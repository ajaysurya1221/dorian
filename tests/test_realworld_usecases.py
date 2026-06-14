"""Tests for the real-world public-case reproductions (bench.realworld_usecases).

These pin the honesty contract: the harness runs offline; every case carries
source metadata and a SCOPED status (never a global overclaim); a reproduced
case's label is DERIVED from dorian's actual BROKEN/VERIFIED behavior, not from
mere watched-file selection; solved/partial/not_solved are distinct; the
trigger-vs-truth ceiling is honored (the partial case re-checks but is not
BROKEN); and no host path / timestamp / private content / overclaim wording leaks.
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

from bench import realworld_usecases as rw  # noqa: E402
from bench.binding_lifecycle import FORBIDDEN_WORDS  # noqa: E402

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def run(tmp_path_factory) -> tuple[dict, list[dict]]:
    ws = tmp_path_factory.mktemp("rwuc")
    return rw.run_benchmark(ws)  # raises if any reproduced label contradicts actual behavior


@pytest.fixture(scope="module")
def summary(run) -> dict:
    return run[0]


@pytest.fixture(scope="module")
def records(run) -> list[dict]:
    return run[1]


def test_runs_offline_and_schema(summary: dict) -> None:
    assert summary["schema"] == rw.SCHEMA
    assert summary["run_mode"] == "offline"
    assert summary["source_date"] == "2026-06-14"
    for key in ("solved_count", "partial_count", "not_solved_count", "cannot_test_count"):
        assert key in summary
    assert summary["candidate_count"] == len(rw._cases())


def test_every_case_has_source_metadata(records: list[dict]) -> None:
    for r in records:
        assert r["source_urls"], f"{r['case_id']} has no source url"
        assert all(u.startswith("http") for u in r["source_urls"])
        assert r["source_project"]
        assert r["source_status_as_of_2026_06_14"]
        assert r["problem_class"]


def test_statuses_are_distinct_and_scoped(summary: dict, records: list[dict]) -> None:
    statuses = {r["solved_status"] for r in records}
    assert {"solved", "partial", "not_solved"} <= statuses  # the honest range is represented
    n = summary
    assert (
        n["solved_count"] + n["partial_count"] + n["not_solved_count"] + n["cannot_test_count"]
        == n["candidate_count"]
    )
    # a scoped, modest summary — no blanket claim
    assert "scoped" in summary["limitations"].lower()


def test_solved_is_derived_from_broken_not_mere_selection(records: list[dict]) -> None:
    """A case is 'solved' only because dorian folded the claim BROKEN — never merely
    because a watched file changed (a candidate that re-checks and passes)."""
    for r in records:
        if r["solved_status"] == "solved":
            a = r["actual_behavior"]
            assert a is not None
            assert a["broken"], f"{r['case_id']} claims solved but nothing was BROKEN"
            assert a["label_matches_actual"]


def test_partial_honors_the_trigger_vs_truth_ceiling(records: list[dict]) -> None:
    """A 'partial' case must re-check the drifted claim (trigger fired) yet leave it
    VERIFIED (the checker could not prove the semantic fact) — not a BROKEN."""
    partials = [r for r in records if r["solved_status"] == "partial"]
    assert partials
    for r in partials:
        a = r["actual_behavior"]
        assert a["broken"], "partial still catches the part it can (e.g. the rename)"
        assert a["passed"], "partial leaves the semantic-drift claim VERIFIED (the ceiling)"
        # the missed claim was re-checked (a candidate) but not broken
        missed = set(a["passed"]) & set(a["candidates_rechecked"])
        assert missed, "the missed claim must have been re-checked, just not proven false"


def test_non_python_or_runtime_cases_are_not_solved(records: list[dict]) -> None:
    # the boundary cases (external file / runtime bug / zero-assertion test) are honest misses
    not_solved = {r["case_id"] for r in records if r["solved_status"] == "not_solved"}
    assert "readme_path_already_fixed_external_file" in not_solved
    assert "zero_assertion_test_counts_as_pass" in not_solved


def test_no_overclaim_wording(summary: dict, records: list[dict]) -> None:
    blob = (json.dumps(summary) + "\n" + rw.render_markdown(summary, records)).lower()
    for word in FORBIDDEN_WORDS:
        assert not re.search(rf"\b{re.escape(word.lower())}\b", blob), f"overclaim: {word!r}"


def test_no_leak_and_no_private_content(summary: dict, records: list[dict]) -> None:
    blob = json.dumps(summary) + "\n" + "\n".join(json.dumps(r) for r in records)
    for bad in ("/Users/", "/tmp/", "/private/", "sealed_at", "warrant_id", "sha256:"):
        assert bad not in blob, f"leak: {bad!r}"
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", blob)  # no ISO timestamp
    for r in records:
        assert r["no_private_content"] is True
        assert r["hermetic"] == (r["reproduction_type"] == "public_case_reproduction")
