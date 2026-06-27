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
from collections.abc import Mapping
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
from dorian.policy import ExecutionPolicy

# C3 prefixes whose program is `<file>::<operand>` (so the watched file is the head
# before `::`); `path:` is the exception (its whole operand is the path). Mirrors
# `c3_ref._FILE_OPERAND_FORMS` — kept in sync so a new C3 subgrammar binds its file.
_C3_FILE_OPERAND_FORMS = ("symbol", "string", "regex", "py-signature", "py-const", "code")


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


class BindingGateError(SealError):
    """--binding-gate=fail refused the seal: high-risk weak-binding diagnostics
    require review. Carries the blocking findings; NO sidecar is written. Weak
    binding is a false-CONFIDENCE smell, never a claim being false — so this maps
    to the existing seal-refused exit (4), not to any trust or claim state."""

    def __init__(self, findings: list[dict]) -> None:
        self.findings = findings
        ids = ", ".join(repr(d["claim_id"]) for d in findings)
        super().__init__(
            f"--binding-gate=fail refused seal: {len(findings)} claim(s) with high-risk "
            f"weak-binding diagnostics require review ({ids}); no sidecar written"
        )


class StrengthGateError(SealError):
    """--strength-gate=fail refused the seal: a load-bearing claim's strongest checker
    is too weak to falsify its kind (a `behavior` claim backed only by existence/text/an
    opaque shell, a `quantity` claim backed only by existence, or an unbacked claim).
    The TRUTH-axis companion to BindingGateError (which gates WHEN a claim re-checks;
    this gates WHETHER its checker can falsify it). Carries the blocking findings; NO
    sidecar is written. Weak truth backing is false CONFIDENCE, never a claim being
    false — so this maps to the existing seal-refused exit (4), not to any trust or
    claim state."""

    def __init__(self, findings: list[dict]) -> None:
        self.findings = findings
        ids = ", ".join(repr(d["claim_id"]) for d in findings)
        super().__init__(
            f"--strength-gate=fail refused seal: {len(findings)} load-bearing claim(s) whose "
            f"checker is too weak to falsify the claim's kind require review ({ids}); "
            "no sidecar written"
        )


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
    elif spec.type == "C3":  # path:<p> | <form>:<file>::<op> | config-value:<path>:<key>:<lit>
        prefix, _, rest = spec.program.partition(":")
        if prefix in _C3_FILE_OPERAND_FORMS:
            file = rest.partition("::")[0]
        elif prefix == "config-value":
            file = rest.partition(":")[0]  # config-value:<path>:<key>:<literal>
        else:  # path:<p>
            file = rest
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


