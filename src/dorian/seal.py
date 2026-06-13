"""Seal pipeline: scope lint, then run every checker, then write the sidecar + index.

A warrant must be born verifiable: any checker FAIL *or* ERROR at seal time raises
SealError and writes nothing — an ERROR here means the checker could not run at
the moment of maximum freshness, so the warrant could never be revalidated.
The sidecar is written atomically (temp file + os.replace); sidecars are the
source of truth and store rows are derived (a store failure after the sidecar is
written is recoverable via `dorian sync`).

Scope lint runs before any checker: read-set uris matching the TARGET repo's
[tool.dorian.scopes] restricted globs (pyproject.toml) refuse the seal with
ScopeViolation (exit 6) unless allow_restricted is set; the refusal leaves only
a receipted scope_violation event — no sidecar, no warrant/claim rows.
"""

from __future__ import annotations

import fnmatch
import os
import tomllib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from dorian import gitio, store
from dorian.checkers.base import CheckContext, Verdict, run_checker
from dorian.model import (
    CheckerSpec,
    Claim,
    FoldPolicy,
    IntegrityError,
    ReadSet,
    ReadSetEntry,
    Warrant,
    sha256_hex,
)


class SealError(Exception):
    """Sealing refused: bad bindings or a checker that is not green right now."""


class ScopeViolation(SealError):
    """Sealing refused: read-set uris match restricted scope globs (exit 6)."""

    def __init__(self, uris: list[str], patterns: list[str]) -> None:
        super().__init__(
            f"restricted read-set entries: {', '.join(uris)} (matched: {', '.join(patterns)})"
        )
        self.uris = uris
        self.patterns = patterns


class ScopeConfigError(ValueError):
    """[tool.dorian.scopes] could not be read (malformed pyproject.toml): caller
    input, mapped to exit 2 — never a scope violation or a seal refusal."""


def _restricted_globs(repo: Path) -> list[str]:
    """[tool.dorian.scopes].restricted from the TARGET repo's pyproject.toml;
    a missing file, table, or key means no restrictions."""
    path = repo / "pyproject.toml"
    if not path.is_file():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
        raise ScopeConfigError(f"pyproject.toml: {exc}") from None
    node = data
    for key in ("tool", "dorian", "scopes"):
        if not isinstance(node, dict) or key not in node:
            return []  # genuinely absent: unrestricted
        node = node[key]
    if not isinstance(node, dict):
        # present but mistyped must not silently degrade to unrestricted sealing
        raise ScopeConfigError("pyproject.toml: [tool.dorian.scopes] must be a table")
    restricted = node.get("restricted", [])
    if not isinstance(restricted, list) or any(not isinstance(p, str) for p in restricted):
        raise ScopeConfigError(
            "pyproject.toml: [tool.dorian.scopes] restricted must be a list of strings"
        )
    return restricted


def _scope_matches(uri: str, pattern: str) -> bool:
    """Repo-relative fnmatch, plus 'dir/**' as an explicit directory prefix."""
    if fnmatch.fnmatch(uri, pattern):
        return True
    return pattern.endswith("/**") and uri.startswith(pattern[:-2])


def _derive_watch(spec: CheckerSpec, readset: ReadSet) -> CheckerSpec:
    """Fill an empty watch list from the checker program; C5 shell must be explicit
    (its command is opaque, so we cannot know which files it depends on)."""
    if spec.watch:
        return spec
    watch: tuple[str, ...] = ()
    if spec.type == "C1":  # program is a read-set entry id
        entry = next((e for e in readset.entries if e.id == spec.program), None)
        if entry is not None:
            watch = (entry.uri,)
    elif spec.type == "C3":  # path:<p> | (symbol|string|regex):<file>::<operand>
        prefix, _, rest = spec.program.partition(":")
        file = rest.partition("::")[0] if prefix in ("symbol", "string", "regex") else rest
        if file:
            watch = (file,)
    elif spec.type == "C4":  # pytest:<nodeid>: the nodeid's file part is the binding
        prefix, _, nodeid = spec.program.partition(":")
        file = nodeid.partition("::")[0].strip() if prefix == "pytest" else ""
        if file:
            watch = (file,)
        # a malformed program leaves watch empty, but the checker run below
        # ERRORs on it (bad_program), so the seal is refused either way
    elif spec.type == "C5":
        form, _, rest = spec.program.partition(":")
        if form == "shell":
            raise SealError("C5 shell checker requires watch")
        watch = tuple(_c5_data_paths(form, rest))
    return replace(spec, watch=watch)


def _c5_data_paths(form: str, rest: str) -> list[str]:
    """Data path(s) of a typed C5 program; unknown forms yield none (the checker
    run will ERROR on them and sealing refuses anyway)."""
    if form == "snapshot":
        return [rest.strip()] if rest.strip() else []
    if form == "reconcile":
        paths = []
        for side in rest.split("~~"):
            engine, _, body = side.strip().partition(":")
            path = body.partition("::")[0] if engine == "sqlite" else body
            if path:
                paths.append(path)
        return paths
    if form in ("rowcount", "schema", "nullrate", "domain", "freshness"):
        path = rest.split("::")[0]
        return [path] if path else []
    return []


