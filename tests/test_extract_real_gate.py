"""Real-document metamorphic gate runner: offline tests (no API anywhere).

Matrix (docs/REAL_DOC_METAMORPHIC_GATE.md is normative):
mapping:
(a) tier boundaries are exact; spans on transformed documents map to
    original-line sets; inserted filler lines map to the empty set
matching:
(b) greedy IoU >= 0.5 matching decomposes pairs into exact matches,
    boundary-only jitter, and genuine selection disagreement; boundary
    distance is hand-computed
deletion scoring:
(c) vanished / fabricated / duplicate-posthoc / artifact outcomes; an empty
    or errored re-extraction is an ARTIFACT, never a vanish-pass
    (the v0.6.0 empty-vs-empty rule); fabrication = survivor whose own
    anchor lines do not support its text (the cache-leak shape)
invariance:
(d) the transform effect is baseline pairwise agreement minus
    transform-vs-baseline agreement, hand-computed
classification:
(e) the verdict is a deterministic pure function; promotion, every rejection
    trigger, between-bands insufficiency, floors, empty-empty flags, and
    threshold boundary values (0.20 / 0.35) behave exactly as pre-registered;
    hard-evidence rejection trumps unmet floors
aggregate:
(f) exit codes: 0 when any SUT promotes, 3 when both reject, 4 otherwise;
    per-doc results must match the manifest
sanity floor:
(g) anti-triviality: a whole-document span or >= 0.70 line coverage rejects;
    near-whole spans, >= 0.50 coverage, near-empty output, or filler
    over-selection block promotion; missing sanity inputs cannot promote; a
    degenerate "perfectly stable" SUT is rejected at aggregate, not promoted
thresholds:
(h) every GATES constant is stated verbatim in the pre-registration document
    (no silent threshold drift)
guard:
(i) live runs refuse without the committed gate doc, a clean tree (incl.
    untracked), an absent results document, and a pushed HEAD
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bench import extract_real_gate as erg  # noqa: E402
from bench import real_metamorph as rm  # noqa: E402

from dorian.model import Anchor, Claim  # noqa: E402

# --- helpers -------------------------------------------------------------------------


def _claim(text: str, a: int, b: int) -> Claim:
    return Claim(
        id=f"cL{a}-{b}",
        text=text,
        kind="fact",
        load_bearing=False,
        anchor=Anchor(line_start=a, line_end=b, quote=text),
    )


# --- mapping -------------------------------------------------------------------------


def test_tier_boundaries() -> None:
    assert erg.tier_of(30) == "short" and erg.tier_of(79) == "short"
    assert erg.tier_of(80) == "medium" and erg.tier_of(119) == "medium"
    assert erg.tier_of(120) == "long" and erg.tier_of(326) == "long"


def test_mapped_line_set_through_filler() -> None:
    doc = "# T\n\nThe timeout is 30 seconds.\n\nLogin is at /v1/login.\n\nVersion is 1.1.\n"
    r = rm.filler_insert_real(doc)
    assert isinstance(r, rm.TransformResult)
    inserted = r.meta["inserted_lines"]
    # a span lying entirely on inserted lines maps to the empty set
    lines_set, n_inserted = erg.mapped_line_set((inserted[1], inserted[2]), r.orig_of)
    assert lines_set == frozenset() and n_inserted == 2
    # an original content line maps back to its original number
    tlines = r.text.split("\n")
    j = tlines.index("The timeout is 30 seconds.") + 1
    lines_set, n_inserted = erg.mapped_line_set((j, j), r.orig_of)
    assert lines_set == frozenset({3}) and n_inserted == 0


# --- matching ------------------------------------------------------------------------


def test_match_decomposition_hand_computed() -> None:
    a = [frozenset({1, 2}), frozenset({5})]
    b = [frozenset({1, 2}), frozenset({9})]
    d = erg.match_decomposition(a, b)
    assert d["exact_matches"] == 1 and d["boundary_jitter"] == 0 and d["selection_only"] == 2
    assert abs(d["boundary_distance"] - (1 - 1 / 3)) < 1e-9  # m=1, |A|+|B|-m=3

    # IoU exactly 0.5 is a boundary-jitter match
    d2 = erg.match_decomposition([frozenset({1, 2, 3})], [frozenset({2, 3, 4})])
    assert d2["exact_matches"] == 0 and d2["boundary_jitter"] == 1 and d2["selection_only"] == 0
    assert d2["boundary_distance"] == 0.0

    # empty-vs-empty is flagged, never scored as agreement
    d3 = erg.match_decomposition([], [])
    assert d3["empty_empty"] is True and d3["boundary_distance"] is None
    d4 = erg.match_decomposition([], [frozenset({1})])
    assert d4["empty_empty"] is False and d4["boundary_distance"] == 1.0


# --- deletion scoring ----------------------------------------------------------------

DEL_DOC = "alpha one\nbravo two\ncharlie three\ndelta four\n"


def test_deletion_vanished() -> None:
    target = _claim("bravo two", 2, 2)
    deleted = rm.delete_lines(DEL_DOC, 2, 2)
    got = erg.score_deletion(target, deleted.text, [_claim("charlie three", 1, 1)], None)
    assert got["outcome"] == "vanished"


def test_deletion_empty_is_artifact_never_a_pass() -> None:
    target = _claim("bravo two", 2, 2)
    deleted = rm.delete_lines(DEL_DOC, 2, 2)
    assert erg.score_deletion(target, deleted.text, [], None)["outcome"] == "artifact"
    assert (
        erg.score_deletion(target, deleted.text, [], "empty: no valid spans")["outcome"]
        == "artifact"
    )
    assert (
        erg.score_deletion(target, deleted.text, [], "truncation: max_tokens")["outcome"]
        == "artifact"
    )


def test_deletion_fabricated_when_anchor_does_not_support() -> None:
    # the cache-leak shape: the deleted claim's text "survives" but its anchor
    # lines in the deleted document hold unrelated content
    target = _claim("bravo two", 2, 2)
    deleted = rm.delete_lines(DEL_DOC, 2, 2)  # lines now: alpha one/charlie three/delta four
    survivor = _claim("bravo two", 3, 3)  # line 3 is "delta four" — no support
    got = erg.score_deletion(target, deleted.text, [survivor], None)
    assert got["outcome"] == "fabricated"


def test_deletion_duplicate_posthoc_when_content_exists_elsewhere() -> None:
    doc = DEL_DOC + "bravo two\n"  # duplicate content the prefilter should catch
    target = _claim("bravo two", 2, 2)
    deleted = rm.delete_lines(doc, 2, 2)  # the duplicate is now line 4
    survivor = _claim("bravo two", 4, 4)
    got = erg.score_deletion(target, deleted.text, [survivor], None)
    assert got["outcome"] == "duplicate_posthoc"


# --- invariance ----------------------------------------------------------------------


def test_invariance_effect_hand_computed() -> None:
    stable = [[frozenset({1, 2})], [frozenset({1, 2})], [frozenset({1, 2})]]
    assert erg.invariance_effect(stable, [frozenset({1, 2})]) == 0.0
    assert erg.invariance_effect(stable, []) == 1.0  # transform lost everything


# --- classification ------------------------------------------------------------------


def _metrics(**over) -> dict:
    m = {
        "docs_total": 16,
        "docs_complete": 16,
        "docs_per_tier": {"short": 6, "medium": 5, "long": 5},
        "tier_boundary_churn": {"short": 0.05, "medium": 0.08, "long": 0.12},
        "tier_exact_churn": {"short": 0.10, "medium": 0.15, "long": 0.20},
        "sanity_line_coverage": 0.05,
        "sanity_max_span_share": 0.05,
        "sanity_mean_claims": 5.0,
        "whole_doc_spans": 0,
        "filler_overselect_rate": 0.0,
        "filler_hard_fp": 0,
        "filler_testable": 16,
        "filler_effect_by_tier": {"short": 0.02, "medium": 0.03, "long": 0.05},
        "reorder_testable": 10,
        "reorder_effect_by_tier": {"short": 0.02, "medium": 0.03, "long": 0.05},
        "deletion_probes": 20,
        "deletion_fabricated": 0,
        "truncation": 0,
        "behavioral_empty": 0,
        "total_draws": 200,
        "empty_empty_pairs": 0,
        "unanchored": 0,
    }
    m.update(over)
    return m


def test_classify_promotion_and_determinism() -> None:
    v1 = erg.classify(_metrics())
    v2 = erg.classify(_metrics())
    assert v1 == v2 and v1["verdict"] == "PROMOTION"


def test_classify_rejection_triggers() -> None:
    assert erg.classify(_metrics(deletion_fabricated=1))["verdict"] == "REJECTION"
    assert erg.classify(_metrics(filler_hard_fp=1))["verdict"] == "REJECTION"
    long_churn = _metrics(tier_boundary_churn={"short": 0.05, "medium": 0.08, "long": 0.35})
    assert erg.classify(long_churn)["verdict"] == "REJECTION"  # >= 0.35 rejects
    artifacts = _metrics(truncation=30, behavioral_empty=15)  # 45/200 > 20%
    assert erg.classify(artifacts)["verdict"] == "REJECTION"
    # hard evidence trumps unmet floors
    thin = _metrics(deletion_fabricated=1, docs_complete=5)
    assert erg.classify(thin)["verdict"] == "REJECTION"


def test_classify_between_bands_is_insufficient() -> None:
    mid = _metrics(tier_boundary_churn={"short": 0.05, "medium": 0.08, "long": 0.25})
    got = erg.classify(mid)
    assert got["verdict"] == "INSUFFICIENT"
    # exactly at the promotion bound fails promotion but does not reject
    edge = _metrics(tier_boundary_churn={"short": 0.05, "medium": 0.08, "long": 0.20})
    assert erg.classify(edge)["verdict"] == "INSUFFICIENT"
    # churn-band rejection needs the long-tier floor; below it -> insufficient
    thin_long = _metrics(
        tier_boundary_churn={"short": 0.05, "medium": 0.08, "long": 0.40},
        docs_per_tier={"short": 7, "medium": 6, "long": 3},
    )
    assert erg.classify(thin_long)["verdict"] == "INSUFFICIENT"


def test_classify_floors_and_artifact_flags() -> None:
    assert erg.classify(_metrics(docs_complete=12))["verdict"] == "INSUFFICIENT"
    assert erg.classify(_metrics(reorder_testable=5))["verdict"] == "INSUFFICIENT"
    assert erg.classify(_metrics(deletion_probes=4))["verdict"] == "INSUFFICIENT"
    assert erg.classify(_metrics(empty_empty_pairs=1))["verdict"] == "INSUFFICIENT"
    assert erg.classify(_metrics(unanchored=2))["verdict"] == "INSUFFICIENT"
    assert erg.classify(_metrics(truncation=1))["verdict"] == "INSUFFICIENT"
    assert erg.classify(_metrics(filler_testable=7))["verdict"] == "INSUFFICIENT"


# --- anti-triviality sanity floor ----------------------------------------------------


def test_classify_rejects_degenerate_extraction() -> None:
    # one giant whole-document span anywhere is a hard rejection, even with
    # otherwise-perfect (trivially stable) churn
    assert erg.classify(_metrics(whole_doc_spans=1))["verdict"] == "REJECTION"
    # echoing >= 70% of the document's lines is gross over-selection
    assert erg.classify(_metrics(sanity_line_coverage=0.70))["verdict"] == "REJECTION"
    assert erg.classify(_metrics(sanity_line_coverage=0.85))["verdict"] == "REJECTION"


def test_classify_trivial_solutions_are_not_promoted() -> None:
    # near-whole-document max span (boundary churn would be ~0) is not promotable
    assert erg.classify(_metrics(sanity_max_span_share=0.55))["verdict"] == "INSUFFICIENT"
    # over-selecting half the lines (the "select nearly every block" win) blocks promotion
    assert erg.classify(_metrics(sanity_line_coverage=0.50))["verdict"] == "INSUFFICIENT"
    # near-empty extraction (one claim per doc) is not a stable extractor worth promoting
    assert erg.classify(_metrics(sanity_mean_claims=1.0))["verdict"] == "INSUFFICIENT"
    # grabbing the inserted filler on more than half the claims blocks promotion
    assert erg.classify(_metrics(filler_overselect_rate=0.60))["verdict"] == "INSUFFICIENT"
    # missing sanity inputs are conservative: cannot promote on absent evidence
    for key in (
        "sanity_max_span_share",
        "sanity_line_coverage",
        "sanity_mean_claims",
        "filler_overselect_rate",
    ):
        assert erg.classify(_metrics(**{key: None}))["verdict"] == "INSUFFICIENT"


# the gate boundary values: exactly-at-bound fails promotion but does not reject
def test_classify_sanity_boundary_values() -> None:
    assert erg.classify(_metrics(sanity_max_span_share=0.50))["verdict"] == "INSUFFICIENT"
    assert erg.classify(_metrics(sanity_line_coverage=0.50))["verdict"] == "INSUFFICIENT"
    # just under the reject band (echoing) but over the promotion band -> insufficient
    assert erg.classify(_metrics(sanity_line_coverage=0.60))["verdict"] == "INSUFFICIENT"
    assert erg.classify(_metrics(sanity_mean_claims=2.0))["verdict"] == "PROMOTION"
    assert erg.classify(_metrics(filler_overselect_rate=0.50))["verdict"] == "PROMOTION"


# --- threshold immutability (code <-> pre-registration agreement) ---------------------

GATE_DOC_TEXT = (REPO_ROOT / "docs" / "REAL_DOC_METAMORPHIC_GATE.md").read_text(encoding="utf-8")

# every gate constant in code must be stated, by exactly this rendering, in the
# normative pre-registration document — no silent threshold drift is possible
DOC_RENDERING = {
    "boundary_churn_tier": "0.20",
    "exact_churn_tier": "0.30",
    "invariance_effect": "0.10",
    "reject_long_boundary_churn": "0.35",
    "reject_artifact_share": "20%",
    "empty_draw_share": "5%",
    "iou_match": "0.5",
    "survivor_fuzzy": "0.75",
    "support_jaccard": "0.9",
    "max_span_share": "0.50",
    "reject_whole_doc_share": "0.80",
    "max_line_coverage": "0.50",
    "reject_line_coverage": "0.70",
    "min_claims_per_doc": "2",
    "max_filler_overselect": "0.50",
    "min_doc_lines": "30",
    "min_docs_complete": "15",
    "min_docs_per_tier": "3",
    "min_long_docs": "4",
    "min_reorder_testable": "8",
    "min_deletion_probes": "10",
    "k": "3",
    "baseline_draws": "3",
    "deletion_cap": "3",
}


def test_thresholds_are_pinned_to_the_preregistration() -> None:
    # 1. every code constant has a documented rendering — adding a threshold to
    #    GATES without documenting it fails here (drift backstop)
    assert set(erg.GATES) == set(DOC_RENDERING)
    # 2. each rendering actually appears in the normative document
    for key, rendering in DOC_RENDERING.items():
        assert rendering in GATE_DOC_TEXT, f"{key}={erg.GATES[key]} not stated as {rendering!r}"
    # 3. decimal renderings equal the code value (the % and count gates are
    #    checked by presence above; their code form is exercised by classify tests)
    for key, rendering in DOC_RENDERING.items():
        if rendering.replace(".", "", 1).isdigit() and "." in rendering:
            assert float(rendering) == float(erg.GATES[key]), key


# --- aggregate -----------------------------------------------------------------------


def _doc_json(
    path: str,
    tier: str,
    lines: int,
    *,
    churn=0.05,
    fabricated=0,
    coverage=0.05,
    max_share=0.05,
    mean_claims=5.0,
    whole=0,
    filler_touch=0,
) -> dict:
    pair = {
        "exact_matches": 5,
        "boundary_jitter": 0,
        "selection_only": 0,
        "exact_distance": churn,
        "fuzzy_distance": churn,
        "boundary_distance": churn,
        "empty_empty": False,
    }
    return {
        "schema": "dorian-real-gate-v1",
        "doc": path,
        "tier": tier,
        "lines": lines,
        "sha256": f"sha-{path}",
        "sut": "anchor",
        "baseline": {
            "per_draw": [{"n_claims": 5, "spans": [[2, 2]], "texts": ["t"], "error": None}] * 3,
            "pairs": [pair] * 3,
            "exact_churn": churn,
            "fuzzy_churn": churn,
            "boundary_churn": churn,
            "empty_empty_pairs": 0,
            "sanity": {
                "n_lines": lines,
                "mean_line_coverage": coverage,
                "max_span_share": max_share,
                "mean_claims": mean_claims,
                "whole_doc_spans": whole,
            },
        },
        "filler": {
            "testable": True,
            "reason": None,
            "hard_fp": 0,
            "boundary_overlap": 0,
            "n_claims": 5,
            "touch_inserted": filler_touch,
            "effect": 0.02,
            "error": None,
        },
        "reorder": {
            "testable": True,
            "reason": None,
            "hard_fp": 0,
            "boundary_overlap": 0,
            "n_claims": 5,
            "touch_inserted": 0,
            "effect": 0.02,
            "error": None,
        },
        "deletion": {
            "candidates": 3,
            "untestable": [],
            "probes": [{"claim_id": "cL2-2", "outcome": "vanished", "detail": ""}] * 2,
            "vanished": 2,
            "fabricated": fabricated,
            "duplicate_posthoc": 0,
            "artifact": 0,
        },
        "artifact_counters": {
            "truncation": 0,
            "behavioral_empty": 0,
            "total_draws": 14,
            "unanchored": 0,
        },
    }


def _corpus() -> list[tuple[str, str, int]]:
    docs = []
    for i in range(6):
        docs.append((f"s{i}.md", "short", 40))
    for i in range(5):
        docs.append((f"m{i}.md", "medium", 100))
    for i in range(5):
        docs.append((f"l{i}.md", "long", 150))
    return docs


def _write_results(tmp_path: Path, name: str, **over) -> Path:
    d = tmp_path / name
    d.mkdir()
    for path, tier, lines in _corpus():
        doc = _doc_json(path, tier, lines, **over)
        (d / f"{path}.json").write_text(json.dumps(doc), encoding="utf-8")
    return d


def _write_manifest(tmp_path: Path) -> Path:
    manifest = {
        "schema": "dorian-real-gate-manifest-v1",
        "head": "deadbeef",
        "docs": [{"path": p, "tier": t, "lines": n, "sha256": f"sha-{p}"} for p, t, n in _corpus()],
    }
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(manifest), encoding="utf-8")
    return p


def _aggregate(tmp_path: Path, dir_a: Path, dir_b: Path) -> int:
    return erg.main(
        [
            "aggregate",
            "--manifest",
            str(_write_manifest(tmp_path)),
            "--dir-a",
            str(dir_a),
            "--dir-b",
            str(dir_b),
            "--out",
            str(tmp_path / "report.json"),
            "--md",
            str(tmp_path / "report.md"),
        ]
    )


def test_aggregate_any_promotion_exits_zero(tmp_path: Path) -> None:
    a = _write_results(tmp_path, "a", churn=0.05)
    b = _write_results(tmp_path, "b", fabricated=1)
    assert _aggregate(tmp_path, a, b) == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["sut_a"]["verdict"] == "PROMOTION"
    assert report["sut_b"]["verdict"] == "REJECTION"
    assert (tmp_path / "report.md").is_file()


def test_aggregate_both_rejected_exits_three(tmp_path: Path) -> None:
    a = _write_results(tmp_path, "a", fabricated=1)
    b = _write_results(tmp_path, "b", fabricated=2)
    assert _aggregate(tmp_path, a, b) == 3


def test_aggregate_incomplete_results_are_insufficient(tmp_path: Path) -> None:
    a = _write_results(tmp_path, "a", churn=0.25)  # between bands
    b = _write_results(tmp_path, "b")
    next(b.glob("l*.json")).unlink()  # missing long doc -> floors fail for b
    next(b.glob("l*.json")).unlink()
    assert _aggregate(tmp_path, a, b) == 4


def test_aggregate_degenerate_sut_is_not_promoted(tmp_path: Path) -> None:
    # SUT-A is perfectly "stable" only because every draw is one whole-document
    # span; the sanity floor must reject that trivial stability, not promote it.
    a = _write_results(tmp_path, "a", churn=0.0, whole=1)
    b = _write_results(tmp_path, "b", coverage=0.50)  # over-selection -> insufficient
    code = _aggregate(tmp_path, a, b)
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["sut_a"]["verdict"] == "REJECTION"
    assert report["sut_b"]["verdict"] == "INSUFFICIENT"
    assert code == 4  # no promotion: one rejected, one insufficient


# --- guard ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "HOME": str(repo.parent),
    }
    import os

    subprocess.run(
        ["git", *args],
        cwd=repo,
        env={**os.environ, **env},
        check=True,
        capture_output=True,
    )


def test_preregistration_guard(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    (repo / "docs" / "REAL_DOC_METAMORPHIC_GATE.md").write_text("# gate\n", encoding="utf-8")

    err = erg.preregistration_error(repo)
    assert err is not None and "track" in err  # not yet tracked

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "pre-register")
    err = erg.preregistration_error(repo)
    assert err is not None and "remote" in err  # tracked + clean, but never pushed

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, capture_output=True)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "origin", "main")
    assert erg.preregistration_error(repo) is None  # pushed: live runs may proceed

    # the results document must not predate the measurement
    results = repo / "docs" / "REAL_DOC_METAMORPHIC_GATE_RESULTS.md"
    results.write_text("# leaked results\n", encoding="utf-8")
    err = erg.preregistration_error(repo)
    assert err is not None and "exists" in err
    results.unlink()
    assert erg.preregistration_error(repo) is None

    # an untracked stray file (selector/scorer/test) blocks the run
    stray = repo / "stray_scorer.py"
    stray.write_text("# untracked\n", encoding="utf-8")
    err = erg.preregistration_error(repo)
    assert err is not None and "untracked" in err
    stray.unlink()
    assert erg.preregistration_error(repo) is None

    (repo / "docs" / "REAL_DOC_METAMORPHIC_GATE.md").write_text("# edited\n", encoding="utf-8")
    err = erg.preregistration_error(repo)
    assert err is not None and "clean" in err  # dirty tree refuses again
