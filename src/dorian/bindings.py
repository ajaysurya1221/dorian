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
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

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
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")  # a single identifier span

# Bare common words inside backticks are markup ("the `config` file", "a `list`"),
# not symbol references; binding one to a same-named one-definer symbol is a false
# BROKEN / false restricted-scope-refusal risk. snake_case / CamelCase spans are still
# admitted (real identifiers); this set blocks only bare common words.
_BACKTICK_STOPWORDS = frozenset(
    {
        "list",
        "run",
        "get",
        "set",
        "put",
        "post",
        "config",
        "class",
        "function",
        "token",
        "route",
        "handler",
    }
)

_GREP_NAMES = frozenset({"grep", "egrep", "fgrep", "rg"})


def analyze(repo: Path, artifact_uri: str) -> list[dict]:
    """Per-claim binding diagnostics for a warranted artifact, in claim order:
    {claim_id, text, watch, flags, mentions}. Flags (fixed order): 'unbacked' |
    'single-file' | 'short-literal' | 'ambiguous-mention' | 'trigger-only-symbol' |
    'unwatched-mention'. File-backed: loads the sidecar, then delegates to
    analyze_candidate (the same logic the seal-time --binding-gate runs in memory)."""
    repo = repo.resolve()
    warrant = Warrant.load(repo / (artifact_uri + ".warrant"))
    entry_uris = {e.id: e.uri for e in warrant.read_set}
    return analyze_candidate(
        repo, artifact_uri=artifact_uri, claims=list(warrant.claims), entry_uris=entry_uris
    )


def _claim_input_sidecars(artifact_uri: str) -> set[str]:
    """Likely human/agent authoring inputs for a warrant.

    These files are not evidence for the claim; scanning them would make a
    committed claims file self-referentially satisfy or weaken its own binding.
    """
    p = PurePosixPath(artifact_uri)
    out = {
        (p.parent / "claims.json").as_posix(),
        p.with_suffix(".claims.json").as_posix(),
        f"{artifact_uri}.claims.json",
    }
    return {x for x in out if x and x != "."}


