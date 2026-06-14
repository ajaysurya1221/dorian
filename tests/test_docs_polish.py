"""Guards for the v0.9.1 evidence-wording polish, so it can't silently regress.

These pin DOC HYGIENE, not product behavior: the README version display can't
drift to a stale literal, the throwaway-demo line stays "evidence" (not "proof"),
the trigger-vs-truth honesty statements stay present, the real-world discovery
catalog stays >= 12 cited candidates across >= 4 categories (distinct from the
3 reproductions), and overclaim wording stays absent — while HONEST negated
caveats ("not behavior proof", "not universal validation") are explicitly allowed.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
README = (REPO / "README.md").read_text(encoding="utf-8")
PROTOCOL = (REPO / "docs" / "REALWORLD_USECASES_PROTOCOL.md").read_text(encoding="utf-8")
# whitespace-normalized README: phrases may wrap across lines in the source
NORM = re.sub(r"\s+", " ", README).lower()


# --- README version display can't drift ----------------------------------------


def test_readme_has_no_stale_version_badge() -> None:
    # the old hardcoded "status-v0.8" badge is gone; the release badge is dynamic
    assert "status-v0.8" not in README
    assert 'alt="v0.8"' not in README
    assert "img.shields.io/github/v/release/ajaysurya1221/dorian" in README  # dynamic source


# --- "proof" softened to "evidence" (negated "not ... proof" stays allowed) -----


def test_readme_does_not_overclaim_proof() -> None:
    assert "proof the mechanism" not in README
    # every "proof" occurrence is the allowed (negated) "behavior proof" caveat
    for m in re.finditer(r"[^.]*\bproof\b[^.]*", NORM):
        seg = m.group(0)
        assert "behavior proof" in seg, f"unexpected 'proof' usage: {seg.strip()[:90]}"


# --- trigger-vs-truth honesty statements stay present ---------------------------


def test_readme_keeps_trigger_vs_truth_framing() -> None:
    assert "the checker still decides" in NORM  # checker decides truth
    assert "watched file changing never makes a claim" in NORM  # not BROKEN by a file change
    assert (
        "trigger coverage" in NORM and "not** behavior proof" in NORM
    )  # binding != behavior proof
    assert "ambiguity is skipped, not guessed" in NORM  # ambiguity skipped, not guessed
    assert "not universal validation" in NORM  # real-world results are scoped


# --- no overclaim wording (honest negations allowed) ----------------------------


def test_readme_has_no_forbidden_overclaim() -> None:
    low = README.lower()
    for bad in (
        "real-world validated",
        "production-ready",
        "production-grade",
        "guaranteed stale-doc detection",
        "fully solves agent claim drift",
        "fully solves stale docs",
        "broken whenever a watched file changes",
    ):
        assert bad not in low, f"forbidden overclaim in README: {bad!r}"
    # "semantic proof" only ever allowed when negated; README must not assert it
    assert "semantic proof" not in low


# --- the real-world discovery catalog (>=12 candidates, >=4 categories) ----------

_CAT_ROW = re.compile(r"^\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|.*\|\s*([a-z_]+)\s*\|\s*$")


def _catalog_rows() -> list[tuple[str, str, str]]:
    rows = []
    for line in PROTOCOL.splitlines():
        m = _CAT_ROW.match(line)
        if m:
            rows.append((m.group(1).strip(), m.group(2).strip(), m.group(3).strip()))
    return rows


def test_discovery_catalog_has_at_least_12_candidates_across_4_categories() -> None:
    rows = _catalog_rows()
    assert len(rows) >= 12, f"catalog has {len(rows)} candidates, need >= 12"
    categories = {cat for cat, _src, _fit in rows}
    assert len(categories) >= 4, f"catalog spans {len(categories)} categories, need >= 4"
    valid_fit = {"solved", "partial", "not_solved", "cannot_test"}
    for cat, src, fit in rows:
        assert "http" in src, f"candidate in {cat!r} lacks a source URL: {src!r}"
        assert fit in valid_fit, f"candidate fit {fit!r} not in {valid_fit}"


def test_catalog_keeps_report_and_reproduction_counts_distinct() -> None:
    # the catalog (>=12 discovered) is distinct from the report (5 cases) and the
    # 3 hermetic reproductions; the protocol states this reconciliation explicitly
    low = PROTOCOL.lower()
    assert "candidate_count = 5" in low or "candidate_count` = 5" in low
    assert "3 hermetic reproductions" in low
    assert "2 documented boundary cases" in low
    star_rows = sum(
        1 for line in PROTOCOL.splitlines() if re.match(r"^\|\s*\d+\s*\|", line) and "★" in line
    )
    assert star_rows == 5, f"expected 5 ★ (report) rows in the catalog, found {star_rows}"
    assert len(_catalog_rows()) > star_rows  # discovery breadth exceeds the report selection
