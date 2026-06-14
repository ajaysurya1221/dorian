"""CLI command handlers for capture | seal | verify | status | blast | bindings
| revalidate | report | suggest-data-checks | sync | bench (cli.py owns parsing).

Exit codes follow cli.py: 0 ok, 2 usage/infra, 3 DEGRADED, 4 REVOKED/seal-refused,
6 seal-time scope violation (restricted read-set uri without --allow-restricted).
A corrupt or tampered sidecar met while syncing maps to a clean message + exit 4
(integrity) in status/sync, matching seal's handling of the same condition.
`seal --extract` refuses to overwrite an existing claims.json next to the
artifact (exit 2): that file embodies the human review the extract loop exists
to enforce. `status --check` is hash-drift detection only in the kernel: it
compares each read-set entry's sealed hash against the working tree and reports
drifted entries without running any checkers or changing any state (revalidate
does that).
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

from dorian import bindings, claims_io, datachecks, gitio, store, symbol_index
from dorian.blast import blast_conn
from dorian.capture.manual import parse_manual
from dorian.capture.transcript import parse_transcript
from dorian.cli import EXIT_DEGRADED, EXIT_OK, EXIT_REVOKED, EXIT_SCOPE, EXIT_USAGE
from dorian.extract import ExtractUnavailable, extract_claims, extract_claims_consensus
from dorian.model import IntegrityError, ReadSet, ReadSetEntry, Warrant, sha256_hex
from dorian.report import audit_lines, report_events, report_since
from dorian.revalidate import ChangedPathsError, render_json, render_md, render_text, revalidate
from dorian.seal import ScopeConfigError, ScopeViolation, SealError, referenced_paths, seal_artifact

# What store.sync propagates from Warrant.load on a corrupt sidecar: tampered id
# (IntegrityError), non-JSON (JSONDecodeError is a ValueError), valid JSON of the
# wrong shape (KeyError/TypeError), unreadable file (OSError).
_SIDECAR_ERRORS = (IntegrityError, ValueError, KeyError, TypeError, OSError)


def _repo(args: argparse.Namespace) -> Path:
    return Path(args.repo).resolve()


def _artifact_uri(repo: Path, raw: str) -> str:
    """Normalize an artifact argument to a repo-relative posix uri."""
    p = Path(raw)
    resolved = (p if p.is_absolute() else repo / p).resolve()
    try:
        return resolved.relative_to(repo).as_posix()
    except ValueError:
        raise ValueError(f"artifact outside repo: {raw}") from None


def _load_readset(path: Path) -> ReadSet:
    """ReadSet.load with shape errors normalized to ValueError (a usage error):
    valid JSON of the wrong shape raises KeyError/TypeError from from_dict."""
    try:
        return ReadSet.load(path)
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{path}: malformed read-set (missing or bad field: {exc})") from None


def cmd_capture(args: argparse.Namespace) -> int:
    repo = _repo(args)
    if _missing_repo(repo, "capture"):
        return EXIT_USAGE
    if sum(map(bool, (args.transcript, args.manual, args.stdin))) != 1:
        print(
            "dorian capture: provide exactly one of --transcript, --manual, --stdin",
            file=sys.stderr,
        )
        return EXIT_USAGE
    try:
        if args.transcript:
            readset = parse_transcript(Path(args.transcript), repo)
        else:
            specs = args.manual or [line.strip() for line in sys.stdin if line.strip()]
            readset = parse_manual(specs, repo)
    except (ValueError, OSError, gitio.GitError) as exc:
        print(f"dorian capture: {exc}", file=sys.stderr)
        return EXIT_USAGE
    readset.dump(Path(args.out))
    print(
        f"captured {len(readset.entries)} read-set entries "
        f"(coverage {readset.coverage:.2f}) -> {args.out}"
    )
    return EXIT_OK


def cmd_seal(args: argparse.Namespace) -> int:
    repo = _repo(args)
    if _missing_repo(repo, "seal"):
        return EXIT_USAGE
    try:
        artifact_uri = _artifact_uri(repo, args.artifact)
        readset = _load_readset(Path(args.readset))
        if args.claims:
            claims = claims_io.load_claims(Path(args.claims))
        elif args.extract:
            # human-review loop: never seal straight off extraction, and never
            # clobber a claims.json a human may already have reviewed/edited
            out = (repo / artifact_uri).parent / "claims.json"
            if out.exists():
                print(
                    f"dorian seal: {out} already exists; re-run with --claims {out}"
                    " (or delete it to re-extract)",
                    file=sys.stderr,
                )
                return EXIT_USAGE
            data = gitio.working_file(repo, artifact_uri)
            if data is None:
                raise ValueError(f"artifact missing: {artifact_uri}")
            if args.extract_consensus:
                if args.extract_mode not in ("anchor", "candidate"):
                    print(
                        "dorian seal: --extract-consensus requires --extract-mode"
                        " anchor or candidate",
                        file=sys.stderr,
                    )
                    return EXIT_USAGE
                claims = extract_claims_consensus(
                    data.decode("utf-8", errors="replace"),
                    k=args.extract_consensus,
                    model=args.model,
                    cache_dir=repo / store.DORIAN_DIR / "extract-cache",
                    artifact_hash=sha256_hex(data),
                    mode=args.extract_mode,
                )
            else:
                claims = extract_claims(
                    data.decode("utf-8", errors="replace"),
                    model=args.model,
                    cache_dir=repo / store.DORIAN_DIR / "extract-cache",
                    artifact_hash=sha256_hex(data),
                    mode=args.extract_mode,
                )
            claims_io.save_claims(out, claims)
            print(f"wrote {out}: review claims.json then re-run with --claims")
            return EXIT_OK
        else:
            print("dorian seal: provide --claims <file> or --extract", file=sys.stderr)
            return EXIT_USAGE
    except (ValueError, OSError, gitio.GitError, ExtractUnavailable) as exc:
        print(f"dorian seal: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        warrant = seal_artifact(
            repo,
            artifact_uri,
            readset,
            claims,
            supersede=args.supersede,
            allow_restricted=args.allow_restricted,
            no_quotes=args.no_quotes,
        )
    except ScopeViolation as exc:  # before SealError: scope refusal is exit 6, not 4
        print(f"dorian seal: {exc}", file=sys.stderr)
        return EXIT_SCOPE
    except ScopeConfigError as exc:
        print(f"dorian seal: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except SealError as exc:
        print(f"dorian seal: {exc}", file=sys.stderr)
        return EXIT_REVOKED
    print(warrant.id)
    return EXIT_OK


def cmd_verify(args: argparse.Namespace) -> int:
    """One-shot: auto-capture a read-set from the files the claims reference, then
    seal. Collapses `capture` + `seal` for the agent-claims workflow, where each
    C3/C4/C5 checker already names the file it depends on. Seal is born-verifiable,
    so exit 0 means every backed claim passed against the current sources; a failed
    claim refuses the seal (exit 4) and writes nothing. C1 span claims bind a
    read-set entry, not a file, and need explicit `capture` + `seal` (exit 2)."""
    repo = _repo(args)
    if _missing_repo(repo, "verify"):
        return EXIT_USAGE
    try:
        artifact_uri = _artifact_uri(repo, args.artifact)
        claims = claims_io.load_claims(Path(args.claims))
        # widen the auto-captured read-set with the files that DEFINE symbols the
        # claims mention (even when no checker named them): the symbol-definer watch
        # the seal adds is then also captured + hashed + scope-linted honestly
        paths = referenced_paths(claims)
        symbol_watch = symbol_index.claim_symbol_watch_paths(repo, claims)
        for path in sorted({p for ps in symbol_watch.values() for p in ps}):
            if path not in paths:
                paths.append(path)
        readset = parse_manual(paths, repo)
        # a load-bearing claim naming an AMBIGUOUS symbol (>1 definer) is left unbound; do
        # not let that skip be silent — warn so the author binds it explicitly (see A3)
        ambiguous = symbol_index.ambiguous_symbol_mentions(repo, claims)
    except (ValueError, OSError, gitio.GitError) as exc:
        print(f"dorian verify: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        warrant = seal_artifact(
            repo,
            artifact_uri,
            readset,
            claims,
            supersede=args.supersede,
            allow_restricted=args.allow_restricted,
            no_quotes=args.no_quotes,
            extra_watch=symbol_watch,
        )
    except ScopeViolation as exc:  # before SealError: scope refusal is exit 6, not 4
        print(f"dorian verify: {exc}", file=sys.stderr)
        return EXIT_SCOPE
    except ScopeConfigError as exc:
        print(f"dorian verify: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except SealError as exc:
        print(f"dorian verify: {exc}", file=sys.stderr)
        return EXIT_REVOKED
    for cid, symbols in ambiguous.items():
        for sym, files in symbols.items():
            print(
                f"dorian verify: warning: load-bearing claim {cid!r} mentions ambiguous symbol "
                f"{sym!r} (defined in {len(files)} files); left unbound — name the file in a "
                "checker or qualify the reference",
                file=sys.stderr,
            )
    backed = sum(1 for c in claims if c.backed)
    print(warrant.id)
    print(
        f"verified {backed}/{len(claims)} claim(s) against current sources"
        f" -> {artifact_uri}.warrant"
    )
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    repo = _repo(args)
    if _missing_repo(repo, "status"):
        return EXIT_USAGE
    conn = store.connect(repo)
    try:
        try:
            store.sync(repo, conn)
        except _SIDECAR_ERRORS as exc:
            print(f"dorian status: corrupt warrant sidecar: {exc}", file=sys.stderr)
            return EXIT_REVOKED
        warrants = store.get_warrants(conn)
        if args.artifact:
            try:
                uri = _artifact_uri(repo, args.artifact)
            except ValueError as exc:
                print(f"dorian status: {exc}", file=sys.stderr)
                return EXIT_USAGE
            warrants = [w for w in warrants if w["artifact_uri"] == uri]
        payload = []
        for w in warrants:
            counts = Counter(s["state"] for s in store.get_claim_states(conn, w["id"]))
            drifted = _drifted_entries(conn, repo, w["id"]) if args.check else None
            if args.json:
                entry = {
                    "id": w["id"],
                    "artifact_uri": w["artifact_uri"],
                    "trust_state": w["trust_state"],
                    "claim_states": dict(sorted(counts.items())),
                }
                if drifted is not None:
                    entry["drifted"] = drifted
                payload.append(entry)
                continue
            summary = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            print(f"{w['trust_state']:9} {w['artifact_uri']}  {w['id'][:23]}  {summary}")
            for where in drifted or ():
                print(f"  drifted: {where}")
        if args.json:
            print(json.dumps({"warrants": payload}, sort_keys=True))
        states = {w["trust_state"] for w in warrants}
        if "REVOKED" in states:
            return EXIT_REVOKED
        if "DEGRADED" in states:
            return EXIT_DEGRADED
        return EXIT_OK
    finally:
        conn.close()


def _drifted_entries(conn, repo: Path, warrant_id: str) -> list[str]:
    """Kernel --check: stored read-set hashes vs working tree; no checker runs."""
    rows = conn.execute(
        "SELECT uri, selector, hash FROM resource WHERE warrant_id = ?"
        " AND scope = 'project' ORDER BY entry_id",
        (warrant_id,),
    )
    return [
        f"{r['uri']}:{r['selector']}" if r["selector"] else r["uri"]
        for r in rows
        if gitio.working_hash(repo, r["uri"], r["selector"]) != r["hash"]
    ]


def _missing_repo(repo: Path, command: str) -> bool:
    """True (with a usage message) when --repo is not a directory. Checked up
    front: store.connect's mkdir would raise FileNotFoundError — an OSError, so
    in _SIDECAR_ERRORS — mislabeling an infra/usage failure as exit 4."""
    if repo.is_dir():
        return False
    print(f"dorian {command}: not a directory: {repo}", file=sys.stderr)
    return True


def cmd_blast(args: argparse.Namespace) -> int:
    """Downstream warrants affected by a path or warrant (read-only walk of the
    derives index): one line per hit, or a --json payload; always exit 0 unless
    the input is unusable (2) or a sidecar is corrupt while syncing (4)."""
    repo = _repo(args)
    if _missing_repo(repo, "blast"):
        return EXIT_USAGE
    target = args.target
    if not target.startswith("sha256:"):
        try:
            target = _artifact_uri(repo, target)
        except ValueError as exc:
            print(f"dorian blast: {exc}", file=sys.stderr)
            return EXIT_USAGE
    conn = store.connect(repo)
    try:
        try:
            store.sync(repo, conn)
        except _SIDECAR_ERRORS as exc:
            print(f"dorian blast: corrupt warrant sidecar: {exc}", file=sys.stderr)
            return EXIT_REVOKED
        hits = blast_conn(conn, target, args.max_depth)
    finally:
        conn.close()
    if args.json:
        print(json.dumps({"target": target, "hits": hits}, sort_keys=True))
        return EXIT_OK
    if not hits:
        print("no downstream warrants")
        return EXIT_OK
    for h in hits:
        print(f"{h['trust_state']:9} {h['artifact_uri']}  depth={h['depth']}  via {h['via'][:23]}")
    return EXIT_OK


def cmd_bindings(args: argparse.Namespace) -> int:
    """Binding-quality diagnostics for one warranted artifact (sidecar is the
    source of truth; no checker runs, no state changes). Always exit 0 when the
    warrant is readable — flags inform, they never gate. Usage guards exit 2;
    a tampered sidecar is integrity (exit 4), matching status/sync."""
    repo = _repo(args)
    if _missing_repo(repo, "bindings"):
        return EXIT_USAGE
    try:
        uri = _artifact_uri(repo, args.artifact)
    except ValueError as exc:
        print(f"dorian bindings: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not (repo / (uri + ".warrant")).is_file():
        print(f"dorian bindings: no warrant sidecar for {uri}", file=sys.stderr)
        return EXIT_USAGE
    try:
        diags = bindings.analyze(repo, uri)
    except gitio.GitError as exc:  # not a git checkout: usage, not integrity
        print(f"dorian bindings: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except _SIDECAR_ERRORS as exc:
        print(f"dorian bindings: corrupt warrant sidecar: {exc}", file=sys.stderr)
        return EXIT_REVOKED
    if args.json:
        print(json.dumps({"artifact_uri": uri, "claims": diags}, sort_keys=True))
        return EXIT_OK
    flagged = 0
    for d in diags:
        flagged += bool(d["flags"])
        print(f"{d['claim_id']}  flags: {', '.join(d['flags']) or 'none'}")
        for m in d["mentions"]:
            print(f"  {m['token']} -> unwatched: {', '.join(m['unwatched_files'])}")
    print(f"{len(diags)} claim(s), {flagged} flagged")
    return EXIT_OK


def cmd_bind_suggest(args: argparse.Namespace) -> int:
    """Read-only: for each claim, the symbol-definer files `verify` would auto-bind
    (excluding ones a checker already names) plus any AMBIGUOUS symbols it would skip.
    Lets an explicit `seal --readset` author add the binding deliberately. Writes
    nothing, runs no checker, never a gate (exit 0); usage problems exit 2."""
    repo = _repo(args)
    if _missing_repo(repo, "bind-suggest"):
        return EXIT_USAGE
    try:
        claims = claims_io.load_claims(Path(args.claims))
    except (ValueError, OSError) as exc:
        print(f"dorian bind-suggest: {exc}", file=sys.stderr)
        return EXIT_USAGE
    watch = symbol_index.claim_symbol_watch_paths(repo, claims)
    ambiguous = symbol_index.ambiguous_symbol_mentions(repo, claims)
    suggestions: list[dict] = []
    for c in claims:
        try:
            covered = set(referenced_paths([c]))
        except ValueError:
            covered = set()  # C1 span / C5 shell: no auto-derivable read-set to compare
        bind = [f for f in watch.get(c.id, ()) if f not in covered]
        amb = {s: list(files) for s, files in ambiguous.get(c.id, {}).items()}
        if bind or amb:
            suggestions.append({"claim_id": c.id, "bind": bind, "ambiguous": amb})
    if args.json:
        print(json.dumps({"suggestions": suggestions}, sort_keys=True))
        return EXIT_OK
    for s in suggestions:
        if s["bind"]:
            print(f"{s['claim_id']}  bind: {', '.join(s['bind'])}")
        for sym, files in sorted(s["ambiguous"].items()):
            print(f"{s['claim_id']}  ambiguous: {sym} ({len(files)} definers, unbound)")
    print(f"{len(suggestions)} claim(s) with binding suggestions")
    return EXIT_OK


def cmd_rebind(args: argparse.Namespace) -> int:
    """Re-derive a warrant's symbol-definer watches with the CURRENT binding logic and
    re-seal it (born-verifiable, superseding the old id) — upgrading a warrant sealed
    before the symbol index existed so a future change to a mentioned symbol's defining
    file re-checks the claim. Re-runs every checker, so a claim that has SINCE become
    false refuses the re-seal (exit 4) and is never laundered into a fresh TRUSTED. The
    original read-set and producing-run identity are kept verbatim and the watch only ever
    WIDENS (the newly bound definer files are added to both); when nothing new binds, rebind
    is an idempotent no-op that leaves the sidecar and its id untouched. C1 span claims bind
    a read-set entry, not a file, and are not auto-rebindable (exit 2)."""
    repo = _repo(args)
    if _missing_repo(repo, "rebind"):
        return EXIT_USAGE
    try:
        uri = _artifact_uri(repo, args.artifact)
    except ValueError as exc:
        print(f"dorian rebind: {exc}", file=sys.stderr)
        return EXIT_USAGE
    sidecar = repo / (uri + ".warrant")
    if not sidecar.is_file():
        print(f"dorian rebind: no warrant sidecar for {uri}", file=sys.stderr)
        return EXIT_USAGE
    try:
        old = Warrant.load(sidecar)
    except _SIDECAR_ERRORS as exc:
        print(f"dorian rebind: corrupt warrant sidecar: {exc}", file=sys.stderr)
        return EXIT_REVOKED
    claims = list(old.claims)
    if any(spec.type == "C1" for c in claims for spec in c.checkers):
        # C1 span claims bind a read-set entry (an artifact span), not a code file, so the
        # symbol index has nothing to widen — refuse rather than silently reseal/no-op.
        print(
            "dorian rebind: C1 span claims bind a read-set entry, not a file; "
            "rebind them with `dorian capture` + `dorian seal`",
            file=sys.stderr,
        )
        return EXIT_USAGE
    symbol_watch = symbol_index.claim_symbol_watch_paths(repo, claims)
    new_paths = {p for ps in symbol_watch.values() for p in ps}
    already_watched = {w for c in claims for spec in c.checkers for w in spec.watch}
    if new_paths <= already_watched:
        # nothing new to bind: an idempotent no-op. Leave the sidecar (and its id)
        # untouched rather than minting a fresh id and re-stamping the supersede chain.
        print(old.id)
        print(f"{uri}.warrant already covers its symbol-definer watches; nothing to rebind")
        return EXIT_OK
    # Preserve the original read-set and producing-run identity verbatim (the warrant's
    # hashed record of what the run read is an honesty artifact); only ADD the newly bound
    # definer files, under non-colliding ids so each claim's supports references stay valid.
    old_entries = list(old.read_set)
    existing_uris = {e.uri for e in old_entries}
    used_ids = {e.id for e in old_entries}
    next_idx = 0
    try:
        head = gitio.head_ref(repo)
        added: list[ReadSetEntry] = []
        for path in sorted(p for p in new_paths if p not in existing_uris):
            h = gitio.working_hash(repo, path, None)
            if h is None:
                raise ValueError(f"missing file: {path}")
            while f"rs-{next_idx}" in used_ids:  # avoid every existing id (ids may be sparse)
                next_idx += 1
            entry_id = f"rs-{next_idx}"
            used_ids.add(entry_id)
            added.append(
                ReadSetEntry(
                    id=entry_id,
                    uri=path,
                    selector=None,
                    hash=h,
                    version=head,
                    scope="project",
                )
            )
    except (OSError, ValueError, gitio.GitError) as exc:
        print(f"dorian rebind: {exc}", file=sys.stderr)
        return EXIT_USAGE
    readset = ReadSet(entries=tuple(old_entries + added), produced_by=old.produced_by)
    try:
        warrant = seal_artifact(
            repo, uri, readset, claims, supersede=old.id, extra_watch=symbol_watch
        )
    except ScopeViolation as exc:  # before SealError: scope refusal is exit 6, not 4
        print(f"dorian rebind: {exc}", file=sys.stderr)
        return EXIT_SCOPE
    except ScopeConfigError as exc:
        print(f"dorian rebind: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except SealError as exc:
        print(f"dorian rebind: {exc}", file=sys.stderr)
        return EXIT_REVOKED
    print(warrant.id)
    print(f"rebound {uri}.warrant (supersedes {old.id})")
    return EXIT_OK


def cmd_revalidate(args: argparse.Namespace) -> int:
    repo = _repo(args)
    changed_file = Path(args.changed_paths) if args.changed_paths else None
    if (args.since is None) == (changed_file is None):
        print(
            "dorian revalidate: provide exactly one of --since <ref> or --changed-paths <file>",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if _missing_repo(repo, "revalidate"):
        return EXIT_USAGE
    try:
        result = revalidate(
            repo,
            since=args.since,
            changed_paths_file=changed_file,
            enable_c2lite=args.enable_c2lite,
        )
    # user-input failures, before the broader ValueError in _SIDECAR_ERRORS:
    # an unresolvable --since ref or an unreadable --changed-paths listing
    # (revalidate reads the listing exactly once and tags its failures)
    except (gitio.GitError, ChangedPathsError) as exc:
        print(f"dorian revalidate: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except _SIDECAR_ERRORS as exc:
        print(f"dorian revalidate: corrupt warrant sidecar: {exc}", file=sys.stderr)
        return EXIT_REVOKED
    renderer = {"text": render_text, "json": render_json, "md": render_md}[args.format]
    print(renderer(result), end="")
    return result.exit_code


def cmd_report(args: argparse.Namespace) -> int:
    repo = _repo(args)
    if _missing_repo(repo, "report"):
        return EXIT_USAGE
    try:
        if args.audit:
            # full local history (one JSON line per event); --since filters only
            # when given explicitly — the digest's 7d default does not apply
            for line in audit_lines(repo, args.since):
                print(line)
        elif args.json:
            print(json.dumps(report_events(repo, args.since or "7d"), sort_keys=True))
        else:
            print(report_since(repo, args.since or "7d"), end="")
    except ValueError as exc:
        print(f"dorian report: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_OK


# dorian bench subcommand -> (bench module, keeps-subcommand-token flag).
# Single-purpose modules get the remaining argv only (no token to re-parse).
_BENCH_DISPATCH: dict[str, tuple[str, bool]] = {
    "mutation": ("bench.controlled_mutation", False),
    "large-mutation": ("bench.large_mutation", False),
    "churn": ("bench.churn", False),
}


def cmd_bench(args: argparse.Namespace) -> int:
    """Alias for the repo-local benchmark tooling: bench/ is a repo-root
    package (not installed with dorian), so retry the lazy per-invocation
    import with the current checkout on sys.path before giving up."""
    rest = list(args.rest)
    subcommand = rest[0] if rest else ""
    dispatch = _BENCH_DISPATCH.get(subcommand)
    if dispatch is None:
        choices = ", ".join(sorted(_BENCH_DISPATCH))
        print(
            f"dorian bench: error: invalid subcommand {subcommand!r} (choose from {choices})",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_USAGE)
    module_name, keeps_token = dispatch
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        sys.path.insert(0, os.getcwd())
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            print(
                "dorian bench: repo-local benchmark tooling requires a dorian checkout"
                " (bench/ package not found)",
                file=sys.stderr,
            )
            return EXIT_USAGE
    return module.main(rest if keeps_token else rest[1:])


def cmd_suggest_data_checks(args: argparse.Namespace) -> int:
    """Print born-verifiable C5 checker SUGGESTIONS for a data file as a JSON
    fragment {"checkers": [...]} — for a human to review and paste into
    claims.json, never applied automatically. Input problems (missing,
    unsupported, or unreadable file; unknown column) are usage errors (2)."""
    repo = _repo(args)
    if _missing_repo(repo, "suggest-data-checks"):
        return EXIT_USAGE
    try:
        uri = _artifact_uri(repo, args.path)
        cols = [c.strip() for c in args.columns.split(",") if c.strip()] if args.columns else None
        checkers = datachecks.suggest(repo, uri, columns=cols)
        payload = json.dumps({"checkers": checkers}, indent=2, sort_keys=True)
        if args.out:  # unwritable --out is a usage error, not a traceback
            Path(args.out).write_text(payload + "\n")
    except (ValueError, OSError) as exc:
        print(f"dorian suggest-data-checks: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(payload)
    return EXIT_OK


def cmd_sync(args: argparse.Namespace) -> int:
    repo = _repo(args)
    if _missing_repo(repo, "sync"):
        return EXIT_USAGE
    conn = store.connect(repo)
    try:
        n = store.sync(repo, conn)
    except _SIDECAR_ERRORS as exc:
        print(f"dorian sync: corrupt warrant sidecar: {exc}", file=sys.stderr)
        return EXIT_REVOKED
    finally:
        conn.close()
    print(f"indexed {n} warrant(s)")
    return EXIT_OK
