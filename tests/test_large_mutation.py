"""Tests for the v0.7.0 large controlled-mutation benchmark (bench/large_mutation.py).

Covers: deterministic output, output + records schema, the pre-registered
confusion matrix (a regression pin - labels are frozen before measurement),
mechanical-label integrity (every published label is re-derived from the frozen
`breaks` sets, never from dorian's verdict), baseline monotonicity, and the
public-output discipline (no reviewer-evidence wording, no private/host leak, no
stale v0.6.0 numbers in the v0.7.0 doc).
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

from bench import large_mutation as lm  # noqa: E402
from bench import large_mutation_domains as dom  # noqa: E402

from dorian import __version__ as DORIAN_VERSION  # noqa: E402

# Forbidden tokens assembled from fragments so this enforcement test does not
# itself contain the literal strings it forbids (keeps the grep gates clean).
_OWN, _HUM, _MOD, _AGT, _JDG, _REV = (
    "own" + "er",
    "hum" + "an",
    "mod" + "el",
    "age" + "nt",
    "jud" + "ge",
    "review" + "er",
)
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
    rf"\b{_REV}s?\b",
)
LEAK_RES = (
    r"/Users/",
    r"/home/",
    r"/var/folders",
    r"/tmp/",
    r"sha256:",
    r"sealed_at",
    r"captured_at",
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}",
)
COMMITTED_DOC = REPO_ROOT / "docs" / "BENCHMARK_v0.7.0.md"
PROTOCOL_DOC = REPO_ROOT / "docs" / "BENCHMARK_PROTOCOL_v0.7.0.md"


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, list[dict]]:
    return lm.run_benchmark(tmp_path_factory.mktemp("lm") / "ws")


@pytest.fixture(scope="module")
def summary(run: tuple[dict, list[dict]]) -> dict:
    return run[0]


@pytest.fixture(scope="module")
def records(run: tuple[dict, list[dict]]) -> list[dict]:
    return run[1]


def test_output_is_deterministic(
    run: tuple[dict, list[dict]], tmp_path_factory: pytest.TempPathFactory
) -> None:
    a_sum, a_rec = run
    b_sum, b_rec = lm.run_benchmark(tmp_path_factory.mktemp("lm-b") / "ws")
    dump = lambda m: json.dumps(m, indent=2, sort_keys=True, ensure_ascii=False)  # noqa: E731
    assert dump(a_sum) == dump(b_sum)
    assert a_rec == b_rec
    assert lm.render_markdown(a_sum) == lm.render_markdown(b_sum)


def test_schema_and_shape(summary: dict) -> None:
    assert summary["schema"] == lm.SCHEMA
    assert set(summary) == {
        "schema",
        "provenance",
        "composition",
        "systems",
        "fp_reduction",
        "by_domain",
        "by_family",
        "by_artifact",
        "adversarial_slice",
        "dorian_error_attribution",
        "bootstrap",
    }
    assert set(summary["systems"]) == {
        "naive_file_watcher",
        "path_scope_watcher",
        "line_aware_watcher",
        "dorian",
    }
    for block in summary["systems"].values():
        assert set(block) == {
            "alarms",
            "tp",
            "fp",
            "fn",
            "tn",
            "precision",
            "recall",
            "f1",
            "specificity",
            "false_positive_rate",
            "alarm_rate",
            "precision_ci",
            "recall_ci",
        }
    prov = summary["provenance"]
    assert prov["benchmark_id"] == lm.BENCHMARK_ID
    # provenance records the dorian build it ran on; the benchmark is *named* for
    # the v0.7.0 feature set it exercises (revalidate is unchanged), so the doc id
    # stays v0.7.0 even when shipped in a later release.
    assert prov["dorian_version"] == DORIAN_VERSION
    assert prov["seed"] == 42


def test_composition_meets_scale_floor(summary: dict) -> None:
    """The benchmark must be substantially larger than v0.6.0 (41 pairs, 2
    artifacts, 9 claims, 2 baselines)."""
    c = summary["composition"]
    assert c["domains"] >= 5
    assert c["artifacts"] >= 8
    assert c["claims"] >= 40
    assert c["pairs"] >= 200
    assert c["true_stale_pairs"] >= 60
    assert c["benign_pairs"] >= 80
    assert len(c["checker_styles"]) >= 4
    assert len(summary["systems"]) == 4  # 3 baselines + dorian
    assert c["errored_pairs"] == 0


def test_composition_regression_pin(summary: dict) -> None:
    c = summary["composition"]
    assert (c["domains"], c["artifacts"], c["claims"]) == (6, 16, 53)
    assert (c["pairs"], c["true_stale_pairs"], c["benign_pairs"]) == (240, 75, 165)
    assert (c["neutral_pairs"], c["adversarial_pairs"]) == (19, 9)
    assert len(c["checker_styles"]) == 13


def test_confusion_matrix_matches_preregistered_labels(summary: dict) -> None:
    """Regression pin: the matrix the frozen known-truth labels imply. dorian's
    behavior is measured, not assumed - if a checker change moves these, this
    test flags it for honest review, not silent acceptance."""
    s = summary["systems"]
    assert (s["dorian"]["tp"], s["dorian"]["fp"], s["dorian"]["fn"], s["dorian"]["tn"]) == (
        70,
        5,
        5,
        160,
    )
    assert (s["naive_file_watcher"]["tp"], s["naive_file_watcher"]["fp"]) == (75, 146)
    assert (s["path_scope_watcher"]["tp"], s["path_scope_watcher"]["fp"]) == (75, 58)
    assert (s["line_aware_watcher"]["tp"], s["line_aware_watcher"]["fp"]) == (75, 52)
    assert all(
        s[b]["fn"] == 0 for b in ("naive_file_watcher", "path_scope_watcher", "line_aware_watcher")
    )
    assert s["dorian"]["precision"] == pytest.approx(70 / 75, abs=1e-3)
    assert s["dorian"]["recall"] == pytest.approx(70 / 75, abs=1e-3)

    fpr = summary["fp_reduction"]
    assert fpr["vs_naive_file_watcher"] == 29.2
    assert fpr["vs_path_scope_watcher"] == 11.6
    assert fpr["vs_line_aware_watcher"] == 10.4

    attr = summary["dorian_error_attribution"]
    assert len(attr["false_positives"]) == 5  # brittle string + anchored-regex breakage
    assert len(attr["false_negatives"]) == 5  # substring-survival misses
    assert s["dorian"]["recall"] < 1.0 and s["dorian"]["precision"] < 1.0


def test_labels_are_mechanical_not_measured(records: list[dict]) -> None:
    """Every published label is re-derived independently from the frozen
    MutationSpec.breaks sets intersected with each artifact's claims - never from
    dorian's verdict. This is what makes the labels known-truth."""
    by_mut = {(d.name, m.id): m for d in dom.DOMAINS for m in d.mutations}
    artifacts = {(d.name, a.uri): a.claim_ids for d in dom.DOMAINS for a in d.artifacts}
    for r in records:
        mut = by_mut[(r["domain"], r["mutation"])]
        claim_ids = artifacts[(r["domain"], r["artifact"])]
        expected = sorted(mut.breaks & claim_ids)
        assert r["expected_broken"] == expected, (r["domain"], r["mutation"], r["artifact"])
        assert r["true"] == bool(expected)


