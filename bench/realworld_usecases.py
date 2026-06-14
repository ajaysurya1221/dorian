"""Real-world public-case reproductions — hermetic, offline, honestly labelled.

Each reproduction distills a PUBLIC, still-open-as-of-2026-06-14 problem into a
tiny, invented, public-safe fixture that exercises dorian's lifecycle promise. No
proprietary content is copied: the public issue is the design TEMPLATE, the fixture
is synthetic. The committed default path is fully offline.

The honest label for each case is NOT asserted by the author — it is DERIVED from
dorian's ACTUAL revalidate behavior and cross-checked against the case's frozen
expectation:

  solved      : the reproduction is hermetic, the stale fact is mechanically
                checkable, and dorian's checker FOLDS the claim BROKEN.
  partial     : dorian RE-CHECKS the claim (the trigger fires) but its checker
                cannot prove the semantic fact, so the claim stays VERIFIED — the
                trigger-vs-truth ceiling, on a real case class.
  not_solved  : dorian misses the change, or it cannot be made deterministic /
                hermetic. Documented from public sources; not reproduced here.
  cannot_test : needs private content, unsafe exploitation, network as the default
                path, or nonmechanical judgment.

A case whose ACTUAL behavior contradicts its declared label raises — a mislabel
cannot pass silently.

Usage:
    python -m bench.realworld_usecases [--out summary.json] [--records recs.jsonl]
        [--md-out doc.md]
    (or: dorian bench realworld-usecases from a dorian checkout)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bench.binding_lifecycle import Artifact, BClaim, _git, _seal_bound, _write  # noqa: E402
from dorian.model import CheckerSpec, Claim  # noqa: E402
from dorian.revalidate import revalidate  # noqa: E402

SCHEMA = "dorian-realworld-usecases-v1"
BENCHMARK_ID = "realworld_usecases"
SOURCE_DATE = "2026-06-14"


def _c(cid: str, text: str, prog: str, ctype: str = "C3") -> BClaim:
    return BClaim(
        Claim(
            id=cid,
            text=text,
            kind="fact",
            load_bearing=True,
            checkers=(CheckerSpec(type=ctype, program=prog),),
        ),
        binding_type="realworld",
        style=ctype,
    )


@dataclass(frozen=True)
class UseCase:
    case_id: str
    source_urls: tuple[str, ...]
    source_project: str
    source_status: str  # status as of SOURCE_DATE
    problem_class: str
    reproduction_type: str  # public_case_reproduction | qualitative_public_case
    claim_shape: str
    checker_shape: str
    expected_behavior: str
    solved_status: str  # solved | partial | not_solved | cannot_test
    why: str
    limitations: str
    # reproduction (omitted for qualitative cases)
    files: dict[str, str] = field(default_factory=dict)
    claims: tuple[BClaim, ...] = ()
    drift: object = None  # callable(repo) -> None
    fact_caught: frozenset[str] = frozenset()  # claim ids dorian SHOULD fold BROKEN
    fact_missed: frozenset[str] = frozenset()  # drifted claims dorian CANNOT catch


# --- drift builders -------------------------------------------------------------


def _replace(rel: str, old: str, new: str):
    def apply(repo: Path, rel=rel, old=old, new=new) -> None:
        p = repo / rel
        body = p.read_text(encoding="utf-8")
        if old not in body:
            raise RuntimeError(f"drift target {old!r} not in {rel}")
        p.write_text(body.replace(old, new), encoding="utf-8")

    return apply


def _chain(*fns):
    def apply(repo: Path, fns=fns) -> None:
        for fn in fns:
            fn(repo)

    return apply


# --- the cases ------------------------------------------------------------------

_LOADER = 'CONFIG_FILE = "config.yaml"\n\n\ndef load():\n    return open(CONFIG_FILE)\n'
_MIGRATE = 'LEGACY = "config.yaml"  # migrate the old file on first run\n'
_ARRAY = "def find_first(xs):\n    return xs[0] if xs else None  # safe: None on empty\n"


def _cases() -> list[UseCase]:
    return [
        # R1 — solved: a renamed config filename leaves the docs stale (string fact).
        UseCase(
            case_id="config_rename_doc_drift",
            source_urls=("https://github.com/Proxyfan/Proxyfan/issues/978",),
            source_project="Proxyfan/Proxyfan",
            source_status="open",
            problem_class=(
                "file/config rename — docs reference the legacy filename after the code renamed it"
            ),
            reproduction_type="public_case_reproduction",
            claim_shape="The config loader reads a file named `config.yaml`.",
            checker_shape="C3 string: the loader source literally references config.yaml",
            expected_behavior=(
                "rename in the loader -> the documented filename string is gone -> BROKEN"
            ),
            solved_status="solved",
            why=(
                "the documented fact IS a string the checker exercises against the source "
                "of truth (the loader), so a rename folds it BROKEN; a migration shim that "
                "intentionally keeps the legacy name is NOT in the checker's bound file, so "
                "it does not over-fire (precision)."
            ),
            limitations=(
                "dorian proves the documented STRING is stale, not that a user workflow "
                "breaks; the claim must be scoped to the canonical source file, which a "
                "human/agent authors."
            ),
            files={
                "src/loader.py": _LOADER,
                # an intentional legacy reference in a shim — must NOT cause a false BROKEN
                "src/migrate.py": _MIGRATE,
            },
            claims=(
                _c(
                    "cfg-name",
                    "The config loader reads `config.yaml`.",
                    "string:src/loader.py::config.yaml",
                ),
            ),
            drift=_replace("src/loader.py", "config.yaml", "config.kv"),
            fact_caught=frozenset({"cfg-name"}),
        ),
        # R2 — solved (security): TLS verification silently disabled (config-value drift).
        UseCase(
            case_id="tls_insecure_skip_verify",
            source_urls=("https://github.com/grafana/grafana/issues/110811",),
            source_project="grafana/grafana",
            source_status="open",
            problem_class=(
                "security config drift — a TLS verification flag flipped to an insecure value"
            ),
            reproduction_type="public_case_reproduction",
            claim_shape=(
                "The HTTP client keeps TLS verification ON (InsecureSkipVerify is False)."
            ),
            checker_shape="C3 regex: InsecureSkipVerify is anchored to False",
            expected_behavior=(
                "flip InsecureSkipVerify to True -> the anchored regex fails -> BROKEN"
            ),
            solved_status="solved",
            why=(
                "a security-relevant config value is a deterministic C3 regex fact (key AND "
                "value anchored); flipping it to the insecure value folds the claim BROKEN at "
                "the next commit."
            ),
            limitations=(
                "dorian proves the source sets InsecureSkipVerify = False, not that TLS is "
                "actually verified at runtime; bind both key and value or a bare flip passes."
            ),
            files={"src/httpclient.py": "TLS = {\n    'InsecureSkipVerify': False,\n}\n"},
            claims=(
                _c(
                    "tls-verify",
                    "TLS verification stays enabled (InsecureSkipVerify is False).",
                    r"regex:src/httpclient.py::InsecureSkipVerify'\s*:\s*False",
                ),
            ),
            drift=_replace(
                "src/httpclient.py", "'InsecureSkipVerify': False", "'InsecureSkipVerify': True"
            ),
            fact_caught=frozenset({"tls-verify"}),
        ),
        # R3 — partial (the ceiling): a rename is caught; a silent behavior change is missed.
        UseCase(
            case_id="api_rename_caught_typedrift_missed",
            source_urls=("https://github.com/Effect-TS/effect-smol/issues/1378",),
            source_project="Effect-TS/effect-smol (Effect v4)",
            source_status="open",
            problem_class=(
                "major-version API churn — a rename (caught) PLUS a same-name return-type "
                "change (missed)"
            ),
            reproduction_type="public_case_reproduction",
            claim_shape=(
                "(a) the example uses exported `reverse`; (b) `find_first` is the safe accessor."
            ),
            checker_shape="C3 symbol: existence checks on both symbols",
            expected_behavior=(
                "one drift commit: rename reverse->flip (existence BROKEN) AND gut find_first's "
                "body keeping the name (existence still passes -> NOT broken)"
            ),
            solved_status="partial",
            why=(
                "dorian catches the pure RENAME (the example's symbol no longer exists -> "
                "BROKEN) but a symbol that keeps its name while changing its return "
                "type/behavior re-checks and PASSES — the documented trigger-vs-truth ceiling, "
                "on a real migration class."
            ),
            limitations=(
                "catching the silent type change needs a checker that EXERCISES behavior (a C4 "
                "test or a type-level check), which the doc author did not bind; existence is "
                "not behavior. Also: the real project is TypeScript, so only C3 "
                "path/symbol/string checks transfer."
            ),
            files={
                "lib/order.py": "def reverse(xs):\n    return list(reversed(xs))\n",
                "lib/array.py": _ARRAY,
            },
            claims=(
                _c(
                    "ex-reverse",
                    "The example imports `reverse` from the order module.",
                    "symbol:lib/order.py::reverse",
                ),
                _c(
                    "find-first",
                    "`find_first` is the safe optional accessor.",
                    "symbol:lib/array.py::find_first",
                ),
            ),
            drift=_chain(
                _replace("lib/order.py", "def reverse", "def flip"),  # rename -> BROKEN
                # same name, new behavior (now raises on empty): existence passes -> MISSED
                _replace(
                    "lib/array.py",
                    "return xs[0] if xs else None  # safe: None on empty",
                    "return xs[0]  # raises on empty",
                ),
            ),
            fact_caught=frozenset({"ex-reverse"}),
            fact_missed=frozenset({"find-first"}),
        ),
        # --- documented boundary cases (not reproduced here) ----------------------
        UseCase(
            case_id="readme_path_already_fixed_external_file",
            source_urls=("https://github.com/AndrejOrsula/pymoveit2/issues/110",),
            source_project="AndrejOrsula/pymoveit2",
            source_status="open",
            problem_class=(
                "README launch-file rename — but already merged-fixed, and the file is in a "
                "sibling package"
            ),
            reproduction_type="qualitative_public_case",
            claim_shape="(README command points at a launch file)",
            checker_shape="(C3 path) — but the path is outside the repo",
            expected_behavior="n/a — not reproduced",
            solved_status="not_solved",
            why=(
                "the doc half was already fixed upstream (README updated 2026-02); the "
                "still-open part is a runtime joint-config bug dorian cannot warrant, and the "
                "referenced launch file lives in an external package, so dorian has no local "
                "evidence file to watch (local-first boundary)."
            ),
            limitations=(
                "cross-package paths and runtime behavior are outside dorian's in-repo "
                "deterministic checks."
            ),
        ),
        UseCase(
            case_id="zero_assertion_test_counts_as_pass",
            source_urls=(
                "https://github.com/rails/rails/issues/26546",
                "https://github.com/jestjs/jest/issues/2209",
            ),
            source_project="rails/minitest, jest, phpunit (cross-ecosystem class)",
            source_status="unresolved",
            problem_class=(
                'a test body with no executed assertions reports as a PASS — "tests cover X" '
                "silently false"
            ),
            reproduction_type="qualitative_public_case",
            claim_shape='"feature X is covered by a test"',
            checker_shape="C4 pytest: the test is collected and exits 0",
            expected_behavior=(
                "n/a — dorian's C4 runs the test and sees a PASS; it cannot tell a gutted, "
                "assertion-free test from a real one"
            ),
            solved_status="not_solved",
            why=(
                "this is the test-level gutted-body ceiling: a zero-assertion test exits 0, so "
                "dorian's C4 checker (which trusts the runner's verdict) reports VERIFIED. "
                "Proving the test actually exercises the behavior is exactly what the runner "
                "itself does not enforce."
            ),
            limitations=(
                "needs assertion-count / mutation-testing semantics dorian deliberately does "
                "not implement (no model, no behavior synthesis); deterministically "
                "reproducible but always a miss."
            ),
        ),
    ]


# --- run ------------------------------------------------------------------------


def _run_reproduction(case: UseCase, workspace: Path) -> dict:
    repo = workspace / case.case_id
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    for rel, content in case.files.items():
        _write(repo, rel, content)
    art = Artifact(uri="docs/claims.md", claims=case.claims)
    _write(repo, art.uri, "# claims\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "t0")
    _seal_bound(repo, art)  # born verifiable: refuses to seal if a claim is already false
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seal")
    t0 = _git(repo, "rev-parse", "HEAD")

    case.drift(repo)  # type: ignore[operator]
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "drift")
    res = revalidate(repo, since=t0)

    broken = {cid for _, cid, _ in res.broken}
    passed = {cid for _, cid, _ in res.passed}
    relocated = {cid for _, cid, _ in res.relocated}  # VERIFIED via relocation
    verified = passed | relocated  # both are still-true outcomes, not breaks
    candidates = {
        cid for grp in (res.passed, res.broken, res.relocated, res.errored) for _, cid, _ in grp
    }
    shutil.rmtree(repo)

    # DERIVE the outcome from actual behavior, then cross-check the declared label.
    caught_ok = case.fact_caught <= broken
    missed_ok = case.fact_missed <= verified  # drifted, yet re-checked and still VERIFIED
    if case.solved_status == "solved":
        derived_ok = caught_ok and not case.fact_missed
    elif case.solved_status == "partial":
        derived_ok = caught_ok and bool(case.fact_missed) and missed_ok
    else:
        derived_ok = False
    return {
        "broken": sorted(broken),
        "passed": sorted(passed),
        "relocated": sorted(relocated),
        "candidates_rechecked": sorted(candidates),
        "label_matches_actual": derived_ok,
    }


def run_benchmark(workspace: Path) -> tuple[dict, list[dict]]:
    workspace.mkdir(parents=True, exist_ok=True)
    cases = _cases()
    records: list[dict] = []
    for case in cases:
        actual = None
        if case.reproduction_type == "public_case_reproduction":
            actual = _run_reproduction(case, workspace)
            if not actual["label_matches_actual"]:
                raise RuntimeError(
                    f"case {case.case_id!r}: actual behavior {actual} contradicts declared "
                    f"solved_status={case.solved_status!r}"
                )
        records.append(
            {
                "case_id": case.case_id,
                "source_urls": list(case.source_urls),
                "source_project": case.source_project,
                "source_status_as_of_2026_06_14": case.source_status,
                "problem_class": case.problem_class,
                "reproduction_type": case.reproduction_type,
                "dorian_claim_shape": case.claim_shape,
                "dorian_checker_shape": case.checker_shape,
                "expected_behavior": case.expected_behavior,
                "actual_behavior": actual,
                "solved_status": case.solved_status,
                "why": case.why,
                "limitations": case.limitations,
                "no_private_content": True,
                "hermetic": case.reproduction_type == "public_case_reproduction",
            }
        )
    records.sort(key=lambda r: r["case_id"])
    return _summary(records), records


def _summary(records: list[dict]) -> dict:
    counts = {
        k: sum(1 for r in records if r["solved_status"] == k)
        for k in ("solved", "partial", "not_solved", "cannot_test")
    }
    reproduced = sum(1 for r in records if r["reproduction_type"] == "public_case_reproduction")
    digest = hashlib.sha256(
        "|".join(r["case_id"] + r["solved_status"] for r in records).encode()
    ).hexdigest()[:16]
    return {
        "schema": SCHEMA,
        "benchmark_name": BENCHMARK_ID,
        "run_mode": "offline",
        "source_date": SOURCE_DATE,
        "provenance": {"dorian_version": _dorian_version(), "run_id": digest},
        "candidate_count": len(records),
        "reproduced_case_count": reproduced,
        "solved_count": counts["solved"],
        "partial_count": counts["partial"],
        "not_solved_count": counts["not_solved"],
        "cannot_test_count": counts["cannot_test"],
        "cases": [
            {k: r[k] for k in ("case_id", "source_project", "solved_status", "reproduction_type")}
            for r in records
        ],
        "limitations": (
            "public-case reproductions are not a blanket real-world result; each is scoped to "
            "its synthetic reproduction of a public problem class, and the trigger-vs-truth "
            "ceiling stands — a checker must EXERCISE a fact for a BROKEN to mean semantic failure."
        ),
    }


def _dorian_version() -> str:
    try:
        from dorian import __version__

        return __version__
    except Exception:  # pragma: no cover
        return "unknown"


# --- render ---------------------------------------------------------------------


def render_markdown(summary: dict, records: list[dict]) -> str:
    lines = [
        "# dorian real-world public-case reproductions",
        "",
        "> Hermetic, offline reproductions of PUBLIC problem classes (sources cited, status as of",
        f"> {summary['source_date']}). Each public issue is the design template; the fixture is",
        "> invented and public-safe. A result is scoped to its reproduction of a public problem",
        "> class — **not** a blanket real-world result. The trigger-vs-truth ceiling stands: a",
        "> checker must EXERCISE a fact for a BROKEN to mean semantic failure.",
        "",
        f"- candidates: {summary['candidate_count']} · reproduced (hermetic): "
        f"{summary['reproduced_case_count']}",
        f"- solved: {summary['solved_count']} · partial: {summary['partial_count']} · "
        f"not_solved: {summary['not_solved_count']} · cannot_test: {summary['cannot_test_count']}",
        f"- dorian `{summary['provenance']['dorian_version']}` · "
        f"run_id `{summary['provenance']['run_id']}`",
        "",
        "| case | source | status | reproduction | outcome |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in records:
        src = r["source_urls"][0] if r["source_urls"] else r["source_project"]
        lines.append(
            f"| {r['case_id']} | [{r['source_project']}]({src}) | "
            f"{r['source_status_as_of_2026_06_14']} | {r['reproduction_type']} | "
            f"**{r['solved_status']}** |"
        )
    lines += ["", "## Case detail", ""]
    for r in records:
        lines += [
            f"### {r['case_id']} — {r['solved_status']}",
            "",
            f"- **source**: {r['source_project']} — " + ", ".join(r["source_urls"]),
            f"- **problem class**: {r['problem_class']}",
            f"- **claim**: {r['dorian_claim_shape']}",
            f"- **checker**: {r['dorian_checker_shape']}",
            f"- **expected**: {r['expected_behavior']}",
        ]
        if r["actual_behavior"]:
            a = r["actual_behavior"]
            lines.append(
                f"- **actual**: BROKEN={a['broken']} · still-VERIFIED={a['passed']} · "
                f"re-checked={a['candidates_rechecked']}"
            )
        lines += [
            f"- **why {r['solved_status']}**: {r['why']}",
            f"- **limitations**: {r['limitations']}",
            f"- hermetic: {r['hermetic']} · no private content: {r['no_private_content']}",
            "",
        ]
    lines += [
        "## Reproduce",
        "",
        "```bash",
        "dorian bench realworld-usecases",
        "```",
        "",
        f"_{summary['limitations']}_",
        "",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.realworld_usecases", description=__doc__)
    ap.add_argument("--out", default=f"bench/results/{BENCHMARK_ID}_summary.json")
    ap.add_argument("--records", default=f"bench/results/{BENCHMARK_ID}_records.jsonl")
    ap.add_argument("--md-out", default="docs/REALWORLD_USECASES.md")
    ap.add_argument("--workspace", default="")
    args = ap.parse_args(argv)

    ws = Path(args.workspace) if args.workspace else Path(tempfile.mkdtemp(prefix="dorian-rwuc-"))
    try:
        summary, records = run_benchmark(ws)
    finally:
        if not args.workspace and ws.exists():
            shutil.rmtree(ws, ignore_errors=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    recs = Path(args.records)
    recs.parent.mkdir(parents=True, exist_ok=True)
    with recs.open("w", encoding="utf-8") as f:
        for row in records:
            f.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    if args.md_out:
        md_out = Path(args.md_out)
        md_out.parent.mkdir(parents=True, exist_ok=True)
        md_out.write_text(render_markdown(summary, records), encoding="utf-8")

    print(
        f"realworld-usecases: {summary['candidate_count']} cases · "
        f"solved {summary['solved_count']} · partial {summary['partial_count']} · "
        f"not_solved {summary['not_solved_count']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
