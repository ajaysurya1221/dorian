"""C3 referential checker: does the referenced path/symbol/string still exist?

Program grammars (the operand in `string:`/`regex:` may itself contain ':'; only
the grammar prefix and the file are split off, the remainder is the operand):
- path:<repo-relative>          PASS iff the file or directory exists.
- symbol:<file>::<name>         PASS iff \\b(def|class)\\s+<name>\\b matches the file.
- string:<file>::<literal>      PASS iff the literal substring is present.
- regex:<file>::<pattern>       PASS iff re.search(pattern, text, re.MULTILINE)
                                hits the LF-normalized file text.

`regex:` is the shape-tolerant form: prefer it over `string:` for facts that must
survive reformatting (the v0.0 false-positive class — e.g. 'TIMEOUT\\s*=\\s*30'
matches both 'TIMEOUT = 30' and 'TIMEOUT=30'). When a `string:` check FAILs but
some line of the file nearly matches the literal, the detail carries a near-miss
hint pointing at `regex:` — line number and similarity ratio only, NEVER file
content (audit export must stay content-free).

File lookups go through ctx.rename_map so renames are not alarms. Empty
operands, paths that resolve outside the repo, and invalid or oversized
(>500 chars) regex patterns are ERROR('bad_program'): a degenerate program must
never produce a vacuous PASS.

Residual regex risk: `regex:` patterns are length-bounded (500 chars) and
compile-guarded, but catastrophic backtracking WITHIN that bound is NOT
mitigated — C3 runs in-process and ignores ctx.timeout_s, so a pathological
nested-quantifier pattern (e.g. '(a+)+$') in a reviewed claims.json can stall
revalidate indefinitely. Reviewers should prefer tolerant-but-anchored
patterns (literal anchors with bounded flexible gaps, e.g. 'TIMEOUT\\s*=\\s*30')
over nested or unbounded quantifiers.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from dorian.checkers import registry
from dorian.checkers.base import CheckContext, CheckResult, Verdict, resolve_path
from dorian.model import CheckerSpec, lf_normalize

_MAX_PATTERN_LEN = 500  # cheap guard against catastrophic patterns
_NEAR_MISS_RATIO = 0.8
_NEAR_MISS_MAX_FILE_BYTES = 1 << 20  # 1 MiB: bound the per-line scan
_NEAR_MISS_MIN_LITERAL = 4  # tiny literals near-match everything


def _contained_path(ctx: CheckContext, uri: str) -> Path | None:
    """Resolve uri via rename_map; None if empty or it escapes the repo root."""
    if not uri:
        return None
    path = resolve_path(ctx, uri)
    if not path.resolve().is_relative_to(ctx.repo.resolve()):
        return None
    return path


def _near_miss(text: str, literal: str) -> tuple[int, float] | None:
    """Best (1-based line, ratio) of a line similar to the absent literal, or
    None if no line reaches the near-miss threshold."""
    matcher = difflib.SequenceMatcher(autojunk=False)
    matcher.set_seq2(literal)  # SequenceMatcher caches seq2: one literal, many lines
    best: tuple[int, float] | None = None
    for lineno, line in enumerate(text.split("\n"), start=1):
        matcher.set_seq1(line)
        if matcher.quick_ratio() < _NEAR_MISS_RATIO:
            continue  # quick_ratio() upper-bounds ratio(): identical results, cheap skip
        ratio = matcher.ratio()
        if ratio >= _NEAR_MISS_RATIO and (best is None or ratio > best[1]):
            best = (lineno, ratio)
    return best


def _string_fail(path: Path, text: str, literal: str) -> CheckResult:
    """FAIL for an absent literal; a bounded near-miss scan adds a hint with the
    line number and ratio only — NEVER file content."""
    if len(literal) < _NEAR_MISS_MIN_LITERAL or path.stat().st_size > _NEAR_MISS_MAX_FILE_BYTES:
        return CheckResult(Verdict.FAIL, detail="string_missing")
    hit = _near_miss(text, literal)
    if hit is None:
        return CheckResult(Verdict.FAIL, detail="string_missing")
    lineno, ratio = hit
    return CheckResult(
        Verdict.FAIL,
        detail=(
            f"string_missing (near-miss: line {lineno}, ratio {ratio:.2f}"
            " — literal may have changed shape; consider regex:)"
        ),
    )


def check(ctx: CheckContext, spec: CheckerSpec) -> CheckResult:
    prefix, sep, rest = spec.program.partition(":")
    if not sep or prefix not in ("path", "symbol", "string", "regex"):
        return CheckResult(Verdict.ERROR, detail="bad_program")

    if prefix == "path":
        path = _contained_path(ctx, rest)
        if path is None:
            return CheckResult(Verdict.ERROR, detail="bad_program")
        if path.exists():
            return CheckResult(Verdict.PASS)
        return CheckResult(Verdict.FAIL, detail="ref_missing")

    file, sep, needle = rest.partition("::")
    if not sep or not needle:
        return CheckResult(Verdict.ERROR, detail="bad_program")

    pattern: re.Pattern[str] | None = None
    if prefix == "regex":
        if len(needle) > _MAX_PATTERN_LEN:
            return CheckResult(Verdict.ERROR, detail="bad_program")
        try:
            pattern = re.compile(needle, re.MULTILINE)
        except re.error:
            return CheckResult(Verdict.ERROR, detail="bad_program")

    path = _contained_path(ctx, file)
    if path is None:
        return CheckResult(Verdict.ERROR, detail="bad_program")
    if not path.is_file():
        return CheckResult(Verdict.FAIL, detail="file_gone")
    text = lf_normalize(path.read_bytes()).decode("utf-8", errors="replace")

    if prefix == "symbol":
        if re.search(rf"\b(def|class)\s+{re.escape(needle)}\b", text):
            return CheckResult(Verdict.PASS)
        return CheckResult(Verdict.FAIL, detail="symbol_missing")

    if prefix == "regex":
        assert pattern is not None  # set above for every regex program
        if pattern.search(text):
            return CheckResult(Verdict.PASS)
        return CheckResult(Verdict.FAIL, detail="regex_missing")

    if needle in text:
        return CheckResult(Verdict.PASS)
    return _string_fail(path, text, needle)


registry.register("C3", check)
