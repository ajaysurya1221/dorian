"""`dorian bench public-repos` — public real-repo micro-benchmark harness.

CHECKOUT-ONLY dev tooling, like every `dorian bench` subcommand: it lives in `bench/`, is
NOT shipped in the installed wheel, and may use the `pyyaml` dev dependency. dorian's runtime
core stays zero-dependency. (This is why the harness lives here and not in `src/dorian/` —
the deep-research plan suggested `src/dorian/bench_public.py`, but a benchmark runner that
parses YAML manifests must not pull a runtime dep into the shipped package.)

What it does: clone/reuse a public repo at a FROZEN SHA, seal human-authored claims, apply
mechanical known-truth mutations, run dorian seal + revalidate, and report the TRIGGER layer
(was the affected claim re-checked?) and the TRUTH layer (BROKEN / VERIFIED / ERRORED)
SEPARATELY — never merged into one score.

Honesty invariants (enforced in code, not just docs):
- It produces *reproducibility evidence on frozen SHAs*, never a real-world performance claim;
  the report renderer REFUSES overclaiming language (`guard_overclaim`).
- Claims must be human-reviewed (`status: benchmark-ready`); a draft/generated status yields
  `NO_CLAIMS`, never a fabricated number.
- ERROR is kept distinct from BROKEN. A checker blocked by `--deny-exec`/`--deny-shell`
  (fail-closed policies, NOT sandboxes) folds to ERRORED, never BROKEN/VERIFIED.
- The author seals under a permissive policy (they are trusted); the re-check policy under
  test (`--deny-exec`/`--deny-shell`) applies only to `revalidate`.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dorian import claims_io, symbol_index
from dorian.capture.manual import parse_manual
from dorian.policy import ExecutionPolicy
from dorian.revalidate import RevalResult, revalidate
from dorian.seal import (
    BindingGateError,
    ScopeConfigError,
    ScopeViolation,
    SealError,
    referenced_paths,
    seal_artifact,
)
from dorian.store import DORIAN_DIR

try:  # bench/ is not the installed package; resolve the version best-effort
    from dorian import __version__ as DORIAN_VERSION
except Exception:  # pragma: no cover - defensive
    DORIAN_VERSION = "unknown"

SCHEMA_VERSION = 1
SUPPORTED_LICENSES = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"})
KNOWN_TRUTH = frozenset({"BROKEN", "TRUSTED", "ERRORED_EXPECTED"})
BENCHMARK_READY = "benchmark-ready"

# expected claim STATE per known-truth label (revalidate folds checkers to these states)
_EXPECTED_STATE = {"BROKEN": "BROKEN", "TRUSTED": "TRUSTED", "ERRORED_EXPECTED": "ERRORED"}

# Overclaim guard: union of docs/PUBLIC_BENCHMARK_PROTOCOL.md §8 and the mission boundaries.
_FORBIDDEN_PHRASES = (
    "validated on real repos",
    "works on real repos",
    "proves dorian works",
    "real-world validated",
    "semantic proof",
    "production-grade",
    "production-ready",
    "production grade",  # hyphen-or-space variant
    "production ready",
    "fully solves",
)
# bare tokens (word-bounded) — kept conservative to avoid refusing honest words like
# "validation"/"proof-of-concept"; includes the British spelling of generalise.
_FORBIDDEN_WORDS = (
    "proven",
    "validated",
    "generalizes",
    "generalises",
    "universal",
    "guaranteed",
)

# Required honest framing every rendered report must carry.
REQUIRED_PHRASES = (
    "reproducible on these frozen SHAs",
    "candidate benchmark subjects",
    "trigger and truth layers reported separately",
)


class ManifestError(ValueError):
    """The benchmark manifest is malformed or an eligible entry is not benchmarkable."""


class MutationError(ValueError):
    """A mutation spec is malformed or missing its known-truth label."""


class OverclaimError(ValueError):
    """A rendered report contained forbidden overclaiming language."""


@dataclass(frozen=True)
class RepoSpec:
    name: str
    url: str = ""
    frozen_sha: str = ""
    license: str = ""
    frozen_ref: str | None = None
    public: bool = True
    eligible: bool = True
    needs_exec: bool = False
    reason: str = ""
    setup: tuple[str, ...] = ()
    claims_path: str = ""
    mutations_path: str = ""
    local_path: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class Mutation:
    id: str
    claim_id: str
    file: str
    op: str
    from_: str
    to: str
    known_truth: str


# --------------------------------------------------------------------------- IO


def load_data(path: Path) -> Any:
    """Load a manifest/mutations file by extension: .yaml/.yml via pyyaml (dev dep),
    .json via the stdlib. Zero-dep callers can always use JSON."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - dev envs have pyyaml
            raise ManifestError(
                f"{path}: YAML manifests need the pyyaml dev dependency; install dev "
                "deps or provide a .json manifest"
            ) from exc
        return yaml.safe_load(text)
    return json.loads(text)