def referenced_paths(claims: list[Claim]) -> list[str]:
    """Repo-relative files the claims' C3/C4/C5 checkers read, in first-seen order.

    This is the auto-captured read-set for `dorian verify`: every C3/C4/C5 program
    names the file it depends on, so the read-set can be derived from the claims
    alone (the same parsing `_derive_watch` uses to fill watch lists). A C1 span
    checker binds a read-set ENTRY (its program is an entry id, not a path), so it
    cannot be auto-captured — raise ValueError directing the caller to an explicit
    `capture` + `seal`. A C5 `shell:` program likewise needs an explicit watch and is
    rejected here for the same reason.
    """
    paths: list[str] = []

    def add(p: str) -> None:
        p = p.strip()
        if p and p not in paths:
            paths.append(p)

    for claim in claims:
        for spec in claim.checkers:
            if spec.type == "C1":
                raise ValueError(
                    f"{claim.id}: C1 span claims bind a read-set entry, not a file; "
                    "use `dorian capture` + `dorian seal` (verify auto-captures C3/C4/C5)"
                )
            prefix, _, rest = spec.program.partition(":")
            if spec.type == "C3":
                add(rest.partition("::")[0] if prefix in ("symbol", "string", "regex") else rest)
            elif spec.type == "C4":
                if prefix == "pytest":  # match _derive_watch; other C4 forms ERROR at seal
                    add(rest.partition("::")[0])
            elif spec.type == "C5":
                if prefix == "shell":
                    raise ValueError(
                        f"{claim.id}: C5 shell checkers need an explicit watch and cannot be "
                        "auto-captured; use `dorian seal` with a watch, or a typed C5 form"
                    )
                for path in _c5_data_paths(prefix, rest):
                    add(path)
    return paths


def _derive_supports(claim: Claim, readset: ReadSet) -> Claim:
    """Bind the read-set entry a C5 snapshot program needs: snapshot:<path>
    ERRORs (no_support_entry) unless the claim supports-binds a read-set entry
    for that path, so a suggest-data-checks fragment pasted verbatim into
    claims.json would never seal. Auto-bind the whole-file entry whose uri
    matches the snapshot path (selector spans hash differently and would FAIL);
    when the read-set has none, the checker run below still ERRORs and the
    seal is refused with the remedy in the message."""
    extra: list[str] = []
    bound_uris = {e.uri for e in readset.entries if e.id in claim.supports}
    for spec in claim.checkers:
        if spec.type != "C5" or not spec.program.startswith("snapshot:"):
            continue
        path = spec.program.partition(":")[2].strip()
        if not path or path in bound_uris:
            continue
        entry = next((e for e in readset.entries if e.uri == path and e.selector is None), None)
        if entry is not None and entry.id not in claim.supports and entry.id not in extra:
            extra.append(entry.id)
            bound_uris.add(path)
    return replace(claim, supports=claim.supports + tuple(extra)) if extra else claim


def _supports(claim: Claim, readset: ReadSet) -> list[ReadSetEntry]:
    entries = []
    for sid in claim.supports:
        try:
            entries.append(readset.entry(sid))
        except KeyError:
            raise SealError(f"{claim.id}: unknown read-set entry {sid!r}") from None
    return entries


def _existing_warrant(sidecar_path: Path) -> Warrant | None:
    """The sidecar already on disk, if present and integrity-valid; else None (a missing
    or corrupt sidecar is simply overwritten by a fresh seal)."""
    if not sidecar_path.is_file():
        return None
    try:
        return Warrant.load(sidecar_path)
    except (IntegrityError, ValueError, KeyError, TypeError, OSError):
        return None


def _material(body: dict) -> dict:
    """A warrant body with only the two per-run wall-clock stamps masked — `sealed_at`
    and produced_by.captured_at — so two seals of otherwise-identical content compare
    equal. Everything else (claims, read-set hashes, git ref, derives, supersede, ...)
    stays in the comparison, so a real change is never masked into a no-op."""
    masked = dict(body)
    masked["sealed_at"] = ""
    masked["produced_by"] = {**body["produced_by"], "captured_at": ""}
    return masked


