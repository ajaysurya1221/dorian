"""Binding-quality diagnostics: surface weak or suspicious claim->file bindings.

The v0.0 benchmark's one recall miss was a claim whose checker watched file A
while the breaking commit changed file B — the claim text mentioned an
identifier that also lived in B, but the binding never covered B. `analyze`
flags that shape (plus other weak-binding smells) without auto-fixing anything;
`dorian bindings` is a diagnostic, never a gate.

Content-free invariant: findings carry repo-relative file PATHS only — never
matched lines or any other file content.
"""

from __future__ import annotations

import fnmatch
import re
import shlex
from pathlib import Path

from dorian import gitio
from dorian.model import Claim, Warrant

_MAX_FILE_BYTES = 1 << 20  # tracked files larger than 1 MiB are skipped
_MAX_CANDIDATES = 8  # candidate tokens extracted per claim (bounds scan WORK, not just report)
_MAX_TOKENS = 5  # reported mention tokens per claim
_MAX_FILES = 5  # reported unwatched files per token
_MIN_LITERAL = 6  # string:/shell-grep operands shorter than this are suspect
_SNIFF_BYTES = 8192  # null-byte binary sniff window
_GLOB_CHARS = ("*", "?", "[")  # mirrors store.claims_for_paths

_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_PATH_RE = re.compile(r"\b(?:[\w.-]+/)+[\w.-]*\.\w+\b")  # has '/' + dot-extension
_SNAKE_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b")
_CAMEL_RE = re.compile(r"\b[A-Za-z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b")
_MIN_IDENT = 4  # snake/Camel identifiers shorter than this are noise

_GREP_NAMES = frozenset({"grep", "egrep", "fgrep", "rg"})


def analyze(repo: Path, artifact_uri: str) -> list[dict]:
    """Per-claim binding diagnostics for a warranted artifact, in claim order:
    {claim_id, text, watch, flags, mentions}. Flags (fixed order): 'unbacked' |
    'single-file' | 'short-literal' | 'ambiguous-mention' | 'trigger-only-symbol' |
    'unwatched-mention'."""
    from dorian import symbol_index  # lazy: symbol_index imports _tokens from here (cycle)

    repo = repo.resolve()
    warrant = Warrant.load(repo / (artifact_uri + ".warrant"))
    entry_uris = {e.id: e.uri for e in warrant.read_set}
    ambiguous = symbol_index.ambiguous_symbol_mentions(repo, list(warrant.claims))

    claim_tokens = {c.id: _tokens(c.text) for c in warrant.claims}
    all_tokens = sorted({t for toks in claim_tokens.values() for t in toks})
    tracked = gitio.ls_files(repo) if all_tokens else []
    hits = _scan_files(repo, tracked, all_tokens, skip={artifact_uri})

    diags: list[dict] = []
    for claim in warrant.claims:
        cover = _watch_support(claim, entry_uris)
        flags: list[str] = []
        if not claim.checkers:
            flags.append("unbacked")
        elif len({w for spec in claim.checkers for w in spec.watch}) == 1:
            flags.append("single-file")
        if _short_literal(claim):
            flags.append("short-literal")
        amb = ambiguous.get(claim.id, {})
        if any(not any(_covered(f, cover) for f in files) for files in amb.values()):
            flags.append("ambiguous-mention")
        named = _checker_named_files(claim, entry_uris)
        if claim.load_bearing and any(
            w not in named for spec in claim.checkers for w in spec.watch
        ):
            flags.append("trigger-only-symbol")
        mentions: list[dict] = []
        for tok in claim_tokens[claim.id]:
            if len(mentions) == _MAX_TOKENS:
                break
            unwatched = [f for f in hits[tok] if not _covered(f, cover)][:_MAX_FILES]
            if unwatched:
                mentions.append({"token": tok, "unwatched_files": unwatched})
        if mentions:
            flags.append("unwatched-mention")
        diags.append(
            {
                "claim_id": claim.id,
                "text": claim.text,
                "watch": sorted(cover),
                "flags": flags,
                "mentions": mentions,
            }
        )
    return diags


def _checker_named_files(claim: Claim, entry_uris: dict[str, str]) -> set[str]:
    """The files a claim's checker PROGRAMS name (the truth they verify), independent of
    symbol-definer watch paths added at verify time. A watch path NOT in this set is a
    re-check TRIGGER that no checker exercises — the binding fix's trigger != truth gap,
    which the 'trigger-only-symbol' flag surfaces."""
    from dorian.seal import _c5_data_paths  # lazy: reuse the canonical C5 path grammar

    named: set[str] = set()
    for spec in claim.checkers:
        prefix, _, rest = spec.program.partition(":")
        if spec.type == "C1":
            uri = entry_uris.get(spec.program)
            if uri:
                named.add(uri)
        elif spec.type == "C3":
            named.add(rest.partition("::")[0] if prefix in ("symbol", "string", "regex") else rest)
        elif spec.type == "C4" and prefix == "pytest":
            named.add(rest.partition("::")[0])
        elif spec.type == "C5":
            named.update(_c5_data_paths(prefix, rest))
    return {f for f in named if f}


