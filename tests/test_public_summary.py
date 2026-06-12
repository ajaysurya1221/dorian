"""Public-safe summary generator tests (bench/public_summary.py) on synthetic fixtures.

Every text field in the fixtures (artifact paths, claim texts, commit shas and
subjects, changed files, rationales-by-proxy stray fields, the private repo
name 'internal-x') carries a SECRET marker: the structural privacy rule says
none of them may ever reach the public md/json outputs. Never reads
bench/real/ — all inputs are written into tmp_path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # bench/ is a repo-root package, not installed
    sys.path.insert(0, str(REPO_ROOT))

from bench import public_summary  # noqa: E402

from dorian import cli  # noqa: E402

SECRET = "SECRET-MARKER"
PRIV = "internal-x"
PUB = "pubrepo"

METRICS = {
    "pairs": 14,
    "excluded": 1,
    "fp_reduction": 3.0,
    "fp_reduction_ci": [1.0, 5.0],
    "dorian_recall": 1.0,
    "dorian_recall_ci": [1.0, 1.0],
    "dorian_precision": 0.75,
    "dorian_precision_ci": [0.5, 1.0],
    "baseline_precision": 0.25,
    "baseline_precision_ci": [0.1, 0.4],
}


def _summary(recommendation: str = "PASS", reasons: list[str] | None = None) -> dict:
    return {
        "schema": "dorian-owner-checked-summary-v1",
        "spot_check": {
            "reviewed_pairs": 14,
            "overrides": 1,
            "unsure": 1,
            "out_of_scope": 1,
            "recommendation": recommendation,
            "reasons": reasons or [],
        },
        "panel": {"pairs_judged": 14, "unanimous": 12, "labeled_true": 3},
        "metrics": dict(METRICS),
        # stray non-schema text field: the generator copies enumerated fields
        # only, so this must never reach the outputs
        "debug_note": f"{SECRET}-stray-summary-note",
    }


def _repo(name: str, n_commits: int, n_claims: int) -> dict:
    artifact = f"{SECRET}-docs/{name}.md"
    commits = [
        {
            "sha": f"{SECRET}-sha-{name}-{i}",
            "subject": f"{SECRET}-subject-{name}-{i}",
            "changed_files": [f"{SECRET}-src/{name}/f{i}.py"],
        }
        for i in range(n_commits)
    ]
    claims = [{"id": f"c{j}", "text": f"{SECRET}-claim-text-{name}-{j}"} for j in range(n_claims)]
    return {
        "name": name,
        "t0": f"{SECRET}-t0-{name}",
        "commits": commits,
        "artifacts": [{"uri": artifact, "backed_claim_ratio": 1.0, "claims": claims}],
        "records": [
            {
                "artifact": artifact,
                "commit": c["sha"],
                "baseline_alarm": True,
                "dorian_alarm": False,
                "broken_claims": [],
                "relocated": [],
                "errored": [],
            }
            for c in commits
        ],
    }


def _results() -> dict:
    # 2 repo windows, 4+3=7 replay commits, 2 artifacts, 2+1=3 claims, 7 pairs
    return {
        "spec": "dorian-bench-results-v0",
        "repos": [_repo(PUB, 4, 2), _repo(PRIV, 3, 1)],
    }


def _run(
    tmp_path: Path,
    *extra: str,
    summary: dict | None = None,
    results: dict | None = None,
    tag: str = "x",
) -> tuple[int, Path, Path]:
    spath = tmp_path / "owner_checked_summary.json"
    rpath = tmp_path / "results.json"
    spath.write_text(json.dumps(summary if summary is not None else _summary()) + "\n")
    rpath.write_text(json.dumps(results if results is not None else _results()) + "\n")
    md = tmp_path / f"out-{tag}" / "public_summary.md"
    js = tmp_path / f"out-{tag}" / "public_summary.json"
    rc = public_summary.main(
        [
            "--summary",
            str(spath),
            "--results",
            str(rpath),
            "--out",
            str(md),
            "--json-out",
            str(js),
            *extra,
        ]
    )
    return rc, md, js


# --- 1. structural privacy ----------------------------------------------------


def test_outputs_contain_no_secret_markers(tmp_path: Path) -> None:
    rc, md, js = _run(tmp_path, "--allow-repo", PUB)
    assert rc == 0
    for text in (md.read_text(), js.read_text()):
        assert SECRET not in text
        assert PRIV not in text  # non-allow-listed repo name never appears


def test_allow_listed_repo_appears_private_repo_anonymized(tmp_path: Path) -> None:
    rc, md, js = _run(tmp_path, "--allow-repo", PUB)
    assert rc == 0
    md_text = md.read_text()
    assert PUB in md_text
    assert "private repository A" in md_text
    pub = json.loads(js.read_text())
    assert pub["repos"] == ["private repository A", PUB]  # sorted-name order


def test_no_repo_allowed_by_default(tmp_path: Path) -> None:
    rc, md, js = _run(tmp_path)
    assert rc == 0
    md_text = md.read_text()
    assert PUB not in md_text and PRIV not in md_text
    pub = json.loads(js.read_text())
    # sorted names [internal-x, pubrepo] -> private repository A / B
    assert pub["repos"] == ["private repository A", "private repository B"]


# --- 2. content ----------------------------------------------------------------


def test_md_headline_metrics_provenance_and_caveat(tmp_path: Path) -> None:
    rc, md, _ = _run(tmp_path, "--allow-repo", PUB)
    assert rc == 0
    text = md.read_text()
    # headline metrics table: baseline vs dorian precision/recall + FP reduction, with CIs
    assert "| baseline precision | 0.25 (0.10-0.40) |" in text
    assert "| dorian precision | 0.75 (0.50-1.00) |" in text
    assert "| dorian recall | 1.00 (1.00-1.00) |" in text
    assert "| FP reduction | 3.00 (1.00-5.00) |" in text
    # ground-truth provenance sentence
    assert (
        "blind 3-judge model panel, 14 pairs, 12 unanimous; "
        "owner spot-check of 14 pairs, recommendation PASS" in text
    )
    # mandatory caveat paragraph
    assert "owner-checked but model-adjudicated" in text


def test_composition_counts(tmp_path: Path) -> None:
    rc, md, js = _run(tmp_path, "--allow-repo", PUB)
    assert rc == 0
    pub = json.loads(js.read_text())
    assert pub["composition"] == {
        "repo_windows": 2,
        "replay_commits": 7,
        "artifacts": 2,
        "claims": 3,
        "pairs": 7,
    }
    text = md.read_text()
    assert "2 repo window(s)" in text
    assert "7 replay commit(s)" in text
    assert "2 artifact(s)" in text
    assert "3 claim(s)" in text
    assert "7 (artifact, commit) pair(s)" in text


def test_json_mirror_aggregate_fields(tmp_path: Path) -> None:
    rc, _, js = _run(tmp_path, "--allow-repo", PUB)
    assert rc == 0
    pub = json.loads(js.read_text())
    assert pub["schema"] == "dorian-public-summary-v1"
    assert set(pub) == {
        "schema",
        "cleared",
        "composition",
        "repos",
        "metrics",
        "panel",
        "spot_check",
    }
    assert pub["metrics"] == METRICS
    assert pub["panel"] == {"pairs_judged": 14, "unanimous": 12, "labeled_true": 3}
    assert pub["spot_check"] == {
        "reviewed_pairs": 14,
        "overrides": 1,
        "unsure": 1,
        "out_of_scope": 1,
        "recommendation": "PASS",
        "reasons": [],
    }


# --- 3. cleared flag + banner ----------------------------------------------------


def test_pass_is_cleared_without_banner(tmp_path: Path) -> None:
    rc, md, js = _run(tmp_path)
    assert rc == 0
    assert json.loads(js.read_text())["cleared"] is True
    assert "NOT CLEARED FOR PUBLIC USE" not in md.read_text()


def test_hold_generates_with_leading_banner_and_not_cleared(tmp_path: Path) -> None:
    reasons = ["dorian recall 0.50 < gate 0.85"]
    rc, md, js = _run(tmp_path, summary=_summary("HOLD_PUBLIC_CLAIMS", reasons))
    assert rc == 0  # still generated
    pub = json.loads(js.read_text())
    assert pub["cleared"] is False
    assert pub["spot_check"]["reasons"] == reasons  # enumerated strings pass through
    first_line = md.read_text().splitlines()[0]
    assert "NOT CLEARED FOR PUBLIC USE" in first_line  # banner leads the md


def test_expand_is_not_cleared_and_has_no_banner(tmp_path: Path) -> None:
    rc, md, js = _run(
        tmp_path, summary=_summary("EXPAND_TO_FULL_201", ["material disagreements 3 > 2"])
    )
    assert rc == 0
    assert json.loads(js.read_text())["cleared"] is False
    assert "NOT CLEARED FOR PUBLIC USE" not in md.read_text()


# --- 4. determinism ---------------------------------------------------------------


def test_outputs_are_deterministic(tmp_path: Path) -> None:
    rc, md_a, js_a = _run(tmp_path, "--allow-repo", PUB, tag="a")
    assert rc == 0
    rc, md_b, js_b = _run(tmp_path, "--allow-repo", PUB, tag="b")
    assert rc == 0
    assert md_a.read_bytes() == md_b.read_bytes()
    assert js_a.read_bytes() == js_b.read_bytes()
    assert js_a.read_bytes().endswith(b"\n")


# --- 5. error handling -------------------------------------------------------------


def test_missing_summary_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rpath = tmp_path / "results.json"
    rpath.write_text(json.dumps(_results()) + "\n")
    md = tmp_path / "public_summary.md"
    js = tmp_path / "public_summary.json"
    rc = public_summary.main(
        [
            "--summary",
            str(tmp_path / "nope.json"),
            "--results",
            str(rpath),
            "--out",
            str(md),
            "--json-out",
            str(js),
        ]
    )
    assert rc == 2
    assert not md.exists() and not js.exists()
    err = capsys.readouterr().err
    assert "nope.json" in err
    assert len(err.strip().splitlines()) == 1  # one-line error, no traceback


def test_missing_results_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spath = tmp_path / "owner_checked_summary.json"
    spath.write_text(json.dumps(_summary()) + "\n")
    rc = public_summary.main(
        [
            "--summary",
            str(spath),
            "--results",
            str(tmp_path / "missing.json"),
            "--out",
            str(tmp_path / "o.md"),
            "--json-out",
            str(tmp_path / "o.json"),
        ]
    )
    assert rc == 2
    assert "missing.json" in capsys.readouterr().err


# --- 6. CLI wiring -----------------------------------------------------------------


def test_cli_bench_public_summary_routing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)
    spath = tmp_path / "owner_checked_summary.json"
    rpath = tmp_path / "results.json"
    spath.write_text(json.dumps(_summary()) + "\n")
    rpath.write_text(json.dumps(_results()) + "\n")
    md = tmp_path / "cli.md"
    js = tmp_path / "cli.json"
    rc = cli.main(
        [
            "bench",
            "public-summary",
            "--summary",
            str(spath),
            "--results",
            str(rpath),
            "--out",
            str(md),
            "--json-out",
            str(js),
            "--allow-repo",
            PUB,
        ]
    )
    assert rc == 0
    assert md.exists() and js.exists()
    assert SECRET not in md.read_text()
