"""Deterministic metamorphic transforms over REAL documents, with line maps.

Pre-registered in docs/REAL_DOC_METAMORPHIC_GATE.md (normative). Unlike
bench/metamorph.py (which transforms planted documents whose claim lines are
known from a manifest), these transforms know nothing about claims: every
transform returns the transformed text plus a LINE MAP back to the original
document, so extraction outputs on the transformed text can be compared in
mapped original-line space. Unsupported or ambiguous documents come back as
Untestable with a reason — never silently scored.

No randomness anywhere: insertion points, distractor choice, and rotation are
arithmetic over the document content, so the same input is always the same
output, across calls and processes.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from bench.churn import normalize
from bench.plant import DISTRACTORS
from dorian.model import Claim

FILLER_CAP = 8
FILLER_LINES_PER_DOC = 25  # one insertion point per ~25 lines, min 3
DUPLICATE_SIMILARITY = 0.5  # token-set Jaccard at/above this = duplicate anchor

# ordering-dependent narration that makes section rotation unsafe; scanned on
# prose lines only — fenced content is verbatim data, not document narration
_LOCK_RE = re.compile(
    r"\babove\b|\bbelow\b|previous section|next section|earlier section"
    r"|following section|later in this document",
    re.IGNORECASE,
)
_NUMBERED_HEADING_RE = re.compile(r"^##\s+\d")


@dataclass(frozen=True)
class TransformResult:
    """orig_of[j] = 1-based original line for 0-based transformed line j,
    or None when line j was inserted by the transform."""

    text: str
    orig_of: tuple[int | None, ...]
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Untestable:
    relation: str
    reason: str


def total_lines(text: str) -> int:
    """Content line count: split lines minus the trailing-newline sentinel."""
    return len(text.split("\n")) - (1 if text.endswith("\n") else 0)


def fence_mask(lines: list[str]) -> list[bool]:
    """True for lines inside (or delimiting) a ``` code fence."""
    mask, inside = [], False
    for line in lines:
        marker = line.lstrip().startswith("```")
        mask.append(inside or marker)
        if marker:
            inside = not inside
    return mask


def _token_set(text: str) -> frozenset[str]:
    return frozenset(normalize(text).split())


# --- relation 1: filler insertion ----------------------------------------------------


