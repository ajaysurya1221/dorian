"""Bench smoke test: the SELFTEST replay end-to-end (H1/H2 harness proof).

Acceptance matrix — scripted selftest history, 1 artifact (docs/design.md) x 8
replay commits after t0:

  idx  commit                                     baseline  dorian  broken    relocated
  1    three-change (rename/timeout/login)        ALARM     ALARM   {c2,c3}   [c1]
  2    unrelated helper (src/util.py)             -         -       []        []
  3    add README                                 -         -       []        []
  4    comment in src/config.py, TIMEOUT as-is    ALARM     -       []        []   <- baseline FP
  5    comment in src/routes.py                   ALARM     -       []        []   <- baseline FP
  6    delete a data/lots.csv row (rowcount != 4) ALARM     ALARM   {c4}      []
  7    2nd comment in src/config.py               ALARM     -       []        []   <- baseline FP
  8    2nd comment in src/routes.py               ALARM     -       []        []   <- baseline FP

Hardcoded ground truth for selftest = the two breaking commits {1, 6}:
  baseline TP=2 FP=4 FN=0 -> precision 1/3, recall 1.0
  dorian   TP=2 FP=0 FN=0 -> precision 1.0, recall 1.0
  fp_reduction = 4 / max(1, 0) = 4.0 >= 2.0 (gate, with margin)
  dorian recall 1.0 >= 0.85 (gate)
  H1 backed_claim_ratio = 4/4 = 1.0 >= 0.40 (gate)

Determinism: two full replays produce byte-identical results.json (fixed git
author/committer dates -> stable shas; no timestamps in results), and identical
report.md once the 'Generated:' header line is stripped.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # bench/ is a repo-root package, not installed
    sys.path.insert(0, str(REPO_ROOT))

from bench import ground_truth, metrics, replay  # noqa: E402

CONFIG = REPO_ROOT / "bench" / "repos.json"


def _run_pipeline(base: Path, tag: str) -> Path:
    out = base / f"out-{tag}"
    rc = replay.main(
        [
            "--config",
            str(CONFIG),
            "--workspace",
            str(base / f"ws-{tag}"),
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    rc = ground_truth.main(["--results", str(out / "results.json"), "--out", str(out)])
    assert rc == 0
    rc = metrics.main(
        ["--results", str(out / "results.json"), "--gt", str(out / "gt.json"), "--out", str(out)]
    )
    assert rc == 0
    return out


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    base = tmp_path_factory.mktemp("bench")
    return _run_pipeline(base, "a"), _run_pipeline(base, "b")


def _selftest(out: Path) -> dict:
    data = json.loads((out / "results.json").read_text())
    (repo,) = data["repos"]
    assert repo["name"] == "selftest"
    return repo


def test_replay_alarm_matrix(pipeline: tuple[Path, Path]) -> None:
    repo = _selftest(pipeline[0])
    shas = [c["sha"] for c in repo["commits"]]
    assert len(shas) == 8
    records = repo["records"]
    assert [r["commit"] for r in records] == shas  # one record per (artifact, commit)
    assert all(r["artifact"] == "docs/design.md" for r in records)

    assert [r["baseline_alarm"] for r in records] == [
        True,
        False,
        False,
        True,
        True,
        True,
        True,
        True,
    ]
    assert [r["dorian_alarm"] for r in records] == [
        True,
        False,
        False,
        False,
        False,
        True,
        False,
        False,
    ]

    assert sorted(records[0]["broken_claims"]) == ["c2", "c3"]
    assert records[0]["relocated"] == ["c1"]  # rename is NOT an alarm
    assert records[3]["broken_claims"] == []  # already-broken c2 does not re-alarm
    assert records[5]["broken_claims"] == ["c4"]
    assert records[6]["broken_claims"] == []  # already-broken c2, again no re-alarm
    assert records[7]["broken_claims"] == []  # already-broken c3, again no re-alarm
    assert all(r["errored"] == [] for r in records)

    # the two scripted breaking commits, recorded for the hardcoded selftest GT
    assert repo["breaking_commits"] == [shas[0], shas[5]]


def test_h1_backed_claim_ratio(pipeline: tuple[Path, Path]) -> None:
    repo = _selftest(pipeline[0])
    (artifact,) = repo["artifacts"]
    assert artifact["uri"] == "docs/design.md"
    assert artifact["backed_claim_ratio"] == 1.0  # all 4 claims carry checkers
    assert len(artifact["claims"]) == 4
    assert all(c["backed"] for c in artifact["claims"])


def test_ground_truth_and_labeling_queue(pipeline: tuple[Path, Path]) -> None:
    out = pipeline[0]
    repo = _selftest(out)
    gt = json.loads((out / "gt.json").read_text())
    # hardcoded selftest GT: exactly the two breaking commits
    assert gt["truth"] == {"selftest:docs/design.md": repo["breaking_commits"]}

    rows = [
        json.loads(line)
        for line in (out / "labeling_queue.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(rows) == 6  # one row per alarmed (artifact, commit)
    for row in rows:
        for key in ("repo", "artifact", "commit", "subject", "changed_files"):
            assert key in row
    by_commit = {r["commit"]: r for r in rows}
    first = by_commit[repo["commits"][0]["sha"]]
    texts = " ".join(first["broken_claim_texts"])
    assert "timeout" in texts and "/v1/login" in texts


def test_metrics_and_gates(pipeline: tuple[Path, Path]) -> None:
    out = pipeline[0]
    m = json.loads((out / "metrics.json").read_text())

    b, d = m["systems"]["baseline"], m["systems"]["dorian"]
    assert (b["tp"], b["fp"], b["fn"]) == (2, 4, 0)
    assert b["precision"] == pytest.approx(1 / 3)
    assert b["recall"] == 1.0
    assert (d["tp"], d["fp"], d["fn"]) == (2, 0, 0)
    assert d["precision"] == 1.0
    assert d["recall"] == 1.0

    assert m["fp_reduction"] == pytest.approx(4.0)  # clear of the 2.0 gate
    assert m["fp_reduction"] >= 2.0
    assert m["h1"]["overall"] == 1.0
    assert m["verdict"] == "PASS"
    assert all(g["pass"] for g in m["gates"].values())

    # bootstrap CIs exist and bracket the point estimates
    lo, hi = m["systems"]["dorian"]["recall_ci"]
    assert lo <= 1.0 <= hi

    report = (out / "report.md").read_text()
    assert "VERDICT: PASS" in report
    assert "Generated:" in report


def test_replay_is_deterministic(pipeline: tuple[Path, Path]) -> None:
    out_a, out_b = pipeline
    assert (out_a / "results.json").read_bytes() == (out_b / "results.json").read_bytes()

    def stripped(p: Path) -> str:
        lines = (p / "report.md").read_text().splitlines()
        return "\n".join(line for line in lines if not line.startswith("Generated:"))

    assert stripped(out_a) == stripped(out_b)


def test_prepare_repo_clone_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Generic (non-SELFTEST) clone path with a RELATIVE workspace: the clone
    target must be resolved, or git (running with cwd=workspace) nests the
    clone at workspace/<workspace>/<name> and rev-parse crashes."""
    src = tmp_path / "src-repo"
    replay.build_selftest(src)
    replay._git(src, "checkout", "-q", "main")  # clone source must not be detached
    monkeypatch.chdir(tmp_path)
    entry = {
        "name": "demo",
        "path_or_url": str(src),
        "t0": "HEAD~8",
        "replay_commits": 3,
        "artifacts": [],
    }
    repo, _t0, shas, breaking = replay.prepare_repo(entry, Path("ws"))
    assert repo == Path("ws") / "demo"
    assert (repo / ".git").exists()
    assert len(shas) == 3
    assert breaking is None


def test_heuristic_gt_for_unscripted_repos() -> None:
    """Without breaking_commits, GT falls back to the documented approximation:
    a later commit touching the artifact file marks the nearest earlier
    support-touching commit as true-staleness."""
    repo = {
        "name": "demo",
        "commits": [
            {"sha": "A", "subject": "break support", "changed_files": ["src/x.py"]},
            {"sha": "B", "subject": "benign", "changed_files": ["README.md"]},
            {"sha": "C", "subject": "fix the doc", "changed_files": ["docs/d.md"]},
            {"sha": "D", "subject": "benign", "changed_files": ["README.md"]},
        ],
        "artifacts": [{"uri": "docs/d.md", "backed_claim_ratio": 1.0, "claims": []}],
        "records": [
            {"artifact": "docs/d.md", "commit": "A", "baseline_alarm": True},
            {"artifact": "docs/d.md", "commit": "B", "baseline_alarm": False},
            {"artifact": "docs/d.md", "commit": "C", "baseline_alarm": False},
            {"artifact": "docs/d.md", "commit": "D", "baseline_alarm": False},
        ],
    }
    assert ground_truth.heuristic_truth(repo, "docs/d.md") == ["A"]
