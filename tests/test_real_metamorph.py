"""Real-document metamorphic transforms: offline tests (no API anywhere).

Matrix (docs/REAL_DOC_METAMORPHIC_GATE.md is normative):
maps:
(a) every transform is deterministic: same input -> byte-identical text and
    identical line map, across repeated calls
(b) map correctness invariant: every transformed line that maps to an
    original line carries IDENTICAL content; inserted lines map to None
filler:
(c) inserted lines are exactly the None-mapped lines, carry no digits or
    path tokens (the separation rule), and never land inside code fences
(d) insertion count follows max(3, total_lines // 25) capped at 8
(e) fewer than 3 eligible blank lines -> Untestable, with reason
reorder:
(f) rotation by one: line multiset preserved, map is a permutation, the
    preamble stays fixed
(g) fewer than 3 sections -> Untestable; ordering-locked sections
    ("above"/"below"/"previous section"/numbered headings) -> Untestable;
    fenced "## " lines are not sections
delete:
(h) delete_lines removes exactly the requested range; map covers the rest
    in order
uniqueness:
(i) duplicate-content anchors are untestable, never targets; unique anchors
    rank most-unique-first; the cap holds; unanchored claims are untestable
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bench import real_metamorph as rm  # noqa: E402

from dorian.model import Anchor, Claim  # noqa: E402

DOC = """\
# Service notes

Intro prose with nothing special.

## Alpha

The default request timeout is 30 seconds.

Plain filler sentence one.

## Beta

Login is served at /v1/login.

```text
## not a heading
above below previous section
```

## Gamma

The report schema is version 1.1.