def seal_artifact(
    repo: Path,
    artifact_uri: str,
    readset: ReadSet,
    claims: list[Claim],
    *,
    supersede: str | None = None,
    allow_restricted: bool = False,
    no_quotes: bool = False,
) -> Warrant:
    """Scope-lint the read-set, run every checker, then write the sidecar + index.

    With no_quotes the sealed sidecar is content-free: every claim anchor keeps
    its line numbers but its quote is dropped (claim text stays — it is the
    user-authored claim, not source content). The warrant id is content-addressed
    over the final, quote-stripped object, so a --no-quotes seal has a different
    id than a quoted seal of the same inputs (expected).
    """
    repo = repo.resolve()

    # 0. claim ids must be unique: the store's (warrant_id, claim_id) PK would
    #    reject a duplicate only AFTER the sidecar is on disk, stranding a
    #    sidecar that breaks every subsequent sync
    seen_ids: set[str] = set()
    for c in claims:
        if c.id in seen_ids:
            raise SealError(f"duplicate claim id: {c.id}")
        seen_ids.add(c.id)

    # 0.5 scope lint, BEFORE any checker runs: a read-set uri matching a
    #     restricted glob refuses the seal, leaving only a receipted
    #     scope_violation event under a synthetic warrant id (events are local
    #     history; no sidecar or warrant/claim rows are written)
    globs = _restricted_globs(repo)
    restricted_uris = sorted(
        {e.uri for e in readset.entries if any(_scope_matches(e.uri, g) for g in globs)}
    )
    if restricted_uris and not allow_restricted:
        patterns = sorted({g for g in globs if any(_scope_matches(u, g) for u in restricted_uris)})
        conn = store.connect(repo)
        try:
            store.append_event(
                conn,
                warrant_id=f"unsealed:{artifact_uri}",
                actor=gitio.actor(repo),
                kind="scope_violation",
                cause={"uris": restricted_uris, "patterns": patterns},
            )
        finally:
            conn.close()
        raise ScopeViolation(restricted_uris, patterns)

    # 0.75 --no-quotes: drop anchor quotes (line numbers and claim text stay)
    if no_quotes:
        claims = [replace(c, anchor=replace(c.anchor, quote="")) if c.anchor else c for c in claims]

    # 1. derive empty checker watch lists from programs, and the supports
    #    binding a C5 snapshot program needs (suggest-data-checks round trip)
    sealed_claims = [
        replace(
            _derive_supports(c, readset),
            checkers=tuple(_derive_watch(s, readset) for s in c.checkers),
        )
        for c in claims
    ]

    # 2. run EVERY checker; FAIL or ERROR refuses the seal and writes nothing
    for claim in sealed_claims:
        ctx = CheckContext(repo=repo, claim=claim, supports=_supports(claim, readset))
        for i, _ in enumerate(claim.checkers):
            result = run_checker(ctx, i)
            if result.verdict is Verdict.FAIL:
                raise SealError(f"FAILED_AT_SEAL: {claim.id}: {result.detail}")
            if result.verdict is Verdict.ERROR:
                raise SealError(f"ERRORED_AT_SEAL: {claim.id}: {result.detail}")

    # 3. derives_from: project read-set entries that are themselves warranted
    derives: list[str] = []
    for entry in readset.entries:
        if entry.scope != "project":
            continue
        sidecar = repo / (entry.uri + ".warrant")
        if sidecar.is_file():
            try:
                wid = Warrant.load(sidecar).id  # integrity-checked
            except (IntegrityError, ValueError, KeyError, TypeError, OSError) as exc:
                raise SealError(f"corrupt warrant sidecar {entry.uri}.warrant: {exc}") from None
            if wid not in derives:
                derives.append(wid)

    # 4. artifact identity at seal time
    data = gitio.working_file(repo, artifact_uri)
    if data is None:
        raise SealError(f"artifact missing: {artifact_uri}")
    artifact_hash = sha256_hex(data)
    try:
        git_ref = gitio.head_ref(repo)
    except gitio.GitError as exc:
        raise SealError(f"cannot resolve HEAD (repo has no commits?): {exc}") from None
    sealed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 5. create, dump sidecar (atomically: temp + replace), index
    warrant = Warrant.create(
        artifact_uri=artifact_uri,
        artifact_hash=artifact_hash,
        git_ref=git_ref,
        produced_by=readset.produced_by,
        read_set=readset.entries,
        claims=tuple(sealed_claims),
        fold_policy=FoldPolicy(),
        sealed_at=sealed_at,
        derives_from=tuple(derives),
        supersedes=supersede,
    )
    sidecar_path = warrant.sidecar_path(repo)

    # idempotent re-seal: if a valid sidecar already records the same MATERIAL body
    # (everything but the two per-run wall-clock stamps), keep its bytes + id so a
    # re-run on unchanged content does not churn the committed sidecar; any real change
    # re-seals. This makes `verify` safe to run repeatedly (pre-commit, CI).
    existing = _existing_warrant(sidecar_path)
    if existing is not None and _material(existing.body_dict()) == _material(warrant.body_dict()):
        warrant = existing
    else:
        tmp_path = sidecar_path.with_name(sidecar_path.name + ".tmp")
        warrant.dump(tmp_path)
        os.replace(tmp_path, sidecar_path)

    conn = store.connect(repo)
    try:
        store.upsert_warrant(conn, warrant, artifact_uri + ".warrant")
        conn.commit()
        # checkers just ran green, so backed claims are VERIFIED right now
        for claim in sealed_claims:
            state = "VERIFIED" if claim.backed else "UNBACKED"
            store.set_claim_state(conn, warrant.id, claim.id, state, warrant.sealed_at)
        # with --allow-restricted the sealed event receipts the allowance
        store.append_event(
            conn,
            warrant_id=warrant.id,
            actor=gitio.actor(repo),
            kind="sealed",
            cause={"allowed_restricted": restricted_uris} if restricted_uris else None,
        )
    finally:
        conn.close()
    return warrant
