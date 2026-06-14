"""Integration tests for the binding-lifecycle benchmark (bench.binding_lifecycle).

These pin the EVIDENCE properties the benchmark must hold, not just that it runs:
mechanical (not dorian-derived) labels, determinism, content-safety, no overclaim
wording, the candidate-vs-alarm separation, the survival condition (no false
BROKEN), and that every required stratum is present and honestly scored — the
ambiguous skip and the semantic ceiling are NOT credited as binding wins.

The whole module is `slow`: it seals + revalidates the quick fixture subset once
(shared via a session fixture) — a few seconds, including a couple of real pytest
(C4) subprocesses.
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

from bench import binding_lifecycle as bl  # noqa: E402
from bench.binding_lifecycle_domains import domains as all_domains  # noqa: E402

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def run(tmp_path_factory) -> tuple[dict, list[dict]]:
    ws = tmp_path_factory.mktemp("bl-bench")
    return bl.run_benchmark(ws, quick=True)


@pytest.fixture(scope="module")
def summary(run) -> dict:
    return run[0]


@pytest.fixture(scope="module")
def records(run) -> list[dict]:
    return run[1]


# --- runs + schema --------------------------------------------------------------


def test_quick_runs_and_schema_is_stable(summary: dict) -> None:
    assert summary["schema"] == bl.SCHEMA
    for key in (
        "provenance",
        "composition",
        "selection_layer",
        "verdict_layer",
        "false_trusted_analysis",
        "semantic_ceiling",
        "by_binding_type",
        "by_mutation_type",
        "error_attribution",
    ):
        assert key in summary, f"missing summary key {key}"
    for key in ("run_id", "fixture_manifest_digest", "dorian_version", "seed"):
        assert key in summary["provenance"]


def test_one_record_per_pair(summary: dict, records: list[dict]) -> None:
    assert summary["composition"]["pairs"] == len(records)
    pairs = {(r["domain"], r["mutation"], r["artifact"]) for r in records}
    assert len(pairs) == len(records)  # no duplicate (domain, mutation, artifact)
    for r in records:
        for col in ("true_fact", "true_trigger", "bound_cand", "bound_broken", "naive"):
            assert col in r


# --- labels are mechanical, not dorian-derived ----------------------------------


def test_labels_are_mechanical_not_dorian_derived(records: list[dict]) -> None:
    """The stale/benign label is a frozen consequence of the mutation spec — not a
    function of dorian's verdict. Recompute it straight from the domain specs and
    assert the records match; a label that depended on dorian's output could not."""
    quick = [d for d in all_domains() if d.quick]
    fact = {}
    trig = {}
    claim_ids = {}
    for d in quick:
        for a in d.artifacts:
            claim_ids[(d.name, a.uri)] = a.claim_ids
        for m in d.mutations:
            fact[(d.name, m.id)] = m.breaks_fact
            trig[(d.name, m.id)] = m.breaks_trigger
    for r in records:
        cids = claim_ids[(r["domain"], r["artifact"])]
        assert r["true_fact"] == bool(fact[(r["domain"], r["mutation"])] & cids)
        assert r["true_trigger"] == bool(trig[(r["domain"], r["mutation"])] & cids)
        # expected_broken is the FROZEN fact-break set, independent of broken_claims
        assert set(r["expected_broken"]) == set(fact[(r["domain"], r["mutation"])] & cids)


# --- determinism ----------------------------------------------------------------


def test_deterministic_rerun_is_byte_identical(tmp_path, summary, records) -> None:
    summary2, records2 = bl.run_benchmark(tmp_path / "again", quick=True)
    assert [bl._records_for_jsonl([r])[0] for r in records] == bl._records_for_jsonl(records2)
    a = json.dumps(summary, sort_keys=True)
    b = json.dumps(summary2, sort_keys=True)
    assert a == b  # run_benchmark leaves measured_commit 'unspecified' -> fully deterministic


# --- content safety + no overclaim ----------------------------------------------


def test_no_forbidden_wording(summary: dict) -> None:
    # whole-word match so structural keys like "provenance" don't trip "proven"
    blob = (json.dumps(summary) + "\n" + bl.render_markdown(summary)).lower()
    for word in bl.FORBIDDEN_WORDS:
        assert not re.search(rf"\b{re.escape(word.lower())}\b", blob), (
            f"forbidden wording leaked: {word!r}"
        )


def test_no_host_path_timestamp_or_warrant_id_leak(summary: dict, records: list[dict]) -> None:
    blob = json.dumps(summary) + "\n" + "\n".join(json.dumps(r) for r in records)
    for bad in ("/Users/", "/tmp/", "/private/", "sealed_at", "warrant_id", "sha256:"):
        assert bad not in blob, f"leak: {bad!r}"
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", blob)  # no ISO timestamp
    # run_benchmark leaves the only sha field unfilled (main() stamps repo HEAD)
    assert summary["provenance"]["measured_commit"] == "unspecified"


# --- candidate vs alarm separation + the survival condition ---------------------