def is_executed_evidence(data: Any) -> bool:
    """True only if a manifest/results doc records an actually-executed benchmark.
    The committed `repos.public.json` (`protocol-only-no-results`) is NEVER evidence."""
    if not isinstance(data, dict):
        return False
    return str(data.get("status", "")).lower() in {"executed", "results"}


def load_manifest(path: Path) -> list[RepoSpec]:
    path = Path(path)
    data = load_data(path)
    if not isinstance(data, dict) or not isinstance(data.get("repos"), list):
        raise ManifestError(f"{path}: manifest must be a mapping with a 'repos' list")
    return [_repo_from_dict(raw, i) for i, raw in enumerate(data["repos"])]


def _repo_from_dict(raw: Any, i: int) -> RepoSpec:
    if not isinstance(raw, dict):
        raise ManifestError(f"repos[{i}]: expected a mapping, got {type(raw).__name__}")
    name = raw.get("name")
    if not name:
        raise ManifestError(f"repos[{i}]: missing 'name'")
    eligible = bool(raw.get("eligible", True))
    spec = RepoSpec(
        name=name,
        url=raw.get("url") or "",
        frozen_sha=raw.get("frozen_sha") or "",
        license=raw.get("license") or "",
        frozen_ref=raw.get("frozen_ref"),
        public=bool(raw.get("public", True)),
        eligible=eligible,
        needs_exec=bool(raw.get("needs_exec", False)),
        reason=raw.get("reason") or "",
        setup=tuple(raw.get("setup") or ()),
        claims_path=raw.get("claims") or "",
        mutations_path=raw.get("mutations") or "",
        local_path=raw.get("local_path"),
        notes=raw.get("notes") or "",
    )
    if not eligible:
        # an excluded repo documents WHY; it is skipped at run time, never validated/run
        if not spec.reason:
            raise ManifestError(f"repo {name!r}: eligible:false requires a 'reason'")
        return spec
    if not spec.frozen_sha:
        raise ManifestError(
            f"repo {name!r}: missing 'frozen_sha' (an eligible repo must be frozen)"
        )
    if not spec.license:
        raise ManifestError(f"repo {name!r}: missing 'license'")
    if spec.license not in SUPPORTED_LICENSES:
        raise ManifestError(
            f"repo {name!r}: unsupported license {spec.license!r} "
            f"(allowed: {sorted(SUPPORTED_LICENSES)})"
        )
    if not spec.public:
        raise ManifestError(
            f"repo {name!r}: not public (public:false) — excluded from a public benchmark"
        )
    return spec


def parse_mutations(path: Path) -> list[Mutation]:
    data = load_data(Path(path))
    if not isinstance(data, dict) or not isinstance(data.get("mutations"), list):
        raise MutationError(f"{path}: mutations file must be a mapping with a 'mutations' list")
    out: list[Mutation] = []
    for i, raw in enumerate(data["mutations"]):
        if not isinstance(raw, dict):
            raise MutationError(f"mutations[{i}]: expected a mapping")
        kt = raw.get("known_truth")
        if kt is None:
            raise MutationError(
                f"mutations[{i}]: missing 'known_truth' (one of {sorted(KNOWN_TRUTH)})"
            )
        if kt not in KNOWN_TRUTH:
            raise MutationError(
                f"mutations[{i}]: bad known_truth {kt!r}; expected one of {sorted(KNOWN_TRUTH)}"
            )
        for fld in ("id", "claim_id", "file", "from", "to"):
            if raw.get(fld) is None:
                raise MutationError(f"mutations[{i}]: missing '{fld}'")
        out.append(
            Mutation(
                id=raw["id"],
                claim_id=raw["claim_id"],
                file=raw["file"],
                op=raw.get("op", "replace"),
                from_=raw["from"],
                to=raw["to"],
                known_truth=kt,
            )
        )
    return out