def _tokens(text: str) -> list[str]:
    """Candidate tokens from claim text, deduped in first-appearance order per
    class: backtick spans, then path-like tokens, then snake/Camel identifiers.
    Capped at the first _MAX_CANDIDATES tokens in that order: the cap bounds the
    repo scan itself, so a token-stuffed claim cannot blow up analyze()."""
    out: list[str] = []
    seen: set[str] = set()

    def add(tok: str) -> None:
        tok = tok.strip()
        if tok and tok not in seen:
            seen.add(tok)
            out.append(tok)

    for m in _BACKTICK_RE.finditer(text):
        add(m.group(1))
    for m in _PATH_RE.finditer(text):
        add(m.group(0))
    for rx in (_SNAKE_RE, _CAMEL_RE):
        for m in rx.finditer(text):
            if len(m.group(0)) >= _MIN_IDENT:
                add(m.group(0))
    return out[:_MAX_CANDIDATES]


_WORD_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")


def _combined_pattern(tokens: list[str]) -> re.Pattern[str]:
    """One alternation over all tokens, found via a zero-width lookahead so every
    start position is tested independently (overlaps cannot hide a token).
    Longest-first ordering so a short token never shadows a longer one that
    starts at the same position."""
    ordered = sorted(tokens, key=lambda t: (-len(t), t))
    alts = "|".join(re.escape(t) + r"(?![A-Za-z0-9_])" for t in ordered)
    return re.compile(r"(?<![A-Za-z0-9_])(?=(" + alts + r"))")


def _scan_files(
    repo: Path, paths: list[str], tokens: list[str], skip: set[str]
) -> dict[str, list[str]]:
    """token -> tracked files with a whole-word match, in `paths` order. Each
    file is searched ONCE with a combined alternation pattern (not once per
    token). Skips the artifact (`skip`), *.warrant sidecars, binaries
    (null-byte sniff), oversized and unreadable files. File content never
    leaves this function."""
    hits: dict[str, list[str]] = {t: [] for t in tokens}
    if not tokens:
        return hits
    combined = _combined_pattern(tokens)
    # the one residual shadow: tokens starting at the SAME position, where the
    # longer one wins the alternation — but then the shorter is a prefix of the
    # longer with a non-word boundary char, so finding B always implies A
    implied = {
        b: [a for a in tokens if a != b and b.startswith(a) and b[len(a)] not in _WORD_CHARS]
        for b in tokens
    }
    for rel in paths:
        if rel in skip or rel.endswith(".warrant"):
            continue
        p = repo / rel
        try:
            if not p.is_file() or p.stat().st_size > _MAX_FILE_BYTES:
                continue
            data = p.read_bytes()
        except OSError:
            continue  # vanished or unreadable: diagnostics never hard-fail on a file
        if b"\0" in data[:_SNIFF_BYTES]:
            continue
        text = data.decode("utf-8", errors="replace")
        found: set[str] = set()
        for m in combined.finditer(text):
            tok = m.group(1)
            if tok in found:
                continue
            found.add(tok)
            found.update(implied[tok])
            if len(found) == len(tokens):
                break
        for tok in tokens:
            if tok in found:
                hits[tok].append(rel)
    return hits


def _watch_support(claim: Claim, entry_uris: dict[str, str]) -> set[str]:
    """The claim's binding cover: checker watch paths/globs + support entry uris."""
    cover = {w for spec in claim.checkers for w in spec.watch}
    cover.update(uri for sid in claim.supports if (uri := entry_uris.get(sid)))
    return cover


def _covered(path: str, cover: set[str]) -> bool:
    if path in cover:
        return True
    return any(any(ch in pat for ch in _GLOB_CHARS) and fnmatch.fnmatch(path, pat) for pat in cover)


def _short_literal(claim: Claim) -> bool:
    """Any string:/shell-grep program whose literal/pattern operand is < 6 chars
    (over-tight or trivially matchable)."""
    for spec in claim.checkers:
        prefix, _, rest = spec.program.partition(":")
        if prefix == "string":
            _, sep, literal = rest.partition("::")
            if sep and literal and len(literal) < _MIN_LITERAL:
                return True
        elif prefix == "shell":
            pattern = _grep_pattern(rest)
            if pattern is not None and len(pattern) < _MIN_LITERAL:
                return True
    return False


def _grep_pattern(cmd: str) -> str | None:
    """The pattern operand of a shell grep command; None when the command is
    not a grep (or is unparseable — diagnostics never guess)."""
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return None
    if not tokens or Path(tokens[0]).name not in _GREP_NAMES:
        return None
    it = iter(tokens[1:])
    for tok in it:
        if tok == "--" or tok in ("-e", "--regexp"):
            return next(it, None)
        if tok.startswith("-"):
            continue
        return tok
    return None
