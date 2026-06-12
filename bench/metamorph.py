"""Metamorphic transforms for the extraction gate (docs/EXTRACT_GATE.md).

Each transform takes (doc_text, manifest) and returns
(transformed_text, expected_present, expected_absent) where the expectation
lists are PLANTED CLAIM TEXTS (exact lines). The oracle is text-based: line
numbers may legitimately shift, so the gate compares normalized claim texts,
never positional ids.

- filler_insert: meaning-preserving — distractor paragraphs inserted at blank
  lines; every planted claim must survive.
- section_reorder: meaning-preserving — "## " sections rotated by one; every
  planted claim must survive.
- claim_delete: claim-killing — up to 3 planted claim lines removed; exactly
  those claims must disappear (a deleted claim still extracted = fabrication).
"""

from __future__ import annotations

import random

from bench.plant import DISTRACTORS

Transform = tuple[str, list[str], list[str]]  # (text, expected_present, expected_absent)


def _claim_texts(manifest: dict) -> list[str]:
    return [c["text"] for c in manifest["claims"]]


def filler_insert(text: str, manifest: dict, seed: int = 0) -> Transform:
    rng = random.Random(f"filler:{seed}")
    lines = text.split("\n")
    blanks = [i for i, line in enumerate(lines) if line == ""]
    targets = sorted(rng.sample(blanks, min(3, len(blanks))), reverse=True)
    for i in targets:
        lines[i:i] = ["", rng.choice(DISTRACTORS), rng.choice(DISTRACTORS)]
    return "\n".join(lines), _claim_texts(manifest), []


def section_reorder(text: str, manifest: dict) -> Transform:
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if line.startswith("## ")]
    if len(starts) < 2:  # nothing to reorder; identity transform
        return text, _claim_texts(manifest), []
    preamble = lines[: starts[0]]
    bounds = [*starts, len(lines)]
    sections = [lines[bounds[i] : bounds[i + 1]] for i in range(len(starts))]
    rotated = sections[1:] + sections[:1]
    out: list[str] = list(preamble)
    for section in rotated:
        out.extend(section)
    return "\n".join(out), _claim_texts(manifest), []


def claim_delete(text: str, manifest: dict, seed: int = 0) -> Transform:
    rng = random.Random(f"delete:{seed}")
    claims = list(manifest["claims"])
    victims = rng.sample(claims, min(3, len(claims)))
    victim_lines = {c["line"] for c in victims}
    victim_texts = [c["text"] for c in victims]
    lines = [line for i, line in enumerate(text.split("\n"), start=1) if i not in victim_lines]
    survivors = [c["text"] for c in claims if c["text"] not in victim_texts]
    return "\n".join(lines), survivors, victim_texts


TRANSFORMS = {
    "filler_insert": filler_insert,
    "section_reorder": lambda text, manifest, seed=0: section_reorder(text, manifest),
    "claim_delete": claim_delete,
}