def test_trap_case_labels(records: list[dict]) -> None:
    """Threshold and substring-survival traps the ground-truth review checks."""
    by = {(r["domain"], r["mutation"], r["artifact"]): r for r in records}
    # '>= 3' still holds at exactly 3 rows: dropping one row does NOT break csv3_lots_min
    r = by[("csv_data", "csv_row_dropped", "docs/data-summary.md")]
    assert r["true"] is False and "csv3_lots_min" not in r["expected_broken"]
    # dropping two rows (-> 2) DOES break '>= 3'
    r = by[("csv_data", "csv_two_rows_dropped", "docs/data-summary.md")]
    assert r["true"] is True and "csv3_lots_min" in r["expected_broken"]
    # adversarial: the route is genuinely removed (true-stale) but dorian MISSES it
    # because the literal survives in a comment (substring scan still hits)
    r = by[("python_service", "py_login_to_comment", "docs/service.md")]
    assert r["true"] is True and r["dorian"] is False  # genuine false negative


def test_baselines_are_monotone_and_recall_complete(records: list[dict]) -> None:
    """naive >= path_scope >= line_aware (alarm sets nest), and every true-stale
    pair is caught by all three watchers (baseline recall is 1.0 by construction)."""
    for r in records:
        if r["lineaware"]:
            assert r["pathscope"], r["mutation"]
        if r["pathscope"]:
            assert r["naive"], r["mutation"]
        if r["true"]:
            assert r["naive"] and r["pathscope"] and r["lineaware"], r["mutation"]


def test_adversarial_slice_precision_is_null_not_one(summary: dict) -> None:
    """dorian catches 0/5 adversarial cases; its precision there is undefined
    (no alarms), reported as null - never the vacuous 1.0 convention."""
    adv = summary["adversarial_slice"]["dorian"]
    assert adv["tp"] == 0 and adv["fp"] == 0 and adv["fn"] == 5
    assert adv["precision"] is None
    assert adv["recall"] == 0.0


def test_records_jsonl_schema(records: list[dict]) -> None:
    assert len(records) == summary_pairs(records)
    rows = lm._records_for_jsonl(records)
    assert all(
        set(r)
        == {
            "domain",
            "artifact",
            "mutation",
            "family",
            "true",
            "expected_broken",
            "naive",
            "pathscope",
            "lineaware",
            "dorian",
            "dorian_broken",
            "errored",
            "changed_files",
            "checker_styles",
        }
        for r in rows
    )