Closing line of gamma.
"""


def _lines(text: str) -> list[str]:
    return text.split("\n")


def _assert_map_invariant(orig_text: str, result: rm.TransformResult) -> None:
    """Every mapped transformed line must equal its original line, verbatim."""
    olines, tlines = _lines(orig_text), _lines(result.text)
    assert len(result.orig_of) == len(tlines)
    for j, src in enumerate(result.orig_of):
        if src is not None:
            assert tlines[j] == olines[src - 1], (j, src)


# --- filler --------------------------------------------------------------------------


def test_filler_deterministic_and_mapped() -> None:
    r1 = rm.filler_insert_real(DOC)
    r2 = rm.filler_insert_real(DOC)
    assert isinstance(r1, rm.TransformResult)
    assert r1.text == r2.text and r1.orig_of == r2.orig_of
    _assert_map_invariant(DOC, r1)


def test_filler_inserted_lines_identifiable_and_claim_free() -> None:
    r = rm.filler_insert_real(DOC)
    assert isinstance(r, rm.TransformResult)
    tlines = _lines(r.text)
    inserted = [j + 1 for j, src in enumerate(r.orig_of) if src is None]
    assert inserted == r.meta["inserted_lines"]
    assert len(inserted) > 0
    for ln in inserted:
        content = tlines[ln - 1]
        # separation rule: filler carries no digit and no path token
        assert not re.search(r"[\d/]", content), content
    # every original line survives, in order
    kept = [src for src in r.orig_of if src is not None]
    assert kept == list(range(1, len(_lines(DOC)) + 1))


def test_filler_count_rule_and_fence_exclusion() -> None:
    r = rm.filler_insert_real(DOC)
    assert isinstance(r, rm.TransformResult)
    total = len(DOC.rstrip("\n").split("\n"))
    expected_points = min(8, max(3, total // 25))
    assert len(r.meta["insertion_points"]) == min(expected_points, len(r.meta["eligible_blanks"]))
    # no insertion point may be a blank inside a code fence
    mask = rm.fence_mask(_lines(DOC))
    for orig_blank in r.meta["insertion_points"]:
        assert not mask[orig_blank - 1], orig_blank
    # a long doc wants more filler, capped at 8
    long_doc = "# T\n\n" + "Prose line here.\n\n" * 120
    rl = rm.filler_insert_real(long_doc)
    assert isinstance(rl, rm.TransformResult)
    assert len(rl.meta["insertion_points"]) == 8


def test_filler_untestable_without_blanks() -> None:
    r = rm.filler_insert_real("# T\nline one\nline two\nline three\n")
    assert isinstance(r, rm.Untestable)
    assert r.relation == "filler_insert" and "blank" in r.reason


# --- reorder -------------------------------------------------------------------------


def test_reorder_rotates_sections_with_permutation_map() -> None:
    r = rm.section_reorder_real(DOC)
    assert isinstance(r, rm.TransformResult)
    assert sorted(_lines(r.text)) == sorted(_lines(DOC))  # pure permutation
    assert r.text != DOC  # actually moved
    _assert_map_invariant(DOC, r)
    assert sorted(r.orig_of) == list(range(1, len(_lines(DOC)) + 1))  # bijective
    # preamble fixed: first section heading of the rotated doc is "## Beta"
    tlines = _lines(r.text)
    assert tlines[0] == "# Service notes"
    first_heading = next(line for line in tlines if line.startswith("## "))
    assert first_heading == "## Beta"
    r2 = rm.section_reorder_real(DOC)
    assert r2 == r  # deterministic


def test_reorder_fenced_heading_is_not_a_section() -> None:
    r = rm.section_reorder_real(DOC)
    assert isinstance(r, rm.TransformResult)
    assert r.meta["n_sections"] == 3  # "## not a heading" is fenced out


def test_reorder_untestable_cases() -> None:
    too_few = "# T\n\n## Only\n\nbody\n"
    r = rm.section_reorder_real(too_few)
    assert isinstance(r, rm.Untestable) and "section" in r.reason

    locked = DOC.replace("Closing line of gamma.", "See the section above for details.")
    r2 = rm.section_reorder_real(locked)
    assert isinstance(r2, rm.Untestable) and "order" in r2.reason

    numbered = DOC.replace("## Alpha", "## 1. Alpha")
    r3 = rm.section_reorder_real(numbered)
    assert isinstance(r3, rm.Untestable)


# --- delete --------------------------------------------------------------------------


def test_delete_lines_removes_exact_range() -> None:
    r = rm.delete_lines(DOC, 7, 7)  # the timeout claim line
    assert isinstance(r, rm.TransformResult)
    _assert_map_invariant(DOC, r)
    n = len(_lines(DOC))
    assert list(r.orig_of) == [*range(1, 7), *range(8, n + 1)]
    assert "The default request timeout is 30 seconds." not in r.text
    assert rm.delete_lines(DOC, 7, 7) == r  # deterministic


# --- uniqueness ----------------------------------------------------------------------


def _claim(text: str, a: int, b: int, lines: list[str]) -> Claim:
    quote = "\n".join(lines[a - 1 : b])
    return Claim(
        id=f"cL{a}-{b}",
        text=" ".join(quote.split()),
        kind="fact",
        load_bearing=False,
        anchor=Anchor(line_start=a, line_end=b, quote=quote),
    )


def test_unique_anchor_targets_ranks_and_caps() -> None:
    lines = _lines(DOC)
    timeout = _claim("", 7, 7, lines)
    login = _claim("", 13, 13, lines)
    schema = _claim("", 22, 22, lines)
    targets, untestable = rm.unique_anchor_targets(DOC, [timeout, login, schema], cap=2)
    assert len(targets) == 2 and untestable == []
    full_targets, _ = rm.unique_anchor_targets(DOC, [timeout, login, schema], cap=3)
    assert len(full_targets) == 3


def test_duplicate_anchor_is_untestable() -> None:
    doc = DOC + "\nThe default request timeout is 30 seconds.\n"
    lines = _lines(doc)
    dup = _claim("", 7, 7, lines)
    targets, untestable = rm.unique_anchor_targets(doc, [dup], cap=3)
    assert targets == []
    assert len(untestable) == 1
    claim, reason = untestable[0]
    assert claim is dup and "duplicate" in reason


def test_unanchored_claim_is_untestable() -> None:
    bare = Claim(id="c1", text="floating", kind="fact", load_bearing=False, anchor=None)
    targets, untestable = rm.unique_anchor_targets(DOC, [bare], cap=3)
    assert targets == [] and untestable[0][1] == "unanchored"