def _add_watch(spec: CheckerSpec, extra: tuple[str, ...]) -> CheckerSpec:
    """Append symbol-definer watch paths (from symbol_index.claim_symbol_watch_paths)
    the checker did not already name: existing order preserved, then the new sorted
    paths, deduped. Strictly additive — it only ever widens a watch set, so it can
    add a missed re-check trigger but never remove or rewrite an existing one."""
    new = tuple(p for p in extra if p not in spec.watch)
    return replace(spec, watch=spec.watch + new) if new else spec


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
                if prefix in _C3_FILE_OPERAND_FORMS:
                    add(rest.partition("::")[0])
                elif prefix == "config-value":  # config-value:<path>:<key>:<literal>
                    add(rest.partition(":")[0])
                else:  # path:<p>
                    add(rest)
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
    extra_watch: Mapping[str, tuple[str, ...]] | None = None,
    binding_gate: str = "off",
    strength_gate: str = "off",
    policy: ExecutionPolicy | None = None,
) -> Warrant:
    """Scope-lint the read-set, run every checker, then write the sidecar + index.

    binding_gate (off | warn | fail; default off) is the opt-in weak-binding review
    gate. It NEVER changes default behavior, trust/claim state, the schema, or fold
    policy. 'off' and 'warn' seal exactly as before (warn's diagnostics are printed
    by the caller after a successful seal). 'fail' computes the same binding
    diagnostics on the candidate claims AFTER every checker passes but BEFORE any
    sidecar/store write, and raises BindingGateError (writing nothing) when a claim
    carries a high-risk weak-binding flag. Weak binding is a false-confidence smell,
    never proof a claim is false.

    strength_gate (off | warn | fail; default off) is the TRUTH-axis companion: where
    binding_gate gates WHEN a claim re-checks, this gates WHETHER its checker can falsify
    it. 'fail' computes the strength/adequacy diagnostics on the candidate claims (same
    after-checkers / before-write position as binding_gate, so it is atomic no-write) and
    raises StrengthGateError when a LOAD-BEARING claim is high-risk — its strongest checker
    is too weak for its kind (a behavior claim backed only by existence/text/opaque shell,
    a quantity claim backed only by existence, or an unbacked claim). Like binding_gate it
    never changes default behavior, trust/claim state, the schema, or fold policy, and never
    marks a claim false.

    extra_watch (claim id -> repo-relative paths) widens a backed claim's checker
    watch set with files the claim depends on but its checker did not name — the
    symbol-definer binding `dorian verify` derives from claim text. It is purely
    additive (never narrows a watch) and is not applied on the explicit `seal`
    path, so `seal --readset` semantics are unchanged.

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

    # 1. derive empty checker watch lists from programs, the supports binding a
    #    C5 snapshot program needs (suggest-data-checks round trip), and — when the
    #    caller passes extra_watch — the symbol-definer files a claim mentions but
    #    its checker never named (additive; widens the watch, never narrows it)
    sealed_claims = []
    for c in claims:
        derived = _derive_supports(c, readset)
        checkers = tuple(_derive_watch(s, readset) for s in derived.checkers)
        extra = extra_watch.get(c.id) if extra_watch else None
        if extra:
            checkers = tuple(_add_watch(s, extra) for s in checkers)
        sealed_claims.append(replace(derived, checkers=checkers))

    # 2. run EVERY checker; FAIL or ERROR refuses the seal and writes nothing.
    #    Under deny-exec/deny-shell, a blocked C4/C5-shell checker ERRORs here,
    #    so the warrant is never born trusted with an un-run executable claim.
    exec_policy = policy if policy is not None else ExecutionPolicy()
    for claim in sealed_claims:
        ctx = CheckContext(
            repo=repo, claim=claim, supports=_supports(claim, readset), policy=exec_policy
        )
        for i, _ in enumerate(claim.checkers):
            result = run_checker(ctx, i)
            if result.verdict is Verdict.FAIL:
                raise SealError(f"FAILED_AT_SEAL: {claim.id}: {result.detail}")
            if result.verdict is Verdict.ERROR:
                raise SealError(f"ERRORED_AT_SEAL: {claim.id}: {result.detail}")

    # 2.5 opt-in weak-binding gate (default off). Runs AFTER every checker passed
    #     (so a false claim is still refused first, by step 2) and BEFORE any sidecar
    #     or store write below — so `fail` is atomic no-write. It only ever REFUSES;
    #     it never marks a claim broken/false and never touches trust/claim state.
    #     `warn` does not refuse here: the caller prints its diagnostics post-seal.
    if binding_gate == "fail":
        from dorian import bindings  # lazy: bindings lazily imports seal helpers

        diags = bindings.analyze_candidate(
            repo,
            artifact_uri=artifact_uri,
            claims=sealed_claims,
            entry_uris={e.id: e.uri for e in readset.entries},
        )
        blocking = bindings.blocking_findings(diags)
        if blocking:
            raise BindingGateError(blocking)

    # 2.6 opt-in TRUTH-axis strength gate (default off). The truth companion to the
    #     trigger-axis binding gate above: that gates WHEN a claim re-checks; this gates
    #     WHETHER its checker can falsify it. Same atomic-no-write position — after every
    #     checker passed (step 2) and BEFORE any sidecar/store write below — so `fail` is
    #     atomic no-write. It only ever REFUSES a load-bearing high-risk claim; it never
    #     marks a claim broken/false and never touches trust/claim state. The strength
    #     import is lazy so the default seal path never pulls in the advisory module.
    if strength_gate == "fail":
        from dorian import strength

        blocking = strength.gate_blocking(strength.analyze(repo, sealed_claims))
        if blocking:
            raise StrengthGateError(blocking)

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
        # per-process temp name so two concurrent seals of the SAME artifact (e.g.
        # pre-commit + CI + editor-on-save) each promote their own private file via
        # os.replace, instead of racing on one shared `.tmp` and tearing it
        tmp_path = sidecar_path.with_name(f"{sidecar_path.name}.{os.getpid()}.tmp")
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