def summary_pairs(records: list[dict]) -> int:
    return len(records)


def test_cis_bracket_point_estimates(summary: dict) -> None:
    for block in summary["systems"].values():
        assert block["precision_ci"][0] <= block["precision"] <= block["precision_ci"][1]
        assert block["recall_ci"][0] <= block["recall"] <= block["recall_ci"][1]
    assert summary["bootstrap"]["scope"] == "in-fixture"


def test_public_outputs_have_no_reviewer_wording(summary: dict, records: list[dict]) -> None:
    blob = (
        lm.render_markdown(summary)
        + "\n"
        + json.dumps(summary)
        + "\n"
        + "\n".join(json.dumps(r) for r in lm._records_for_jsonl(records))
    ).lower()
    for needle in FORBIDDEN_SUBSTRINGS:
        assert needle not in blob, f"forbidden phrase in public output: {needle!r}"
    for pat in FORBIDDEN_WORD_RES:
        assert not re.search(pat, blob), f"forbidden word in public output: {pat!r}"


def test_public_outputs_do_not_leak(summary: dict) -> None:
    blob = lm.render_markdown(summary) + "\n" + json.dumps(summary, sort_keys=True)
    for pat in LEAK_RES:
        assert not re.search(pat, blob), f"leak pattern in public output: {pat!r}"
    # the one live value is the measured commit, and it must be bare hex (no sha256:)
    assert not summary["provenance"]["measured_commit"].startswith("sha256:")


def test_markdown_states_scope_and_no_verdict(summary: dict) -> None:
    md = lm.render_markdown(summary)
    assert "synthetic fixtures" in md
    assert "not** a" in md and "universal performance claim" in md
    assert "known-truth" in md
    assert "240 (artifact, mutation) pairs" in md
    assert "by construction" in md  # the honest baseline-recall caveat
    assert not re.search(r"\b(PASS|FAIL|VERDICT|GO|cleared)\b", md)


def test_committed_doc_matches_render(summary: dict) -> None:
    assert COMMITTED_DOC.is_file(), "docs/BENCHMARK_v0.7.0.md must exist"
    assert COMMITTED_DOC.read_text(encoding="utf-8") == lm.render_markdown(summary)


def test_committed_doc_is_clean() -> None:
    text = COMMITTED_DOC.read_text(encoding="utf-8")
    low = text.lower()
    for needle in FORBIDDEN_SUBSTRINGS:
        assert needle not in low
    for pat in FORBIDDEN_WORD_RES:
        assert not re.search(pat, low)
    for pat in LEAK_RES:
        assert not re.search(pat, text)


def test_no_v060_numbers_in_v070_doc() -> None:
    """Once the v0.7.0 benchmark exists, its doc must not recycle v0.6.0 numbers."""
    text = COMMITTED_DOC.read_text(encoding="utf-8")
    assert "v0.7.0" in text
    assert "v0.6.0" not in text
    assert "41 (artifact, mutation)" not in text  # the v0.6.0 pair count


def test_readme_numbers_match_summary(summary: dict) -> None:
    """The README's v0.7.0 benchmark numbers must match the measured summary."""
    readme = " ".join((REPO_ROOT / "README.md").read_text(encoding="utf-8").split())
    c = summary["composition"]
    s = summary["systems"]
    fpr = summary["fp_reduction"]
    needles = [
        f"{c['pairs']} (artifact, mutation) pairs",
        f"**{s['dorian']['precision']:.2f}** / recall **{s['dorian']['recall']:.2f}**",
        f"**{s['naive_file_watcher']['precision']:.2f}** (naive)",
        f"**{s['path_scope_watcher']['precision']:.2f}** (path-scope)",
        f"**{s['line_aware_watcher']['precision']:.2f}** (line-aware)",
        f"**{fpr['vs_path_scope_watcher']}x",
        f"**{fpr['vs_line_aware_watcher']}x",
        "BENCHMARK_v0.7.0.md",
        "bench large-mutation",
    ]
    for n in needles:
        assert n in readme, f"README missing/mismatched: {n!r}"


def test_protocol_doc_exists_and_clean() -> None:
    assert PROTOCOL_DOC.is_file(), "docs/BENCHMARK_PROTOCOL_v0.7.0.md must exist"
    text = PROTOCOL_DOC.read_text(encoding="utf-8")
    low = text.lower()
    for needle in FORBIDDEN_SUBSTRINGS:
        assert needle not in low
    for pat in FORBIDDEN_WORD_RES:
        assert not re.search(pat, low)
    # the protocol declares no pass/fail gate
    assert not re.search(r"\b(PASS|FAIL|VERDICT|GO|cleared)\b", text)
