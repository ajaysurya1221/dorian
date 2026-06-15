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

Regex DoS mitigation: `regex:` patterns are length-bounded (500 chars) and
compile-guarded, AND the match itself runs in a spawned worker process under a
hard wall-clock timeout (the checker's spec.timeout_s, default 30s). A
catastrophic-backtracking pattern (e.g. '(a+)+$' against a non-matching tail) is
killed when the timeout elapses and reported as ERROR('regex_timeout') — never a
silent stall and never a PASS/FAIL. The process boundary is what makes the
timeout enforceable: a thread or in-process signal cannot interrupt a C-level
re.search(). Reviewers should still prefer tolerant-but-anchored patterns
(literal anchors with bounded flexible gaps, e.g. 'TIMEOUT\\s*=\\s*30') over
nested or unbounded quantifiers; the timeout is a backstop, not a license.
Residual: the per-check process spawn adds latency (roughly 50-150ms per `regex:`
check on spawn platforms, scaling with the number of regex checks in a run) to
`regex:` checks only; non-regex C3 forms are unaffected and stay fully in-process.
"""

from __future__ import annotations

import difflib
import multiprocessing
import re
from pathlib import Path

from dorian._regex_worker import MATCH, NO_MATCH, WORKER_ERROR, search_worker
from dorian.checkers import registry
from dorian.checkers.base import CheckContext, CheckResult, Verdict, resolve_path
from dorian.model import CheckerSpec, lf_normalize

_MAX_PATTERN_LEN = 500  # cheap guard against catastrophic patterns
_NEAR_MISS_RATIO = 0.8
_NEAR_MISS_MAX_FILE_BYTES = 1 << 20  # 1 MiB: bound the per-line scan
_NEAR_MISS_MIN_LITERAL = 4  # tiny literals near-match everything
_REGEX_TERM_GRACE_S = 1.0  # SIGTERM grace before SIGKILL on a runaway match


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


def _search_with_timeout(needle: str, flags: int, text: str, timeout_s: int) -> str:
    """Run re.search in a spawned worker killed after timeout_s. Returns one of
    'match' | 'nomatch' | 'timeout' | 'worker_error' | 'spawn_error'. The worker
    is the ONLY way to bound catastrophic backtracking: the OS can kill a process
    mid-match, where a thread or signal cannot interrupt a C-level re.search().

    The three non-result outcomes are kept distinct so a real timeout is not
    confused with an environment failure: 'timeout' = we killed a still-running
    match; 'worker_error' = the worker caught an exception (pre-compiled, so rare);
    'spawn_error' = the child exited without ever setting a result (a bootstrap/
    spawn failure, e.g. an embedder without a spawn-safe __main__ guard)."""
    mp = multiprocessing.get_context("spawn")
    result = mp.Value("b", -1)  # -1 survives iff the worker never set it
    proc = mp.Process(target=search_worker, args=(needle, flags, text, result), daemon=True)
    proc.start()
    proc.join(timeout_s)
    if proc.is_alive():
        proc.terminate()  # SIGTERM: kills a backtracking match the GIL can't stop
        proc.join(_REGEX_TERM_GRACE_S)
        if proc.is_alive():
            proc.kill()  # escalate if SIGTERM was ignored
            proc.join()
        return "timeout"
    if result.value == MATCH:
        return "match"
    if result.value == NO_MATCH:
        return "nomatch"
    if result.value == WORKER_ERROR:
        return "worker_error"
    return "spawn_error"  # value still -1: the worker bootstrap never ran search


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
        assert pattern is not None  # compiled above to validate before we spawn
        status = _search_with_timeout(needle, re.MULTILINE, text, spec.timeout_s)
        if status == "match":
            return CheckResult(Verdict.PASS)
        if status == "nomatch":
            return CheckResult(Verdict.FAIL, detail="regex_missing")
        if status == "timeout":
            return CheckResult(
                Verdict.ERROR,
                detail=f"regex_timeout (>{spec.timeout_s}s — catastrophic backtracking?)",
            )
        if status == "spawn_error":
            return CheckResult(
                Verdict.ERROR,
                detail="regex_spawn_error (regex worker process failed to start;"
                " an embedder needs a spawn-safe __main__ guard)",
            )
        return CheckResult(Verdict.ERROR, detail="regex_error")

    if needle in text:
        return CheckResult(Verdict.PASS)
    return _string_fail(path, text, needle)


registry.register("C3", check)
