"""`release_state.py` — deterministic release-state evaluator for dorian 1.0.0.

Replaces ad-hoc human "is it ready?" judgement with a machine-verifiable state
machine. It reads only facts it can derive deterministically (version files, the
git tag/commit relationship, workflow files, doc text, claim status, benchmark
result files) plus a recorded `release_evidence.json` of gate outcomes (lint /
tests / build / benchmark determinism) that an interactive agent cannot fake into
existence. From the state table it emits exactly ONE decision:

    PROMOTE_1_0_READY | CUT_RC2_READY | STAY_RC
    HALT_UNSAFE | HALT_INSUFFICIENT_EVIDENCE | HALT_PUBLISH_NOT_CONFIGURED
    HALT_VERSION_MISMATCH | HALT_NONDETERMINISTIC

It is CHECKOUT-ONLY dev tooling (lives in bench/, not shipped in the wheel),
stdlib-only, never touches the network, never calls a model, never prompts. The
core `evaluate()` is a pure function over (facts, evidence) so it is exhaustively
mockable; `gather_facts()` does the real read-only IO; `main()` ties them together.

Usage:
    uv run python bench/release_state.py --target 1.0.0 --json --strict
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = 1
RC_TAG = "v1.0.0rc1"

# Decisions ------------------------------------------------------------------
_HALTS = (
    "HALT_VERSION_MISMATCH",
    "HALT_UNSAFE",
    "HALT_NONDETERMINISTIC",
    "HALT_PUBLISH_NOT_CONFIGURED",
    "HALT_INSUFFICIENT_EVIDENCE",
)  # listed in resolution priority order (first wins)
_GO = ("PROMOTE_1_0_READY", "CUT_RC2_READY", "STAY_RC")

# Overclaim guard mirrors bench/public_repos.py and docs/VALIDATION_HONESTY.md.
_FORBIDDEN_PHRASES = (
    "validated on real repos",
    "works on real repos",
    "proves dorian works",
    "100% accurate",
    "semantic proof",
    "production-grade",
    "production-ready",
    "fully solves",
)
_FORBIDDEN_WORDS = ("proven", "validated", "generalizes", "generalises", "universal", "guaranteed")
_REQUIRED_FRAMING = (
    "reproducible on these frozen SHAs",
    "candidate benchmark subjects",
    "trigger and truth layers reported separately",
)

_GATE_KEYS = ("lint_ok", "format_ok", "tests_ok", "build_ok", "install_smoke_ok")


def exit_code(decision: str) -> int:
    """0 for a GO decision (PROMOTE/CUT_RC2/STAY_RC), nonzero for any HALT."""
    return 0 if decision in _GO else 1


def _overclaims(text: str) -> list[str]:
    low = text.lower()
    hits = [p for p in _FORBIDDEN_PHRASES if p in low]
    hits += [w for w in _FORBIDDEN_WORDS if re.search(rf"\b{re.escape(w)}\b", low)]
    return hits


# --------------------------------------------------------------------- states


def _state(sid, name, status, evidence, *, blocker=False, halt=None):
    st = {"id": sid, "name": name, "status": status, "evidence": list(evidence), "blocker": blocker}
    if halt:
        st["halt"] = halt
    return st


def _gate(value, *, strict):
    """Resolve a recorded gate result. True/False are taken as-is; a missing gate
    is SKIP normally but a hard FAIL under --strict (no fabricated confidence)."""
    if value is True:
        return "PASS", None
    if value is False:
        return "FAIL", "HALT_UNSAFE"
    return ("FAIL", "HALT_INSUFFICIENT_EVIDENCE") if strict else ("SKIP", None)


def evaluate(
    facts: dict,
    evidence: dict,
    *,
    target: str = "1.0.0",
    strict: bool = True,
    require_publish: bool = False,
) -> dict:
    """Pure evaluation of the S0-S11 state table. No IO, no network, no prompt."""
    states: list[dict] = []
    wf = facts.get("workflows", {})

    # S0 — repo clean OR dirty only with expected Week-1/2/3 files.
    unexpected = facts.get("unexpected_dirty", [])
    states.append(
        _state(
            "S0",
            "repo_known",
            "PASS" if not unexpected else "FAIL",
            [f"unexpected dirty paths: {sorted(unexpected)}"]
            if unexpected
            else ["working tree dirty only with expected release-branch files"],
            blocker=True,
            halt=None if not unexpected else "HALT_UNSAFE",
        )
    )

    # S1 — version files agree AND the rc tag exists.
    vers = {facts.get("pyproject_version"), facts.get("init_version"), facts.get("lock_version")}
    version_ok = len(vers) == 1 and None not in vers and facts.get("rc_tag_exists")
    states.append(
        _state(
            "S1",
            "version_gate",
            "PASS" if version_ok else "FAIL",
            [
                f"pyproject={facts.get('pyproject_version')} init={facts.get('init_version')} "
                f"lock={facts.get('lock_version')} rc_tag={facts.get('rc_tag')} "
                f"exists={facts.get('rc_tag_exists')} "
                f"features_after_rc1={facts.get('features_after_rc1')}"
            ],
            blocker=True,
            halt=None if version_ok else "HALT_VERSION_MISMATCH",
        )
    )

    # S2 — Week-2 capabilities present (config-value impl+doc, audit atomicity).
    w2 = facts.get("week2", {})
    w2_ok = bool(
        w2.get("config_value_impl") and w2.get("config_value_doc") and w2.get("atomicity_impl")
    )
    states.append(
        _state(
            "S2",
            "week2_complete",
            "PASS" if w2_ok else "FAIL",
            [
                f"config_value_impl={w2.get('config_value_impl')} doc={w2.get('config_value_doc')} "
                f"atomicity_impl={w2.get('atomicity_impl')}"
            ],
        )
    )

    # S3 — local test matrix (lint/format/tests/build/install smoke).
    s3_status, s3_halt, s3_ev = "PASS", None, []
    for k in _GATE_KEYS:
        st, halt = _gate(evidence.get(k), strict=strict)
        s3_ev.append(f"{k}={evidence.get(k)} -> {st}")
        if st != "PASS":
            s3_status = "FAIL"
            s3_halt = s3_halt or halt
    s3_ev.append(
        f"tests_failed={evidence.get('tests_failed')} tests_total={evidence.get('tests_total')}"
    )
    states.append(_state("S3", "test_matrix_local", s3_status, s3_ev, blocker=True, halt=s3_halt))

    # S4 — public benchmark harness exists, verifies cache, ERROR distinct from BROKEN.
    h = facts.get("harness", {})
    s4_ok = bool(h.get("exists") and h.get("verify_cache") and h.get("error_distinct_broken"))
    states.append(
        _state(
            "S4",
            "public_bench_harness",
            "PASS" if s4_ok else "FAIL",
            [
                f"exists={h.get('exists')} verify_cache={h.get('verify_cache')} "
                f"error_distinct_broken={h.get('error_distinct_broken')}"
            ],
            blocker=True,
            halt=None if s4_ok else "HALT_UNSAFE",
        )
    )

    # S5 — machine-derived, proof-backed benchmark-ready claims (not human semantic claims).
    mc = facts.get("machine_claims", [])
    s5_ok = len(mc) >= 1
    states.append(
        _state(
            "S5",
            "machine_derived_claims",
            "PASS" if s5_ok else "FAIL",
            [f"repos with proof-backed machine-derived claims: {sorted(mc)}"],
        )
    )

    # S6 — public benchmark executed (>=2 repos), deterministic x2, every known-truth matched.
    bench = evidence.get("benchmark", {}) or {}
    if not bench.get("executed"):
        states.append(
            _state(
                "S6",
                "public_bench_executed",
                "SKIP",
                ["benchmark not executed — no machine-derived results"],
            )
        )
    elif not bench.get("deterministic", False):
        states.append(
            _state(
                "S6",
                "public_bench_executed",
                "FAIL",
                [f"nondeterministic fields run1/run2: {bench.get('nondeterministic_fields')}"],
                blocker=True,
                halt="HALT_NONDETERMINISTIC",
            )
        )
    elif not bench.get("all_match", False):
        states.append(
            _state(
                "S6",
                "public_bench_executed",
                "FAIL",
                ["a mutation's observed state != known_truth — contradictory evidence"],
                blocker=True,
                halt="HALT_INSUFFICIENT_EVIDENCE",
            )
        )
    elif len(bench.get("repos", [])) < 2:
        states.append(
            _state(
                "S6",
                "public_bench_executed",
                "FAIL",
                [f"only {len(bench.get('repos', []))} repo executed (need >=2)"],
                blocker=True,
                halt="HALT_INSUFFICIENT_EVIDENCE",
            )
        )
    else:
        states.append(
            _state(
                "S6",
                "public_bench_executed",
                "PASS",
                [f"executed {sorted(bench['repos'])}; deterministic x2; all known-truth matched"],
            )
        )

    # S7 — benchmark docs honesty-guarded (no forbidden phrases, required framing present).
    # The doc legitimately ENUMERATES the forbidden terms in its "Allowed vs forbidden
    # wording" glossary; scan only the prose ABOVE that glossary for assertive overclaims.
    doc = facts.get("bench_doc_text", "")
    scan = doc.split("## Allowed vs forbidden")[0]
    overs = _overclaims(scan)
    missing_framing = [p for p in _REQUIRED_FRAMING if p not in doc]
    s7_ok = not overs and not missing_framing
    states.append(
        _state(
            "S7",
            "bench_doc_honest",
            "PASS" if s7_ok else "FAIL",
            [f"forbidden={overs}", f"missing_required_framing={missing_framing}"],
            blocker=True,
            halt=None if s7_ok else "HALT_UNSAFE",
        )
    )

    # S8 — security hardening: no pull_request_target, ci permissions, log-injection
    # test, dispatch-only microbench.
    prt = sorted(n for n, c in wf.items() if "pull_request_target" in c)
    ci = wf.get("ci.yml", "")
    ci_perms = "permissions:" in ci
    mb = wf.get("public-microbench.yml", "")
    mb_dispatch_only = ("workflow_dispatch" in mb) and ("pull_request_target" not in mb)
    log_inj = bool(facts.get("security", {}).get("log_injection_test"))
    s8_ev = [
        f"pull_request_target_in={prt}",
        f"ci_permissions={ci_perms}",
        f"microbench_dispatch_only={mb_dispatch_only}",
        f"log_injection_test={log_inj}",
    ]
    s8_ok = (not prt) and ci_perms and mb_dispatch_only and log_inj
    states.append(
        _state(
            "S8",
            "security_hardening",
            "PASS" if s8_ok else "FAIL",
            s8_ev,
            blocker=True,
            halt=None if s8_ok else "HALT_UNSAFE",
        )
    )

    # S9 — release artifacts + provenance/attestation workflow exists.
    prov = bool(facts.get("provenance_workflow"))
    states.append(
        _state(
            "S9",
            "release_artifacts_and_provenance",
            "PASS" if prov else "FAIL",
            [f"provenance/attestation workflow present={prov}"],
            halt="HALT_PUBLISH_NOT_CONFIGURED" if (require_publish and not prov) else None,
            blocker=require_publish and not prov,
        )
    )

    # S10 — PyPI Trusted Publisher TestPyPI dry-run workflow exists (real publish stays deferred).
    tp = bool(facts.get("testpypi_workflow"))
    states.append(
        _state(
            "S10",
            "pypi_trusted_publisher_dry_run",
            "PASS" if tp else "FAIL",
            [f"TestPyPI Trusted-Publishing dry-run workflow present={tp}"],
            halt="HALT_PUBLISH_NOT_CONFIGURED" if (require_publish and not tp) else None,
            blocker=require_publish and not tp,
        )
    )

    decision = _decide(states, facts, evidence)
    return {
        "schema_version": SCHEMA_VERSION,
        "target": target,
        "source_version": facts.get("pyproject_version", "unknown"),
        "evaluated_commit": facts.get("head_commit", "unknown"),
        "strict": strict,
        "require_publish": require_publish,
        "decision": decision,
        "states": states,
        "release_claim": _release_claim(decision, evidence),
    }


def _decide(states: list[dict], facts: dict, evidence: dict) -> str:
    by_id = {s["id"]: s for s in states}
    # 1) any HALT from a FAILing state wins, by fixed priority
    halts = {s.get("halt") for s in states if s["status"] == "FAIL" and s.get("halt")}
    for h in _HALTS:
        if h in halts:
            return h
    # 2) no halts: distinguish PROMOTE / CUT_RC2 / STAY_RC
    week2_ok = by_id["S2"]["status"] == "PASS"
    claims_ok = by_id["S5"]["status"] == "PASS"
    bench_ok = by_id["S6"]["status"] == "PASS"
    if not (week2_ok and claims_ok and bench_ok):
        return "STAY_RC"  # no executed machine-derived evidence yet
    provenance_ok = by_id["S9"]["status"] == "PASS" and by_id["S10"]["status"] == "PASS"
    if facts.get("features_after_rc1") or not provenance_ok:
        return "CUT_RC2_READY"  # new behavior after rc1 and/or publish path needs a live run
    return "PROMOTE_1_0_READY"


def _release_claim(decision: str, evidence: dict) -> dict:
    executed = bool((evidence.get("benchmark") or {}).get("executed"))
    if executed:
        allowed = (
            "dorian includes a public micro-benchmark harness with machine-derived structural "
            "claims, reproduced on named public repositories pinned at frozen SHAs. Results report "
            "trigger and truth layers separately and are reproducible evidence on those frozen "
            "inputs, not a general real-world validation claim."
        )
    else:
        allowed = (
            "dorian includes the public micro-benchmark harness and candidate frozen SHAs; no "
            "public benchmark result is published yet."
        )
    return {
        "allowed": allowed,
        "forbidden": list(_FORBIDDEN_PHRASES) + list(_FORBIDDEN_WORDS),
    }


def render_json(report: dict) -> str:
    return json.dumps(report, sort_keys=True, indent=2) + "\n"


def render_decision_md(report: dict) -> str:
    """Deterministic human-readable decision doc (docs/RELEASE_DECISION_1_0.md)."""
    d = report["decision"]
    lines = [
        "# Release decision — dorian " + report["target"],
        "",
        f"**Decision: `{d}`**  (exit {exit_code(d)})",
        "",
        f"- evaluated commit: `{report['evaluated_commit']}`",
        f"- source version: `{report['source_version']}`",
        f"- strict: {report['strict']}; require_publish: {report['require_publish']}",
        "",
        "Generated by `bench/release_state.py` — a deterministic state machine. It does "
        "not run tests, hit the network, call a model, or ask a question; see "
        "[RELEASE_GATE_1_0.md](RELEASE_GATE_1_0.md).",
        "",
        "| state | name | status |",
        "|---|---|---|",
    ]
    for s in report["states"]:
        mark = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP"}[s["status"]]
        lines.append(f"| {s['id']} | {s['name']} | {mark}{' (blocker)' if s['blocker'] else ''} |")
    lines += ["", "## Evidence", ""]
    for s in report["states"]:
        lines.append(f"- **{s['id']} {s['name']}** — {s['status']}")
        for ev in s["evidence"]:
            lines.append(f"  - {ev}")
    lines += [
        "",
        "## Allowed release claim",
        "",
        "> " + report["release_claim"]["allowed"],
        "",
        "Forbidden wording (refused mechanically): "
        + ", ".join(f"`{w}`" for w in report["release_claim"]["forbidden"]),
        "",
    ]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------ real-repo IO (impure)


def _git(repo: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip()


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _grep_version(text: str, pat: str) -> str | None:
    m = re.search(pat, text)
    return m.group(1) if m else None


def _strip_comments(text: str) -> str:
    """Drop YAML/shell `#` comments so an explanatory `# ... pull_request_target ...`
    line is not mistaken for an actual trigger. (Triggers never live in quoted strings.)"""
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        out.append(line.split(" #", 1)[0])
    return "\n".join(out)


def _parse_porcelain(stdout: str) -> list[str]:
    """Parse `git status --porcelain` WITHOUT a global strip (which would eat the
    leading space of a ' M path' first line and shift the field offsets). Each line is
    `XY<space>path`; git quotes paths containing spaces, so unquote."""
    paths = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        paths.append(path)
    return paths


# Expected dirty/untracked path prefixes for the Week-1/2/3 release branch. Anything
# outside this allowlist (and not a top-level .md doc) makes S0 fail closed.
_EXPECTED_DIRTY = (
    ".gitignore",
    "spec/checkers.md",
    "src/dorian/",
    "tests/",
    "bench/",
    "docs/",
    ".github/workflows/",
)


def _is_expected_dirty(path: str) -> bool:
    # a code/config path must match an allowlisted prefix; a top-level *.md doc (README,
    # AGENTS.md, CLAUDE.md, a research report) cannot affect the build/tests, so it is fine
    if any(path.startswith(pre) for pre in _EXPECTED_DIRTY):
        return True
    return "/" not in path and path.endswith(".md")


def gather_facts(repo: Path) -> dict:
    """Read-only collection of machine-verifiable facts from the repo. No network."""
    repo = Path(repo)
    pyproject = _read(repo / "pyproject.toml")
    init = _read(repo / "src" / "dorian" / "__init__.py")
    lock = _read(repo / "uv.lock")

    # version files
    pyproject_version = _grep_version(pyproject, r'(?m)^version\s*=\s*"([^"]+)"')
    init_version = _grep_version(init, r'__version__\s*=\s*"([^"]+)"')
    m = re.search(r'name = "dorian-vwp"\s*\nversion = "([^"]+)"', lock)
    lock_version = m.group(1) if m else None

    # tag + commit relationship
    _, tags = _git(repo, "tag", "--list", RC_TAG)
    rc_tag_exists = RC_TAG in tags.split()
    _, head = _git(repo, "rev-parse", "HEAD")
    rc_tag_commit = None
    if rc_tag_exists:
        _, rc_tag_commit = _git(repo, "rev-list", "-n1", RC_TAG)
    rc_anc, _ = (
        _git(repo, "merge-base", "--is-ancestor", RC_TAG, "HEAD") if rc_tag_exists else (1, "")
    )
    features_after_rc1 = bool(rc_tag_exists and rc_anc == 0 and head != rc_tag_commit)

    # dirty-tree allowlist (gitignored paths are already excluded by --porcelain). Read
    # the raw stdout (no global strip) so the first ' M path' line parses correctly.
    porc = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True
    ).stdout
    dirty = _parse_porcelain(porc)
    unexpected = [p for p in dirty if not _is_expected_dirty(p)]

    # week-2 capability presence
    c3 = _read(repo / "src" / "dorian" / "checkers" / "c3_ref.py")
    spec = _read(repo / "spec" / "checkers.md")
    store = _read(repo / "src" / "dorian" / "store.py")
    fold = _read(repo / "src" / "dorian" / "fold.py")
    week2 = {
        "config_value_impl": "config-value" in c3 and "_check_config_value" in c3,
        "config_value_doc": "config-value:" in spec,
        "atomicity_impl": "apply_claim_state_atomic" in store
        and "apply_claim_state_atomic" in fold,
    }

    # harness presence + invariants
    harness_src = _read(repo / "bench" / "public_repos.py")
    harness = {
        "exists": bool(harness_src),
        "verify_cache": "_verify_cache" in harness_src,
        "error_distinct_broken": "_EXPECTED_STATE" in harness_src and "ERRORED" in harness_src,
    }

    # proof-backed, benchmark-ready machine-derived claims
    machine_claims = []
    repos_dir = repo / "bench" / "public" / "repos"
    if repos_dir.is_dir():
        for sub in sorted(repos_dir.iterdir()):
            cj = sub / "claims.json"
            if not cj.is_file():
                continue
            try:
                doc = json.loads(_read(cj))
            except json.JSONDecodeError:
                continue
            if (
                doc.get("status") == "benchmark-ready"
                and all(isinstance(c.get("proof"), dict) for c in doc.get("claims", []))
                and doc.get("claims")
            ):
                machine_claims.append(sub.name)

    # workflows — store comment-stripped content so an explanatory `# NO pull_request_target`
    # comment can't be mistaken for an actual trigger in the S8 scan.
    wf_dir = repo / ".github" / "workflows"
    raw_wf = {p.name: _read(p) for p in sorted(wf_dir.glob("*.yml"))} if wf_dir.is_dir() else {}
    workflows = {name: _strip_comments(c) for name, c in raw_wf.items()}
    provenance_workflow = any(
        "attest-build-provenance" in c or "attestations: write" in c for c in workflows.values()
    )
    testpypi_workflow = any(
        "test.pypi.org" in c or "testpypi" in c.lower() for c in workflows.values()
    )

    # security: a test asserting the Action fences/ignores injected log commands
    log_injection_test = False
    tests_dir = repo / "tests"
    if tests_dir.is_dir():
        for tp in tests_dir.glob("test_*.py"):
            t = _read(tp)
            if "stop-commands" in t or "log_injection" in t or "log-injection" in t:
                log_injection_test = True
                break

    return {
        "pyproject_version": pyproject_version,
        "init_version": init_version,
        "lock_version": lock_version,
        "rc_tag": RC_TAG,
        "rc_tag_exists": rc_tag_exists,
        "head_commit": head,
        "rc_tag_commit": rc_tag_commit,
        "features_after_rc1": features_after_rc1,
        "unexpected_dirty": unexpected,
        "week2": week2,
        "harness": harness,
        "machine_claims": machine_claims,
        "bench_doc_text": _read(repo / "docs" / "BENCHMARK_PUBLIC_REAL_REPOS.md"),
        "workflows": workflows,
        "security": {"log_injection_test": log_injection_test},
        "provenance_workflow": provenance_workflow,
        "testpypi_workflow": testpypi_workflow,
    }


def load_evidence(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


# --------------------------------------------------------------------------- CLI


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="release_state", description=__doc__)
    ap.add_argument("--target", default="1.0.0", help="release target version")
    ap.add_argument("--repo", default=".", help="repository root")
    ap.add_argument(
        "--evidence",
        default="bench/public/results/release_evidence.json",
        help="recorded gate-outcome evidence json",
    )
    ap.add_argument(
        "--out",
        default="bench/public/results/release_state.json",
        help="where to write the state json",
    )
    ap.add_argument(
        "--decision-out",
        default="docs/RELEASE_DECISION_1_0.md",
        help="where to write the human-readable decision doc",
    )
    ap.add_argument("--json", action="store_true", help="print the state json to stdout")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="missing gate evidence is HALT_INSUFFICIENT_EVIDENCE, not SKIP",
    )
    ap.add_argument(
        "--require-publish",
        action="store_true",
        help="treat missing provenance/TestPyPI workflows as HALT_PUBLISH_NOT_CONFIGURED",
    )
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    facts = gather_facts(repo)
    evidence = load_evidence(
        repo / args.evidence if not Path(args.evidence).is_absolute() else Path(args.evidence)
    )
    report = evaluate(
        facts,
        evidence,
        target=args.target,
        strict=args.strict,
        require_publish=args.require_publish,
    )

    out_path = repo / args.out if not Path(args.out).is_absolute() else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_json(report), encoding="utf-8")

    dec_path = (
        repo / args.decision_out
        if not Path(args.decision_out).is_absolute()
        else Path(args.decision_out)
    )
    dec_path.parent.mkdir(parents=True, exist_ok=True)
    dec_path.write_text(render_decision_md(report), encoding="utf-8")

    if args.json:
        sys.stdout.write(render_json(report))
    else:
        sys.stdout.write(f"decision: {report['decision']}\n")
        for s in report["states"]:
            sys.stdout.write(f"  [{s['status']:4}] {s['id']} {s['name']}\n")
        sys.stdout.write(f"state json -> {out_path}\n")
    return exit_code(report["decision"])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