def test_candidate_and_alarm_layers_are_distinct(summary: dict, records: list[dict]) -> None:
    assert "bound_dorian_candidate" in summary["selection_layer"]
    assert "bound_dorian_broken_alarm" in summary["verdict_layer"]
    # candidates are a SUPERSET of brokens: every broken claim was first a candidate
    for r in records:
        if r["bound_broken"]:
            assert r["bound_cand"], f"{r['domain']}/{r['mutation']} broken but not a candidate"
    cand_alarms = summary["selection_layer"]["bound_dorian_candidate"]["alarms"]
    broken_alarms = summary["verdict_layer"]["bound_dorian_broken_alarm"]["alarms"]
    assert cand_alarms >= broken_alarms  # re-checks >= alarms (candidate noise is not alarm noise)


def test_survival_condition_no_false_broken(records: list[dict]) -> None:
    """A claim must NEVER be BROKEN merely because a watched file changed: every
    BROKEN must correspond to a frozen fact-break (verdict precision 1.0)."""
    false_broken = [r for r in records if r["bound_broken"] and not r["true_fact"]]
    assert false_broken == [], f"false BROKEN (the cardinal sin): {false_broken}"


def test_errored_is_separate_from_broken(records: list[dict]) -> None:
    for r in records:
        # an errored claim is never counted as a broken/alarm claim
        assert not (set(r["errored_claims"]) & set(r["broken_claims"]))
        if r["errored_claims"] and not r["broken_claims"]:
            assert r["bound_broken"] is False


# --- every required stratum is present + honestly scored ------------------------


def test_false_trusted_reduction_is_real(summary: dict) -> None:
    ft = summary["false_trusted_analysis"]
    # binding lifts selection recall above the pre-binding checker-path watcher
    assert ft["bound_candidate_selection_recall"] > ft["checker_path_selection_recall"]
    assert ft["trigger_stale_pairs_checker_path_misses_but_binding_catches"] > 0


def test_ambiguous_symbol_skip_not_credited_as_a_win(summary: dict, records: list[dict]) -> None:
    assert "ambiguous_symbol" in summary["composition"]["binding_types"]
    amb = [r for r in records if r["mutation"] == "amb-change-one"]
    assert amb, "ambiguous stratum missing"
    for r in amb:
        # conservative: an ambiguous symbol's definer change is NOT auto-selected...
        assert r["bound_cand"] is False
        assert r["bound_broken"] is False  # ...and never alarmed


def test_ambiguous_pyproject_script_not_bound(summary: dict, records: list[dict]) -> None:
    assert "ambiguous_pyproject_script" in summary["composition"]["binding_types"]
    amb = [r for r in records if r["mutation"] == "pp-edit-ambtarget" and "pp_amb" in r["artifact"]]
    assert amb
    for r in amb:
        assert r["bound_cand"] is False  # the ambiguous script target is unbound


def test_backtick_common_word_not_bound(summary: dict, records: list[dict]) -> None:
    assert "backtick_common_word" in summary["composition"]["binding_types"]
    cw = [r for r in records if r["mutation"] == "bt-change-config"]
    assert cw
    for r in cw:
        assert r["bound_cand"] is False  # `config` (common word) must not bind its definer


def test_c4_whitespace_stratum_present_and_scored(summary: dict, records: list[dict]) -> None:
    assert "c4_whitespace" in summary["composition"]["binding_types"]
    brk = [r for r in records if r["mutation"] == "c4ws-break-impl"]
    benign = [r for r in records if r["mutation"] == "c4ws-benign"]
    assert brk and all(r["bound_broken"] for r in brk)  # broken impl -> caught
    assert benign and not any(r["bound_broken"] for r in benign)  # comment -> not an alarm


def test_semantic_ceiling_present_and_not_overclaimed(summary: dict, records: list[dict]) -> None:
    sc = summary["semantic_ceiling"]
    exist = sc["gutted_body_existence_checker"]
    contrast = sc["gutted_body_behavior_checker_contrast"]
    # existence checker: the gutted body is SELECTED (trigger) but produces NO BROKEN
    assert exist["pairs"] >= 1
    assert exist["bound_broken_alarm_count"] == 0
    assert exist["bound_candidate_selection_recall"] == 1.0
    # the contrast: a behavior (C4) checker on the SAME edit DOES catch it
    assert contrast["pairs"] >= 1
    assert contrast["bound_broken_alarm_recall"] == 1.0
    # and the gutted-body existence record itself is candidate=True, broken=False
    gut = [r for r in records if r["mutation"] == "gut" and "gut_exists" in r["artifact"]]
    assert gut and all(r["bound_cand"] and not r["bound_broken"] for r in gut)


def test_bad_python_is_non_fatal_and_still_binds(summary: dict, records: list[dict]) -> None:
    assert "bad_python_present" in summary["composition"]["binding_types"]
    brk = [r for r in records if r["mutation"] == "badpy-rename"]
    assert brk and all(r["bound_broken"] for r in brk)  # rename caught despite a broken sibling