def analyze_candidate(
    repo: Path,
    *,
    artifact_uri: str,
    claims: Sequence[Claim],
    entry_uris: Mapping[str, str],
) -> list[dict]:
    """The diagnostic core, over CANDIDATE data (the claims plus their read-set
    entry uris) rather than a written sidecar — so it can run at seal time, before
    any `.warrant` is dumped, for the opt-in --binding-gate. `analyze` is the
    file-backed wrapper around this. Output shape and flag set are identical."""
    from dorian import symbol_index  # lazy: symbol_index imports _tokens from here (cycle)

    repo = repo.resolve()
    claims = list(claims)
    ambiguous = symbol_index.ambiguous_symbol_mentions(repo, claims)

    claim_tokens = {c.id: _tokens(c.text) for c in claims}
    all_tokens = sorted({t for toks in claim_tokens.values() for t in toks})
    tracked = gitio.ls_files(repo) if all_tokens else []
    skip = {artifact_uri, *_claim_input_sidecars(artifact_uri)}
    hits = _scan_files(repo, tracked, all_tokens, skip=skip)

    diags: list[dict] = []
    for claim in claims:
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
        exercised = _checker_exercised_files(repo, claim, entry_uris)
        if claim.load_bearing and any(
            w not in exercised for spec in claim.checkers for w in spec.watch
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


# --- opt-in weak-binding gate policy (seal-time review only; never trust state) ----

GATE_MODES = ("off", "warn", "fail")

# 'single-file' is the EXPECTED shape of an honest one-checker C3 path/symbol/regex
# claim (the launch-train Dorian-on-Dorian warrant carries five), so it is warn-only —
# never a default seal refusal. The rest are weak-binding smells worth blocking a
# strict review gate. Weak binding is a false-CONFIDENCE risk, never proof a claim is
# false: the gate maps to the seal-refused path (exit 4), never to a claim/trust state.
HIGH_RISK_FLAGS = frozenset(
    {"unbacked", "short-literal", "ambiguous-mention", "trigger-only-symbol", "unwatched-mention"}
)


def blocking_findings(diags: list[dict]) -> list[dict]:
    """Diagnostics carrying at least one HIGH_RISK_FLAGS flag — exactly what
    --binding-gate=fail refuses on. A claim flagged only 'single-file' is never
    blocking, so honest one-checker C3 warrants still seal under `fail`."""
    return [d for d in diags if any(f in HIGH_RISK_FLAGS for f in d["flags"])]


def weak_binding_lines(diags: list[dict]) -> list[str]:
    """One deterministic line per FLAGGED claim for --binding-gate output: claim
    id, flags, watch paths, and any unwatched mention token -> paths. Content-free:
    carries repo-relative paths, claim-text tokens, flags, and claim ids only —
    never a matched line or any file content."""
    lines: list[str] = []
    for d in diags:
        if not d["flags"]:
            continue
        parts = [
            f"claim {d['claim_id']!r}",
            f"flags={','.join(d['flags'])}",
            f"watch={','.join(d['watch']) or '-'}",
        ]
        for m in d["mentions"]:
            parts.append(f"unwatched[{m['token']}]={','.join(m['unwatched_files'])}")
        lines.append(" ".join(parts))
    return lines


def _checker_named_files(claim: Claim, entry_uris: dict[str, str]) -> set[str]:
    """The files a claim's checker PROGRAMS literally name (the truth they verify),
    independent of symbol-definer watch paths added at verify time. This is the narrow,
    pre-binding-fix watch surface — the bench's ``checker_path_watcher`` ablation depends
    on it staying narrow, so C4 test-import deps are NOT added here (they live in
    ``_checker_exercised_files``)."""
    # lazy: reuse seal's canonical C3 file-operand form set and C5 path grammar
    from dorian.seal import _C3_FILE_OPERAND_FORMS, _c5_data_paths

    named: set[str] = set()
    for spec in claim.checkers:
        prefix, _, rest = spec.program.partition(":")
        if spec.type == "C1":
            uri = entry_uris.get(spec.program)
            if uri:
                named.add(uri)
        elif spec.type == "C3":
            named.add(rest.partition("::")[0] if prefix in _C3_FILE_OPERAND_FORMS else rest)
        elif spec.type == "C4" and prefix == "pytest":
            named.add(rest.partition("::")[0].strip())  # parity with seal._derive_watch
        elif spec.type == "C5":
            # typed C5 derives its data path; a shell checker derives none, so its
            # EXPLICIT watch is what it exercises (else a load-bearing shell claim
            # gets a spurious 'trigger-only-symbol' flag).
            named.update(_c5_data_paths(prefix, rest) or spec.watch)
    return {f for f in named if f}


def _checker_exercised_files(repo: Path, claim: Claim, entry_uris: dict[str, str]) -> set[str]:
    """The files a claim's checkers actually EXERCISE when they run: the checker-named
    files PLUS, for each C4 ``pytest:`` checker, the repo-local implementation files its
    test statically imports. A watch path NOT in this set is a re-check TRIGGER that no
    checker exercises — the binding fix's trigger != truth gap the 'trigger-only-symbol'
    flag surfaces. Adding C4 import-deps here keeps import-aware C4 binding from spuriously
    flagging a good behavior claim (and so from tripping --binding-gate=fail): a test
    IMPORTS and runs the files it depends on, so those widened watches are exercised."""
    from dorian import test_deps  # lazy: cycle-safe module load (cached); the cost is gated below

    exercised = _checker_named_files(claim, entry_uris)
    for spec in claim.checkers:
        test_file = test_deps._c4_test_file(spec)
        if test_file:
            exercised.update(test_deps.python_import_dependencies(repo, test_file))
    return exercised


def _backtick_binds(tok: str) -> bool:
    """A backtick span is a candidate identifier only when it is a single
    identifier-shaped token of >= _MIN_IDENT chars that is not a bare common word.
    snake_case / CamelCase spans always pass (real identifiers); markup around an
    English word ('`config`', '`token`') does not — binding it is a false-positive risk."""
    if len(tok) < _MIN_IDENT or not _IDENT_RE.match(tok):
        return False
    if _SNAKE_RE.fullmatch(tok) or _CAMEL_RE.fullmatch(tok):
        return True
    return tok.lower() not in _BACKTICK_STOPWORDS


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
        tok = m.group(1).strip()
        if _backtick_binds(tok):
            add(tok)
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
