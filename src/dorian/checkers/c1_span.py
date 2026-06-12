"""C1 span-anchor checker: is the cited span still present, possibly relocated?

PASS when the anchored span is hash-identical at its (rename-resolved) location,
found verbatim elsewhere in the file, or — behind the c2lite flag — fuzzy-matched
at >= 0.90 similarity. FAIL means the span's content drifted or vanished;
infrastructure problems (unreachable original ref, ref span inconsistent with the
captured hash) are ERROR, never FAIL.
"""

from __future__ import annotations

import difflib

from dorian import gitio
from dorian.checkers import registry
from dorian.checkers.base import CheckContext, CheckResult, Verdict
from dorian.model import CheckerSpec, sha256_hex, span_hash

_C2LITE_RATIO = 0.90
_C2LITE_MAX_LINES = 20_000


def check_c1(ctx: CheckContext, spec: CheckerSpec) -> CheckResult:
    entry = next((e for e in ctx.supports if e.id == spec.program), None)
    if entry is None:
        return CheckResult(Verdict.ERROR, detail="support entry not found")
    resolved = ctx.rename_map.get(entry.uri, entry.uri)
    if not (ctx.repo / resolved).resolve().is_relative_to(ctx.repo.resolve()):
        # Same containment guard as C3/C5: a hostile uri ('..' or absolute,
        # which pathlib's `/` lets replace the root) must not become an
        # existence or hash-equality oracle for files outside the repo.
        return CheckResult(Verdict.ERROR, detail="bad_program")

    current = gitio.working_file(ctx.repo, resolved)
    if current is None:
        return CheckResult(Verdict.FAIL, detail="file_gone")

    # Hash from the bytes already read (mirrors gitio.working_hash) — a second
    # disk read could race a concurrent delete and misreport file_gone as drift.
    text = current.decode("utf-8", errors="replace")
    if entry.selector is None:
        current_hash = sha256_hex(current)
    else:
        current_hash = span_hash(text, entry.selector)
    if current_hash == entry.hash:
        return CheckResult(Verdict.PASS, relocated=resolved != entry.uri)

    original = (
        gitio.span_at_ref(ctx.repo, entry.version, entry.uri, entry.selector)
        if entry.version
        else None
    )
    if original is None:
        return CheckResult(Verdict.ERROR, detail="original_unreachable")
    if sha256_hex(original.encode("utf-8")) != entry.hash:
        # The ref-resolved span is not what the claim was anchored to (e.g. a
        # dirty-tree capture, or an out-of-range selector at the ref). Matching
        # against it could yield false PASSes — a capture problem, so ERROR.
        return CheckResult(Verdict.ERROR, detail="capture_inconsistent")

    needle = original.strip()
    if needle and needle in text:
        return CheckResult(Verdict.PASS, detail="anchor_moved", relocated=True)

    if ctx.enable_c2lite and needle and _c2lite_match(original, text):
        return CheckResult(Verdict.PASS, detail="c2lite", relocated=True)

    return CheckResult(Verdict.FAIL, detail="span_changed_or_removed")


def _c2lite_match(original: str, text: str) -> bool:
    """Best same-line-count window similarity >= threshold (capped at 20k lines)."""
    lines = text.split("\n")[:_C2LITE_MAX_LINES]
    n = len(original.split("\n"))
    if n > len(lines):
        return False
    matcher = difflib.SequenceMatcher(b=original, autojunk=False)
    for i in range(len(lines) - n + 1):
        matcher.set_seq1("\n".join(lines[i : i + n]))
        if matcher.ratio() >= _C2LITE_RATIO:
            return True
    return False


registry.register("C1", check_c1)