def filler_insert_real(text: str) -> TransformResult | Untestable:
    """Insert deterministic non-claim filler paragraphs at blank lines outside
    code fences. max(3, total_lines // 25) points (capped at 8), evenly spaced
    over eligible blanks; two distractor sentences per point, cycled from a
    document-derived offset. DISTRACTORS carry no digits and no path tokens
    (the mechanically tested separation rule), so an extracted claim landing
    entirely on inserted lines is an unambiguous false positive."""
    lines = text.split("\n")
    mask = fence_mask(lines)
    eligible = [j for j in range(1, len(lines) - 1) if lines[j] == "" and not mask[j]]
    if len(eligible) < 3:
        return Untestable("filler_insert", "fewer than 3 eligible blank lines")

    total = total_lines(text)
    want = min(FILLER_CAP, max(3, total // FILLER_LINES_PER_DOC), len(eligible))
    if want == 1:
        picks = {eligible[0]}
    else:
        step = (len(eligible) - 1) / (want - 1)
        picks = {eligible[round(i * step)] for i in range(want)}

    start = total % len(DISTRACTORS)
    out: list[str] = []
    orig_of: list[int | None] = []
    inserted: list[int] = []
    ordinal = 0
    for j, line in enumerate(lines):
        if j in picks:
            block = [
                "",
                DISTRACTORS[(start + 2 * ordinal) % len(DISTRACTORS)],
                DISTRACTORS[(start + 2 * ordinal + 1) % len(DISTRACTORS)],
            ]
            ordinal += 1
            for filler in block:
                out.append(filler)
                orig_of.append(None)
                inserted.append(len(out))
        out.append(line)
        orig_of.append(j + 1)
    return TransformResult(
        "\n".join(out),
        tuple(orig_of),
        {
            "inserted_lines": inserted,
            "insertion_points": sorted(j + 1 for j in picks),
            "eligible_blanks": [j + 1 for j in eligible],
        },
    )


# --- relation 2: section reorder -----------------------------------------------------


def section_reorder_real(text: str) -> TransformResult | Untestable:
    """Rotate top-level '## ' sections (outside code fences) by one, preamble
    fixed. Documents with fewer than 3 sections, numbered headings, or
    ordering-dependent narration in any prose line of the section region are
    untestable for this relation."""
    lines = text.split("\n")
    mask = fence_mask(lines)
    starts = [j for j, line in enumerate(lines) if line.startswith("## ") and not mask[j]]
    if len(starts) < 3:
        return Untestable("section_reorder", f"fewer than 3 sections ({len(starts)})")
    for j in starts:
        if _NUMBERED_HEADING_RE.match(lines[j]):
            return Untestable(
                "section_reorder", f"ordering-locked: numbered heading at line {j + 1}"
            )
    for j in range(starts[0], len(lines)):
        if not mask[j] and (hit := _LOCK_RE.search(lines[j])):
            return Untestable(
                "section_reorder", f"ordering-locked: {hit.group(0)!r} at line {j + 1}"
            )

    bounds = [*starts, len(lines)]
    sections = [range(bounds[i], bounds[i + 1]) for i in range(len(starts))]
    order = [*sections[1:], sections[0]]
    out: list[str] = []
    orig_of: list[int | None] = []
    for j in range(starts[0]):  # preamble, fixed
        out.append(lines[j])
        orig_of.append(j + 1)
    for section in order:
        for j in section:
            out.append(lines[j])
            orig_of.append(j + 1)
    return TransformResult(
        "\n".join(out), tuple(orig_of), {"n_sections": len(starts), "rotation": 1}
    )


# --- relation 3: anchor-targeted deletion --------------------------------------------


def delete_lines(text: str, line_start: int, line_end: int) -> TransformResult:
    """Delete the 1-based inclusive line range; map covers the rest in order."""
    lines = text.split("\n")
    out: list[str] = []
    orig_of: list[int | None] = []
    for j, line in enumerate(lines):
        if line_start <= j + 1 <= line_end:
            continue
        out.append(line)
        orig_of.append(j + 1)
    return TransformResult(
        "\n".join(out), tuple(orig_of), {"deleted": list(range(line_start, line_end + 1))}
    )


def unique_anchor_targets(
    text: str, claims: Sequence[Claim], cap: int = 3
) -> tuple[list[Claim], list[tuple[Claim, str]]]:
    """Split claims into deletion targets (uniquely testable anchors, ranked
    most-unique-first, capped) and untestable claims with reasons. A claim is
    unique when no same-length line window elsewhere in the document reaches
    token-set Jaccard >= 0.5 with the claim's tokens; duplicates and
    unanchored claims are untestable, never passes."""
    lines = text.split("\n")
    ranked: list[tuple[float, int, Claim]] = []
    untestable: list[tuple[Claim, str]] = []
    for claim in claims:
        if claim.anchor is None:
            untestable.append((claim, "unanchored"))
            continue
        a, b = claim.anchor.line_start, claim.anchor.line_end
        tokens = _token_set(claim.text)
        if not tokens:
            untestable.append((claim, "empty token set"))
            continue
        width = b - a + 1
        max_sim, max_at = 0.0, 0
        for s in range(1, len(lines) - width + 2):
            if s <= b and s + width - 1 >= a:
                continue  # overlaps the anchor itself
            window = _token_set(" ".join(lines[s - 1 : s - 1 + width]))
            if not window:
                continue
            sim = len(tokens & window) / len(tokens | window)
            if sim > max_sim:
                max_sim, max_at = sim, s
        if max_sim >= DUPLICATE_SIMILARITY:
            untestable.append(
                (claim, f"duplicate anchor: window at line {max_at} similarity {max_sim:.2f}")
            )
        else:
            ranked.append((max_sim, a, claim))
    ranked.sort(key=lambda r: (r[0], r[1]))
    return [claim for _, _, claim in ranked[:cap]], untestable