def load_claims_doc(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ManifestError(f"{path}: claims doc must be a JSON object")
    return data


def is_benchmark_ready(doc: Any) -> bool:
    """A claims doc is executable evidence ONLY when a human has marked it benchmark-ready.
    Any draft/generated/missing status is not — the harness reports NO_CLAIMS for it."""
    return isinstance(doc, dict) and doc.get("status") == BENCHMARK_READY


def _claim_checker_types(doc: dict) -> set[str]:
    types: set[str] = set()
    for c in doc.get("claims", []) or []:
        for spec in c.get("checkers", []) or []:
            t = spec.get("type")
            if t:
                types.add(t)
    return types


def build_policy(deny_exec: bool = False, deny_shell: bool = False) -> ExecutionPolicy:
    return ExecutionPolicy.from_flags_and_env(deny_exec=deny_exec, deny_shell=deny_shell)


# --------------------------------------------------------------------- execution


def _clean_state(work: Path, artifact_uri: str, snapshots: dict[str, bytes]) -> None:
    """Restore mutated files and remove any prior warrant/store so each mutation runs
    from the same clean frozen state (independent, deterministic)."""
    for rel, data in snapshots.items():
        (work / rel).write_bytes(data)
    sidecar = work / (artifact_uri + ".warrant")
    if sidecar.is_file():
        sidecar.unlink()
    store_dir = work / DORIAN_DIR
    if store_dir.is_dir():
        shutil.rmtree(store_dir)


def _seal_clean(work: Path, artifact_uri: str, claims: list) -> tuple[bool, str]:
    """Seal at the clean frozen state under a PERMISSIVE policy (the trusted author
    seals; the re-check policy under test applies only to revalidate)."""
    paths = referenced_paths(claims)
    symbol_watch = symbol_index.claim_watch_paths(work, claims)
    for p in sorted({p for ps in symbol_watch.values() for p in ps}):
        if p not in paths:
            paths.append(p)
    try:
        readset = parse_manual(paths, work)
        seal_artifact(
            work, artifact_uri, readset, claims, extra_watch=symbol_watch, policy=ExecutionPolicy()
        )
        return True, ""
    except (
        SealError,
        ScopeViolation,
        BindingGateError,
        ScopeConfigError,
        ValueError,
        OSError,
    ) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _apply_mutation(work: Path, mut: Mutation) -> None:
    if mut.op != "replace":
        raise MutationError(f"mutation {mut.id!r}: unsupported op {mut.op!r} (only 'replace')")
    target = work / mut.file
    text = target.read_text(encoding="utf-8")
    count = text.count(mut.from_)
    if count != 1:
        raise MutationError(
            f"mutation {mut.id!r}: 'from' occurs {count}x in {mut.file} (need exactly 1)"
        )
    target.write_text(text.replace(mut.from_, mut.to, 1), encoding="utf-8")


def _classify(result: RevalResult, claim_id: str) -> tuple[str, bool]:
    """Map a target claim's revalidate outcome to (observed_state, selected). A claim
    re-checked (selected) lands in exactly one bucket; if it is in none, the trigger
    layer missed it (selected=False)."""
    for _, cid, _ in result.broken:
        if cid == claim_id:
            return "BROKEN", True
    for _, cid, _ in result.errored:
        if cid == claim_id:
            return "ERRORED", True
    for _, cid, _ in (*result.passed, *result.relocated):
        if cid == claim_id:
            return "TRUSTED", True
    return "NOT_SELECTED", False


def _run_one_mutation(
    work: Path,
    artifact_uri: str,
    claims: list,
    mut: Mutation,
    policy: ExecutionPolicy,
    snapshots: dict[str, bytes],
    cp_file: Path,
) -> dict:
    _clean_state(work, artifact_uri, snapshots)
    seal_ok, seal_detail = _seal_clean(work, artifact_uri, claims)
    expected = _EXPECTED_STATE[mut.known_truth]
    if not seal_ok:
        _clean_state(work, artifact_uri, snapshots)
        return {
            "mutation_id": mut.id,
            "claim_id": mut.claim_id,
            "known_truth": mut.known_truth,
            "expected_state": expected,
            "observed_state": "SEAL_FAILED",
            "selected": False,
            "match": False,
            "detail": seal_detail,
        }
    _apply_mutation(work, mut)
    cp_file.write_text(mut.file + "\n", encoding="utf-8")
    result = revalidate(work, changed_paths_file=cp_file, policy=policy, checker_source="head")
    observed, selected = _classify(result, mut.claim_id)
    _clean_state(work, artifact_uri, snapshots)
    return {
        "mutation_id": mut.id,
        "claim_id": mut.claim_id,
        "known_truth": mut.known_truth,
        "expected_state": expected,
        "observed_state": observed,
        "selected": selected,
        "match": bool(selected and observed == expected),
        "detail": "",
    }


def _empty_result(spec: RepoSpec, claims_doc: dict, mutations: list[Mutation], status: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark": "public-repos",
        "dorian_version": DORIAN_VERSION,
        "repo": {
            "name": spec.name,
            "url": spec.url,
            "frozen_sha": spec.frozen_sha,
            "frozen_ref": spec.frozen_ref,
            "license": spec.license,
            "needs_exec": spec.needs_exec,
            "eligible": spec.eligible,
        },
        "claims_total": len(claims_doc.get("claims", []) or []),
        "mutations_total": len(mutations),
        "results": [],
        "truth_layer": {
            "broken_expected": 0,
            "broken_observed": 0,
            "trusted_expected": 0,
            "trusted_observed": 0,
            "errored": 0,
        },
        "trigger_layer": {"candidate_claims_checked": 0, "claims_skipped": 0},
        "status": status,
    }


def run_repo(
    spec: RepoSpec,
    checkout: Path,
    claims_doc: dict,
    mutations: list[Mutation],
    *,
    policy: ExecutionPolicy,
    workdir: Path,
) -> dict:
    """Run the benchmark for one repo against an existing local checkout.

    `policy` governs the RE-CHECK (revalidate) — e.g. --deny-exec for an untrusted-fork
    posture. The seal is always done under a permissive policy (the trusted author).
    Returns a deterministic result dict (no wall-clock timestamps)."""
    result = _empty_result(spec, claims_doc, mutations, "NO_CLAIMS")
    if not spec.eligible:
        result["status"] = "SKIPPED_INELIGIBLE"
        return result
    if not is_benchmark_ready(claims_doc):
        return result  # NO_CLAIMS — draft/unreviewed claims are not executed evidence

    # A repo that needs code execution is SKIPPED (not run) under deny-exec, so its
    # code-executing checkers never fold to a spurious ERRORED -> false FAIL. This mirrors
    # the dry-run plan and manifest.v1.yaml ("skipped under --deny-exec"); deny-exec blocks
    # BOTH C4 and C5 (policy.allow_exec). ERRORED stays distinct from BROKEN either way.
    if spec.needs_exec and not policy.allow_exec:
        result["status"] = "SKIPPED_DENY_EXEC"
        return result

    exec_types = _claim_checker_types(claims_doc) & {"C4", "C5"}
    if exec_types and not spec.needs_exec:
        raise ManifestError(
            f"repo {spec.name!r}: claims use {sorted(exec_types)} (code-executing) checkers "
            "but needs_exec is false — set needs_exec: true to run them"
        )

    claims = claims_io.claims_from_dict(claims_doc)
    artifact_uri = claims_doc.get("artifact")
    if not artifact_uri:
        raise ManifestError(f"repo {spec.name!r}: benchmark-ready claims need an 'artifact' path")

    work = workdir / spec.name
    if work.exists():
        shutil.rmtree(work)
    workdir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(checkout, work)

    touched = sorted({m.file for m in mutations})
    snapshots = {rel: (work / rel).read_bytes() for rel in touched if (work / rel).is_file()}
    cp_file = workdir / f"{spec.name}.changed-paths.txt"

    records = [
        _run_one_mutation(work, artifact_uri, claims, m, policy, snapshots, cp_file)
        for m in mutations
    ]
    return _finalize(result, records)


def _finalize(result: dict, records: list[dict]) -> dict:
    result["results"] = records
    tl = result["truth_layer"]
    tl["broken_expected"] = sum(1 for r in records if r["expected_state"] == "BROKEN")
    tl["broken_observed"] = sum(1 for r in records if r["observed_state"] == "BROKEN")
    tl["trusted_expected"] = sum(1 for r in records if r["expected_state"] == "TRUSTED")
    tl["trusted_observed"] = sum(1 for r in records if r["observed_state"] == "TRUSTED")
    tl["errored"] = sum(1 for r in records if r["observed_state"] == "ERRORED")
    trig = result["trigger_layer"]
    trig["candidate_claims_checked"] = sum(1 for r in records if r["selected"])
    trig["claims_skipped"] = sum(1 for r in records if not r["selected"])
    result["status"] = "PASS" if records and all(r["match"] for r in records) else "FAIL"
    if not records:
        result["status"] = "NO_CLAIMS"
    return result


# ----------------------------------------------------------------------- output


def write_results(out_dir: Path, result: dict) -> tuple[Path, Path]:
    """Write deterministic <name>.json (sorted keys) and a <name>.jsonl event stream.
    No wall-clock timestamps are emitted."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = result["repo"]["name"]
    json_path = out_dir / f"{name}.json"
    json_path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    jsonl_path = out_dir / f"{name}.jsonl"
    lines = [
        {
            "event": "repo",
            "name": name,
            "frozen_sha": result["repo"]["frozen_sha"],
            "dorian_version": result["dorian_version"],
            "status": result["status"],
        }
    ]
    for rec in result["results"]:
        lines.append({"event": "mutation", **rec})
    jsonl_path.write_text(
        "".join(json.dumps(ln, sort_keys=True) + "\n" for ln in lines), encoding="utf-8"
    )
    return json_path, jsonl_path


def guard_overclaim(text: str) -> None:
    """Raise OverclaimError if `text` contains forbidden overclaiming language."""
    low = text.lower()
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in low:
            raise OverclaimError(f"forbidden overclaiming phrase: {phrase!r}")
    for word in _FORBIDDEN_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", low):
            raise OverclaimError(f"forbidden overclaiming word: {word!r}")


def render_report(results: list[dict]) -> str:
    """Render the honesty-guarded Markdown report. Trigger and truth layers are reported
    separately; the framing names these as candidate subjects, reproducible on frozen SHAs;
    overclaiming language is refused before the text is returned."""
    executed = [r for r in results if r["status"] in {"PASS", "FAIL"}]
    lines = [
        "# Public real-repo micro-benchmark — results",
        "",
        "These are **candidate benchmark subjects** pinned at frozen commit SHAs. Any numbers "
        "below are **reproducible on these frozen SHAs** only; they do not transfer to other "
        "repositories and are not a real-world performance claim. The **trigger and truth layers "
        "reported separately**: trigger = was the affected claim re-checked; truth = was it "
        "BROKEN / VERIFIED / ERRORED. ERRORED (a checker that could not run) is never an alarm.",
        "",
    ]
    if not executed:
        lines += [
            "## Status: NO_CLAIMS",
            "",
            "No public real-repo benchmark result exists yet. Every subject reported `NO_CLAIMS` "
            "(no human-reviewed `benchmark-ready` claims were executed). This section documents "
            "the candidate frozen SHAs and protocol only — do not cite it as evidence.",
            "",
        ]
    lines += [
        "| repo | sha | license | status | trigger re-checked/skipped"
        " | truth broken/trusted/errored |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        repo = r["repo"]
        tl, trig = r["truth_layer"], r["trigger_layer"]
        lines.append(
            f"| {repo['name']} | `{(repo['frozen_sha'] or '')[:12]}` | {repo['license']} | "
            f"{r['status']} | {trig['candidate_claims_checked']}/{trig['claims_skipped']} | "
            f"{tl['broken_observed']}/{tl['trusted_observed']}/{tl['errored']} |"
        )
    lines += [
        "",
        f"_dorian {results[0]['dorian_version'] if results else DORIAN_VERSION}; "
        "binding selects WHEN a claim is re-checked, the checker decides WHETHER it is false; "
        "`--deny-exec`/`--deny-shell` are fail-closed policies, not sandboxes._",
        "",
    ]
    md = "\n".join(lines)
    missing = [p for p in REQUIRED_PHRASES if p not in md]
    if missing:
        raise OverclaimError(f"report missing required honest framing: {missing}")
    guard_overclaim(md)
    return md


# -------------------------------------------------------------------------- CLI


def _clone_or_reuse(spec: RepoSpec, manifest_dir: Path, workdir: Path) -> Path:
    """Resolve a checkout for a repo: a manifest local_path (offline), or a frozen clone
    cached by SHA under workdir. Network clone is gated to the run path (never unit tests)."""
    if spec.local_path:
        p = (manifest_dir / spec.local_path).resolve()
        if not p.is_dir():
            raise ManifestError(f"repo {spec.name!r}: local_path {p} does not exist")
        return p
    cache = workdir / "checkouts" / f"{spec.name}-{spec.frozen_sha[:12]}"
    if cache.is_dir():
        _verify_cache(spec, cache)  # fail-closed: reuse only a git checkout at the exact SHA
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--quiet", spec.url, str(cache)], check=True)
    subprocess.run(["git", "-C", str(cache), "checkout", "--quiet", spec.frozen_sha], check=True)
    _verify_cache(spec, cache)  # confirm the fresh checkout really landed at the frozen SHA
    return cache


def _verify_cache(spec: RepoSpec, cache: Path) -> None:
    """A reused/fresh cache MUST be a git checkout at EXACTLY the frozen SHA, else fail
    closed (raise) — never produce a benchmark result from an unverifiable checkout. We
    never auto-delete (the dir could hold unrelated data); the operator removes it and
    re-runs. Only the benchmark workdir cache path is ever inspected."""
    if not (cache / ".git").exists():
        raise ManifestError(
            f"repo {spec.name!r}: cache {cache} is not a git checkout — delete it and re-run"
        )
    proc = subprocess.run(
        ["git", "-C", str(cache), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
    )
    head = proc.stdout.strip()
    if proc.returncode != 0 or head != spec.frozen_sha:
        raise ManifestError(
            f"repo {spec.name!r}: cache {cache} is at HEAD {head or '<none>'!r}, expected frozen "
            f"SHA {spec.frozen_sha!r} — delete it and re-run (fail-closed; not auto-deleted)"
        )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="dorian bench public-repos")
    ap.add_argument("--manifest", required=True, help="path to the public manifest (.yaml/.json)")
    ap.add_argument("--out", default="bench/public/results", help="results output dir")
    ap.add_argument("--workdir", default=".bench/public-work", help="clone/work dir (gitignored)")
    ap.add_argument(
        "--repo", action="append", default=[], help="limit to named repo(s); repeatable"
    )
    ap.add_argument("--deny-exec", action="store_true", help="fail-closed: block C4/C5 at re-check")
    ap.add_argument(
        "--deny-shell", action="store_true", help="fail-closed: block C5 shell at re-check"
    )
    ap.add_argument("--report", default=None, help="also render the Markdown report to this path")
    ap.add_argument("--dry-run", action="store_true", help="validate + plan only; no clone/seal")
    ap.add_argument("--json", action="store_true", help="print machine-readable results to stdout")
    args = ap.parse_args(argv)

    manifest_path = Path(args.manifest)
    try:
        specs = load_manifest(manifest_path)
    except (ManifestError, OSError) as exc:
        print(f"dorian bench public-repos: {exc}", file=sys.stderr)
        return 2
    if args.repo:
        wanted = set(args.repo)
        specs = [s for s in specs if s.name in wanted]
        if not specs:
            print(
                f"dorian bench public-repos: no manifest repo matched {sorted(wanted)}",
                file=sys.stderr,
            )
            return 2

    manifest_dir = manifest_path.resolve().parent
    workdir = Path(args.workdir)
    policy = build_policy(deny_exec=args.deny_exec, deny_shell=args.deny_shell)

    if args.dry_run:
        plan = _dry_run_plan(specs, manifest_dir, deny_exec=args.deny_exec)
        print(json.dumps(plan, sort_keys=True, indent=2) if args.json else _render_plan(plan))
        return 0

    results: list[dict] = []
    for spec in specs:
        if not spec.eligible:
            print(f"skip {spec.name}: ineligible ({spec.reason})", file=sys.stderr)
            continue
        claims_doc = _load_optional_claims(manifest_dir, spec)
        mutations = _load_optional_mutations(manifest_dir, spec)
        # don't clone a repo run_repo will skip (deny-exec skip mirrors the dry-run plan)
        will_run = is_benchmark_ready(claims_doc) and not (
            spec.needs_exec and not policy.allow_exec
        )
        try:
            checkout = _clone_or_reuse(spec, manifest_dir, workdir) if will_run else workdir
            result = run_repo(spec, checkout, claims_doc, mutations, policy=policy, workdir=workdir)
        except (ManifestError, MutationError) as exc:
            # fail-closed: a misconfigured manifest or an unverifiable cache yields NO result
            # for that repo (never a fabricated one); other repos still run.
            print(f"skip {spec.name}: {exc}", file=sys.stderr)
            continue
        write_results(Path(args.out), result)
        results.append(result)

    if args.report and results:
        Path(args.report).write_text(render_report(results), encoding="utf-8")
    if args.json:
        print(json.dumps(results, sort_keys=True, indent=2))
    else:
        for r in results:
            print(f"{r['repo']['name']}: {r['status']}")
    return 0


def _load_optional_claims(manifest_dir: Path, spec: RepoSpec) -> dict:
    if spec.claims_path and (manifest_dir / spec.claims_path).is_file():
        return load_claims_doc(manifest_dir / spec.claims_path)
    return {"status": "missing", "claims": []}


def _load_optional_mutations(manifest_dir: Path, spec: RepoSpec) -> list[Mutation]:
    if spec.mutations_path and (manifest_dir / spec.mutations_path).is_file():
        return parse_mutations(manifest_dir / spec.mutations_path)
    return []


def _dry_run_plan(specs: list[RepoSpec], manifest_dir: Path, *, deny_exec: bool) -> dict:
    repos = []
    for spec in specs:
        claims_doc = _load_optional_claims(manifest_dir, spec)
        ready = is_benchmark_ready(claims_doc)
        repos.append(
            {
                "name": spec.name,
                "eligible": spec.eligible,
                "needs_exec": spec.needs_exec,
                "frozen_sha": spec.frozen_sha,
                "license": spec.license,
                "claims_status": claims_doc.get("status", "missing"),
                "benchmark_ready": ready,
                "would_run": bool(spec.eligible and ready and not (spec.needs_exec and deny_exec)),
                "reason": ("" if spec.eligible else f"ineligible: {spec.reason}")
                or ("" if ready else "claims not benchmark-ready (NO_CLAIMS)"),
            }
        )
    return {"benchmark": "public-repos", "dry_run": True, "deny_exec": deny_exec, "repos": repos}


def _render_plan(plan: dict) -> str:
    lines = ["dorian bench public-repos — DRY RUN (no clone, no seal, no results written)", ""]
    for r in plan["repos"]:
        flag = "RUN" if r["would_run"] else "skip"
        lines.append(
            f"  [{flag}] {r['name']}: eligible={r['eligible']} needs_exec={r['needs_exec']} "
            f"claims={r['claims_status']} ({r['reason'] or 'ready'})"
        )
    lines.append("")
    lines.append("No public real-repo benchmark result exists yet — this is a plan only.")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
