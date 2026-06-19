"""C4 import-aware binding benchmark — known-truth, trigger-vs-truth honest.

Measures the C4 import-aware dependency binding fix. A C4 ``pytest:`` checker proves
behavior WHEN IT RUNS, but the pre-fix watch is only the nodeid's test file, so an edit
to the implementation the test imports was never SELECTED for re-check — the claim stayed
trusted on stale confidence. This suite scores, on synthetic scenarios with labels frozen
BEFORE measurement, two layers kept deliberately separate:

SELECTION (trigger) layer — did a watcher SELECT the claim when the imported impl changed?
  test_file_watcher    the pre-fix C4 watch: the nodeid's test file ONLY (the ablation).
  import_aware_watcher  the fix: the test file UNION the repo-local files it imports.

VERDICT (truth) layer — when the import-aware watcher selects and the C4 test RUNS, does
the verdict track the test? A broken implementation FAILs the test (BROKEN); a behavior-
preserving edit re-runs the test and PASSes (not BROKEN). A file change is a re-check
TRIGGER, never proof a claim is false — so the import-aware watcher's extra selections do
NOT become extra alarms.

Scope / limits (stated up front)
--------------------------------
- Invented synthetic fixtures authored and scored by the same tool. These numbers are a
  reproducible demonstration of the MECHANISM on this suite, not evidence about any real
  repository, and binding is NOT behavior proof — only the C4 test decides truth.
- Determinism: the summary is byte-identical across runs — no sha, warrant id, wall-clock
  timestamp, or host path is emitted; provenance is a content digest of the scenarios plus
  a deterministic run id.

Usage
-----
    python -m bench.c4_import_binding [--quick] [--out summary.json] [--md-out doc.md]
    (or: dorian bench c4-import-binding ... from a dorian checkout)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:  # bench/ is a repo-root package, not installed
    sys.path.insert(0, str(_REPO_ROOT))

from dorian import gitio, test_deps  # noqa: E402
from dorian.capture.manual import parse_manual  # noqa: E402
from dorian.model import CheckerSpec, Claim  # noqa: E402
from dorian.revalidate import revalidate  # noqa: E402
from dorian.seal import seal_artifact  # noqa: E402

SCHEMA = "dorian-c4-import-binding-v1"
BENCHMARK_ID = "c4_import_binding"

FORBIDDEN_WORDS = (
    "proven",
    "validated",
    "production-grade",
    "production-ready",
    "universal",
    "real-world validated",
    "guaranteed",
    "semantic proof",
    "behavior proof",  # binding is explicitly NOT behavior proof; never assert it
)

GIT_ENV = {
    "GIT_AUTHOR_NAME": "dorian-bench",
    "GIT_AUTHOR_EMAIL": "bench@dorian.local",
    "GIT_COMMITTER_NAME": "dorian-bench",
    "GIT_COMMITTER_EMAIL": "bench@dorian.local",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}

_PKG_INIT = ("src/__init__.py", "")  # makes `from src.x import ...` import under `python -m`
_AUTH_DEF = "def verify_token(t):\n    return t\n"

# Each SELECTION scenario: a synthetic repo where a C4 test imports an impl file in one
# import style. `changed` is the implementation file the test exercises (the edit a
# reviewer would make); `should_recheck=True` means a watcher SHOULD select the claim.
# Direct-import styles are the recall target (import-aware -> 1.0); the ambiguous style is
# a deliberate, honest miss (a wrong watch is a false alarm, so the conservative resolver
# skips it — scored as a miss, never credited as a win).
_SELECTION_SCENARIOS: tuple[dict, ...] = (
    {
        "name": "absolute_from",
        "style": "from src.auth import verify_token",
        "files": {_PKG_INIT[0]: _PKG_INIT[1], "src/auth.py": _AUTH_DEF},
        "test": "tests/test_x.py",
        "test_src": "import os\nfrom src.auth import verify_token\n\ndef test_x():\n    pass\n",
        "nodeid": "tests/test_x.py::test_x",
        "changed": "src/auth.py",
        "should_recheck": True,
        "kind": "direct",
    },
    {
        "name": "absolute_import",
        "style": "import src.auth",
        "files": {_PKG_INIT[0]: _PKG_INIT[1], "src/auth.py": _AUTH_DEF},
        "test": "tests/test_x.py",
        "test_src": "import src.auth\n\ndef test_x():\n    pass\n",
        "nodeid": "tests/test_x.py::test_x",
        "changed": "src/auth.py",
        "should_recheck": True,
        "kind": "direct",
    },
    {
        "name": "package_init",
        "style": "import pkg  (-> pkg/__init__.py)",
        "files": {"pkg/__init__.py": "VALUE = 1\n"},
        "test": "tests/test_x.py",
        "test_src": "import pkg\n\ndef test_x():\n    pass\n",
        "nodeid": "tests/test_x.py::test_x",
        "changed": "pkg/__init__.py",
        "should_recheck": True,
        "kind": "direct",
    },
    {
        "name": "relative",
        "style": "from .impl import f",
        "files": {"pkg/__init__.py": "", "pkg/impl.py": "def f():\n    return 1\n"},
        "test": "pkg/test_impl.py",
        "test_src": "from .impl import f\n\ndef test_x():\n    pass\n",
        "nodeid": "pkg/test_impl.py::test_x",
        "changed": "pkg/impl.py",
        "should_recheck": True,
        "kind": "direct",
    },
    {
        "name": "nested_module",
        "style": "from src.sub.deep import g",
        "files": {
            "src/__init__.py": "",
            "src/sub/__init__.py": "",
            "src/sub/deep.py": "def g():\n    return 1\n",
        },
        "test": "tests/test_x.py",
        "test_src": "from src.sub.deep import g\n\ndef test_x():\n    pass\n",
        "nodeid": "tests/test_x.py::test_x",
        "changed": "src/sub/deep.py",
        "should_recheck": True,
        "kind": "direct",
    },
    {
        "name": "ambiguous",
        "style": "import auth  (two tracked auth.py: definer unknowable)",
        "files": {"auth.py": "X = 1\n", "src/auth.py": "Y = 2\n"},
        "test": "tests/test_x.py",
        "test_src": "import auth\n\ndef test_x():\n    pass\n",
        "nodeid": "tests/test_x.py::test_x",
        "changed": "src/auth.py",
        "should_recheck": True,
        "kind": "ambiguous_skip",  # honest miss: conservative resolver leaves it unbound
    },
)

# VERDICT scenarios: the import-aware watcher selects the claim; the C4 test then RUNS and
# its result decides truth. `broken` makes the test fail (-> BROKEN); `benign` preserves
# behavior (-> not BROKEN). Same starting impl + test; only the edit differs.
_VERDICT_FILES = {
    "src/__init__.py": "",
    "src/auth.py": "def verify_token(token):\n    return token == 'good'\n",
    "tests/test_login.py": (
        "from src.auth import verify_token\n\n\n"
        "def test_login():\n"
        "    assert verify_token('good') is True\n"
        "    assert verify_token('bad') is False\n"
    ),
}
_VERDICT_NODEID = "tests/test_login.py::test_login"
_VERDICT_CASES = (
    ("broken", "def verify_token(token):\n    return token == 'nope'\n", "BROKEN"),
    ("benign", "def verify_token(token):\n    # tidy\n    return token == 'good'\n", "VERIFIED"),
)


def _git(repo: Path, *args: str) -> None:
    import os

    subprocess.run(
        ["git", *args], cwd=repo, env={**os.environ, **GIT_ENV}, check=True, capture_output=True
    )


def _build_repo(repo: Path, files: dict[str, str]) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")


def _selection_records(workspace: Path) -> list[dict]:
    records: list[dict] = []
    for sc in _SELECTION_SCENARIOS:
        repo = workspace / "sel" / sc["name"]
        files = dict(sc["files"])
        files[sc["test"]] = sc["test_src"]
        _build_repo(repo, files)
        deps = test_deps.python_import_dependencies(repo, sc["test"])
        test_file_watch = {sc["test"]}
        import_aware_watch = test_file_watch | set(deps)
        records.append(
            {
                "layer": "selection",
                "scenario": sc["name"],
                "style": sc["style"],
                "kind": sc["kind"],
                "changed": sc["changed"],
                "should_recheck": sc["should_recheck"],
                "selected_test_file_watcher": sc["changed"] in test_file_watch,
                "selected_import_aware_watcher": sc["changed"] in import_aware_watch,
                # precision guard: every resolved dep is a repo-local tracked file (never a
                # stdlib/third-party module) — content-free, paths only
                "resolved_deps": list(deps),
            }
        )
    return records


def _verdict_records(workspace: Path) -> list[dict]:
    records: list[dict] = []
    for name, mutated_impl, expected in _VERDICT_CASES:
        repo = workspace / "verdict" / name
        _build_repo(repo, dict(_VERDICT_FILES))
        claim = Claim(
            id="login-behavior",
            text="Login rejects invalid tokens.",  # names no uniquely indexed symbol
            kind="behavior",
            load_bearing=True,
            checkers=(CheckerSpec(type="C4", program=f"pytest:{_VERDICT_NODEID}"),),
        )
        # seal the way `dorian verify` does: union the import-aware watch into extra_watch +
        # read-set, so the impl file is watched and captured. Born-verifiable: the test passes.
        extra = test_deps.c4_dependency_watch_paths(repo, [claim])
        readset = parse_manual(["tests/test_login.py", *extra.get("login-behavior", ())], repo)
        seal_artifact(repo, "tests/test_login.py", readset, [claim], extra_watch=extra)
        base = gitio.head_ref(repo)
        (repo / "src/auth.py").write_text(mutated_impl)  # the only edit: implementation
        res = revalidate(repo, since=base)
        if res.broken:
            verdict = "BROKEN"
        elif res.errored:
            verdict = "ERRORED"
        elif res.passed or res.relocated:
            verdict = "VERIFIED"
        else:
            verdict = "NOT_SELECTED"
        records.append(
            {
                "layer": "verdict",
                "scenario": name,
                "selected": res.candidates >= 1,
                "verdict": verdict,
                "expected": expected,
                "match": verdict == expected,
            }
        )
    return records


def _recall(records: list[dict], watcher: str, kind: str) -> tuple[int, int]:
    rel = [r for r in records if r["layer"] == "selection" and r["kind"] == kind]
    hit = sum(1 for r in rel if r[watcher])
    return hit, len(rel)


def _summarize(records: list[dict]) -> dict:
    direct_old = _recall(records, "selected_test_file_watcher", "direct")
    direct_new = _recall(records, "selected_import_aware_watcher", "direct")
    amb_new = _recall(records, "selected_import_aware_watcher", "ambiguous_skip")
    verdicts = [r for r in records if r["layer"] == "verdict"]
    alarm_correct = sum(1 for r in verdicts if r["match"])
    false_broken = sum(
        1 for r in verdicts if r["scenario"] == "benign" and r["verdict"] == "BROKEN"
    )

    def rate(hl: tuple[int, int]) -> float:
        return round(hl[0] / hl[1], 4) if hl[1] else 0.0

    return {
        "schema": SCHEMA,
        "provenance": {"benchmark_id": BENCHMARK_ID, "run_id": _run_id(records)},
        "composition": {
            "selection_scenarios": sum(1 for r in records if r["layer"] == "selection"),
            "direct_import_scenarios": direct_new[1],
            "ambiguous_skip_scenarios": amb_new[1],
            "verdict_scenarios": len(verdicts),
        },
        "selection_layer": {
            # the headline: the pre-fix test-file-only watcher misses every implementation
            # edit (it watches only the test file); the import-aware watcher selects them all
            "test_file_watcher_recall_direct": rate(direct_old),
            "import_aware_watcher_recall_direct": rate(direct_new),
            "import_aware_selected_ambiguous": amb_new[0],  # 0 = the honest, conservative skip
        },
        "verdict_layer": {
            # selection is not alarm: the import-aware watcher's extra re-checks only become
            # BROKEN when the C4 test actually fails
            "alarm_match": f"{alarm_correct}/{len(verdicts)}",
            "false_broken_from_benign_edit": false_broken,  # MUST be 0 (survival condition)
        },
        "limits": (
            "Synthetic fixtures authored and scored by one tool: a reproducible demonstration"
            " of the mechanism on this suite, not evidence about any real repository. Binding"
            " widens the re-check TRIGGER set; the C4 test still decides truth."
        ),
    }


def _run_id(records: list[dict]) -> str:
    payload = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def run_benchmark(workspace: Path, *, quick: bool = False) -> tuple[dict, list[dict]]:
    """Run both layers in ``workspace`` and return (summary, records). Deterministic:
    no sha/timestamp/host path is emitted. ``quick`` is accepted for CLI parity (the
    suite is already small); both layers always run."""
    records = _selection_records(workspace)
    records += _verdict_records(workspace)
    return _summarize(records), records


def _render_md(summary: dict) -> str:
    s = summary["selection_layer"]
    v = summary["verdict_layer"]
    c = summary["composition"]
    return "\n".join(
        [
            "# C4 import-aware binding benchmark (current)",
            "",
            f"_schema `{summary['schema']}`, run_id `{summary['provenance']['run_id']}`_",
            "",
            "Synthetic, known-truth. Binding widens the re-check **trigger** set; the C4 test"
            " still decides truth (a watched file changing never makes a claim BROKEN by"
            " itself).",
            "",
            "## Selection (trigger) layer",
            "",
            "| watcher | recall on direct-import impl edits |",
            "| --- | ---: |",
            f"| pre-fix (test-file-only) | {s['test_file_watcher_recall_direct']} |",
            f"| import-aware (this fix) | {s['import_aware_watcher_recall_direct']} |",
            "",
            f"- direct-import scenarios: {c['direct_import_scenarios']};"
            f" ambiguous (honest skip): {c['ambiguous_skip_scenarios']}"
            f" — import-aware selected {s['import_aware_selected_ambiguous']} of them"
            " (a wrong watch is a false alarm, so ambiguity is skipped, not guessed).",
            "",
            "## Verdict (truth) layer",
            "",
            f"- alarm match (broken impl -> BROKEN, benign impl -> not BROKEN): {v['alarm_match']}",
            f"- false BROKEN from a behavior-preserving edit: {v['false_broken_from_benign_edit']}"
            " (must be 0 — file drift is a trigger, not a verdict).",
            "",
            f"_{summary['limits']}_",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dorian bench c4-import-binding", description=__doc__)
    ap.add_argument("--quick", action="store_true", help="(accepted for parity; suite is small)")
    ap.add_argument("--out", type=Path, help="write the JSON summary here")
    ap.add_argument("--md-out", type=Path, help="write a markdown report here")
    ap.add_argument("--records", type=Path, help="write per-scenario records (JSONL) here")
    args = ap.parse_args(argv)

    import tempfile

    with tempfile.TemporaryDirectory(prefix="dorian-c4ib-") as tmp:
        summary, records = run_benchmark(Path(tmp), quick=args.quick)

    blob = json.dumps(summary, indent=2, sort_keys=True)
    # overclaim guard over the HUMAN-READABLE prose (the markdown body + the limits line),
    # not the JSON structure — so a structural key like "provenance" never trips "proven".
    prose = (_render_md(summary) + " " + summary["limits"]).lower()
    for word in FORBIDDEN_WORDS:
        if word in prose:
            print(f"bench c4-import-binding: overclaim guard tripped on {word!r}", file=sys.stderr)
            return 2
    if args.out:
        args.out.write_text(blob + "\n")
    if args.md_out:
        args.md_out.write_text(_render_md(summary))
    if args.records:
        args.records.write_text("\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n")
    print(blob)
    return 0


if __name__ == "__main__":
    sys.exit(main())
