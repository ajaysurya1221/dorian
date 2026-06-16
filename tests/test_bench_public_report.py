"""The Markdown report must refuse overclaiming language and carry the honest framing.

Forbidden vocabulary is the union of docs/PUBLIC_BENCHMARK_PROTOCOL.md §8 and the mission
hard boundaries; required wording keeps trigger/truth separate and frames the subjects as
candidates, reproducible on frozen SHAs — never "validated".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # bench/ is a repo-root package, not installed
    sys.path.insert(0, str(REPO_ROOT))

from bench import public_repos as pr  # noqa: E402

SAMPLE = {
    "schema_version": 1,
    "benchmark": "public-repos",
    "dorian_version": "1.0.0rc1",
    "repo": {
        "name": "humanize",
        "url": "https://github.com/python-humanize/humanize",
        "frozen_sha": "2ddb5903cdc1c7e6eb6b083f4f99f73db50aecd9",
        "license": "MIT",
    },
    "claims_total": 0,
    "mutations_total": 0,
    "results": [],
    "truth_layer": {
        "broken_expected": 0,
        "broken_observed": 0,
        "trusted_expected": 0,
        "trusted_observed": 0,
        "errored": 0,
    },
    "trigger_layer": {"candidate_claims_checked": 0, "claims_skipped": 0},
    "status": "NO_CLAIMS",
}


def test_report_includes_required_wording() -> None:
    md = pr.render_report([SAMPLE])
    for phrase in (
        "reproducible on these frozen SHAs",
        "candidate benchmark subjects",
        "trigger and truth layers reported separately",
    ):
        assert phrase in md, f"missing required phrase: {phrase!r}"


def test_report_refuses_forbidden_phrases() -> None:
    md = pr.render_report([SAMPLE]).lower()
    for forbidden in (
        "validated on real repos",
        "works on real repos",
        "proves dorian works",
        "generalizes",
        "production-grade",
    ):
        assert forbidden not in md, f"report leaked forbidden phrase: {forbidden!r}"


def test_no_claims_report_says_not_executed_evidence() -> None:
    md = pr.render_report([SAMPLE])
    assert "NO_CLAIMS" in md or "no public real-repo benchmark result" in md.lower()


def test_guard_overclaim_raises_on_forbidden_text() -> None:
    with pytest.raises(pr.OverclaimError):
        pr.guard_overclaim("dorian is validated on real repos and generalizes everywhere.")
    with pytest.raises(pr.OverclaimError):
        pr.guard_overclaim("This proves dorian works in production-grade settings.")


def test_guard_overclaim_allows_honest_text() -> None:
    pr.guard_overclaim(
        "Reproducible on these frozen SHAs; candidate benchmark subjects; "
        "trigger and truth layers reported separately. Not a real-world performance claim."
    )


def test_published_benchmark_doc_body_is_honesty_guarded() -> None:
    """The hand-authored docs/BENCHMARK_PUBLIC_REAL_REPOS.md must itself pass the overclaim
    guard (excluding its 'Allowed vs forbidden wording' glossary, which legitimately lists the
    forbidden terms) and carry the required honest framing. Locks the curated doc against drift."""
    doc = (REPO_ROOT / "docs" / "BENCHMARK_PUBLIC_REAL_REPOS.md").read_text(encoding="utf-8")
    body = doc.split("## Allowed vs forbidden")[0]
    pr.guard_overclaim(body)  # raises OverclaimError on any assertive forbidden phrase/word
    for phrase in pr.REQUIRED_PHRASES:
        assert phrase in doc, f"benchmark doc missing required framing: {phrase!r}"
