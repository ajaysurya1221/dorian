"""Controlled-mutation benchmark tests (bench/controlled_mutation.py).

Covers: deterministic output, output schema, the pre-registered confusion
matrix (a regression pin — labels are frozen before measurement), and the
public-output discipline (no reviewer-panel evidence wording, no private data or
host-specific values leak into the published summary).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # bench/ is a repo-root package, not installed
    sys.path.insert(0, str(REPO_ROOT))

from bench import controlled_mutation as cm  # noqa: E402

# Public-output discipline: the generated summary + markdown must never present a
# reviewer, panel, or adjudicator as the source of benchmark truth. The forbidden
# tokens are assembled from fragments so this enforcement test does not itself
# contain the literal strings it forbids (keeping the grep gates clean over tests/).
_OWN, _HUM, _MOD, _AGT, _JDG = "own" + "er", "hum" + "an", "mod" + "el", "age" + "nt", "jud" + "ge"
FORBIDDEN_SUBSTRINGS = (
    f"{_OWN}-checked",
    f"{_OWN} checked",
    f"{_OWN} spot-check",
    f"{_HUM} spot-check",
    f"{_HUM}-labeled",
    f"{_HUM} labeled",
    f"{_MOD}-adjudicated",
    f"{_MOD} adjudicated",
    f"{_MOD} panel",
    f"claude {_AGT}s",
)
FORBIDDEN_WORD_RES = (
    rf"\b{_OWN}\b",
    rf"\b{_HUM}\b",
    rf"\b{_AGT}\b",
    rf"\b{_AGT}s\b",
    rf"\b{_JDG}s\b",
    rf"blind .*{_JDG}",
)
# Host-specific / non-deterministic values that must never reach a committed artifact.
LEAK_RES = (
    r"/Users/",
    r"/home/",
    r"/var/folders",
    r"/tmp/",
    r"sha256:",
    r"sealed_at",
    r"captured_at",
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}",  # ISO timestamp
)


@pytest.fixture(scope="module")
def summary(tmp_path_factory: pytest.TempPathFactory) -> dict:
    return cm.run_benchmark(tmp_path_factory.mktemp("cm") / "ws")


def test_output_is_deterministic(tmp_path_factory: pytest.TempPathFactory) -> None:
    a = cm.run_benchmark(tmp_path_factory.mktemp("cm-a") / "ws")
    b = cm.run_benchmark(tmp_path_factory.mktemp("cm-b") / "ws")
    dump = lambda m: json.dumps(m, indent=2, sort_keys=True, ensure_ascii=False)  # noqa: E731
    assert dump(a) == dump(b)
    assert cm.render_markdown(a) == cm.render_markdown(b)


def test_schema_and_shape(summary: dict) -> None:
    assert summary["schema"] == cm.SCHEMA
    assert set(summary) == {
        "schema",
        "fixture",
        "pairs",
        "true_stale_pairs",
        "benign_pairs",
        "errored_pairs",
        "systems",
        "fp_reduction",
        "by_artifact",
        "dorian_error_attribution",
        "bootstrap",
    }
    assert set(summary["systems"]) == {"naive_file_watcher", "line_aware_watcher", "dorian"}
    for block in summary["systems"].values():
        assert set(block) == {
            "alarms",
            "tp",
            "fp",
            "fn",
            "tn",
            "precision",
            "recall",
            "precision_ci",
            "recall_ci",
        }
    assert summary["fixture"] == {
        "artifacts": 2,
        "claims": 9,
        "files": [
            "data/lots.csv",
            "docs/design-naive.md",
            "docs/design.md",
            "src/auth.py",
            "src/config.py",
            "src/routes.py",
        ],
    }


def test_confusion_matrix_matches_preregistered_labels(summary: dict) -> None:
    """Regression pin: the matrix the (frozen) known-truth labels imply. dorian's
    behavior is measured, not assumed — if a checker change moves these, this
    test flags it for honest review, not silent acceptance."""
    assert summary["pairs"] == 41
    assert summary["true_stale_pairs"] == 19
    assert summary["benign_pairs"] == 22
    assert summary["errored_pairs"] == 0

    s = summary["systems"]
    assert (s["naive_file_watcher"]["tp"], s["naive_file_watcher"]["fp"]) == (19, 20)
    assert s["naive_file_watcher"]["fn"] == 0
    assert (s["line_aware_watcher"]["tp"], s["line_aware_watcher"]["fp"]) == (19, 15)
    assert s["line_aware_watcher"]["fn"] == 0
    assert (s["dorian"]["tp"], s["dorian"]["fp"], s["dorian"]["fn"], s["dorian"]["tn"]) == (
        16,
        5,
        3,
        17,
    )
    assert s["dorian"]["precision"] == pytest.approx(16 / 21, abs=1e-3)
    assert s["dorian"]["recall"] == pytest.approx(16 / 19, abs=1e-3)

    fpr = summary["fp_reduction"]
    assert (fpr["naive_fp"], fpr["line_aware_fp"], fpr["dorian_fp"]) == (20, 15, 5)
    assert fpr["vs_naive_file_watcher"] == 4.0
    assert fpr["vs_line_aware_watcher"] == 3.0

    # the deliberate failure modes are present (honest, not a 1.0 victory lap)
    attr = summary["dorian_error_attribution"]
    assert len(attr["false_negatives"]) == 3  # string substring-survival misses
    assert len(attr["false_positives"]) == 5  # regex/exact-string brittleness
    assert s["dorian"]["recall"] < 1.0 and s["dorian"]["precision"] < 1.0


def test_cis_bracket_point_estimates(summary: dict) -> None:
    for block in summary["systems"].values():
        assert block["precision_ci"][0] <= block["precision"] <= block["precision_ci"][1]
        assert block["recall_ci"][0] <= block["recall"] <= block["recall_ci"][1]
    assert summary["bootstrap"]["scope"] == "in-fixture"


def test_public_outputs_have_no_reviewer_evidence_wording(summary: dict) -> None:
    md = cm.render_markdown(summary)
    blob = (md + "\n" + json.dumps(summary)).lower()
    for needle in FORBIDDEN_SUBSTRINGS:
        assert needle not in blob, f"forbidden phrase in public output: {needle!r}"
    for pat in FORBIDDEN_WORD_RES:
        assert not re.search(pat, blob), f"forbidden word in public output: {pat!r}"


def test_public_outputs_do_not_leak_private_or_host_values(summary: dict) -> None:
    blob = cm.render_markdown(summary) + "\n" + json.dumps(summary, sort_keys=True)
    for pat in LEAK_RES:
        assert not re.search(pat, blob), f"leak pattern in public output: {pat!r}"


def test_markdown_states_scope_and_numbers(summary: dict) -> None:
    md = cm.render_markdown(summary)
    assert "synthetic fixture" in md
    assert "universal performance claim" in md
    assert "known-truth" in md
    assert "41 (artifact, mutation) pairs" in md
    # no PASS/GO/verdict vocabulary (no pre-registered gate -> numbers only)
    assert not re.search(r"\b(PASS|FAIL|VERDICT|GO|cleared)\b", md)


def test_readme_has_no_owner_checked_claim() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert f"{_OWN}-checked" not in text
    assert f"{_OWN} checked" not in text


def test_committed_benchmark_doc_is_clean() -> None:
    """docs/BENCHMARK_v0.6.0.md is the committed public summary; it must carry no
    reviewer-evidence wording and no host/private leak."""
    doc = REPO_ROOT / "docs" / "BENCHMARK_v0.6.0.md"
    assert doc.is_file(), "docs/BENCHMARK_v0.6.0.md must exist"
    text = doc.read_text(encoding="utf-8")
    low = text.lower()
    for needle in FORBIDDEN_SUBSTRINGS:
        assert needle not in low
    for pat in FORBIDDEN_WORD_RES:
        assert not re.search(pat, low)
    for pat in LEAK_RES:
        assert not re.search(pat, text)
