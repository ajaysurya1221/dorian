"""LLM claim extraction (optional `extract` extra) with a deterministic stub mode.

If DORIAN_EXTRACT_STUB is set, it names a claims.json loaded via claims_io —
offline determinism for tests/bench. Otherwise a single Anthropic messages.create
call with the fixed PROMPT_V0 system prompt FORCES the emit_claims tool
(tool_choice), so the API returns schema-validated structured input instead of
free text — there is no JSON string parsing to go wrong. A response stopped at
max_tokens is a clear truncation error, never a parse error. Results are cached
under cache_dir keyed by artifact hash, model, and the extraction-protocol hash
(prompt + tool schema); the cache is consulted before the API call (and before
the anthropic import, so cached extractions work without the package). A corrupt
cache entry is deleted and re-extracted rather than raising. use_cache=False
skips both the cache read and the cache write (bench.churn re-run measurement);
temperature is passed explicitly to the SDK call (default 0.0).

Adaptive degradation (e.g. claude-fable-5 rejects both): a 400 "`temperature`
is deprecated for this model" drops temperature; a 400 "tool_choice forces tool
use is not compatible with this model" falls back to tool_choice auto (the
system prompt still demands the tool call; multiple tool calls in one auto
response are merged). Each degradation retries once and is remembered for
the process — queryable via temperature_unsupported() / forced_tools_unsupported()
so measurements record what was actually sent.

Three extraction modes (mode=):
- "restate" (default, the original protocol): the model authors each claim's
  text as an atomic restatement.
- "anchor" (anchor-first): the model only selects 1-based line spans via the
  emit_spans tool; _claims_from_spans then derives text, anchor, and id from
  the artifact deterministically. The model never authors identity-bearing
  text, so claim wording cannot churn — only span selection can. Modes hash to
  different extraction protocols (prompt_hash(mode)) and never share cache
  entries; the restate protocol hash is unchanged.
- "candidate" (candidate-first; pre-registered challenger in
  docs/REAL_DOC_METAMORPHIC_GATE.md): segment_candidates() splits the
  artifact into candidate blocks deterministically and the model only
  classifies which candidates state checkable claims via emit_candidates.
  Boundaries are fixed by the segmentation — boundary jitter is impossible
  by construction — and selection reduces to a per-candidate vote.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

from dorian import claims_io
from dorian.model import Claim, canonical_json

PROMPT_V0 = """\
You extract verifiable claims from an AI-generated artifact.
You MUST call the emit_claims tool with the claims you extract — never answer
in prose. Claim ids are "c<N>".
Each claim must be a single checkable statement grounded in the artifact text,
restated atomically. anchor quotes an exact artifact substring (or null).
Leave supports and checkers empty — binding happens at seal time.
Mark load_bearing true only when the artifact's conclusions depend on the claim.
"""

# anchor-first mode: the model only SELECTS line spans — it never authors claim
# text. Stage 2 (_claims_from_spans) derives text/anchor/id deterministically
# from the artifact, so re-runs that select the same spans produce byte-identical
# claims. Measured motivation: v0.3.0 churn showed claim *selection* is stable
# across re-runs while model-authored *wording* is not.
ANCHOR_PROMPT_V0 = """\
You select the line spans of an AI-generated artifact that state verifiable
claims. The artifact is shown with 1-based line numbers as "N<TAB>content".
You MUST call the emit_spans tool with the spans you select — never answer in
prose. For each checkable claim give the smallest line range that states it;
one span states ONE atomic claim. Do not write claim text — text is derived
from the artifact lines. Skip unverifiable prose (opinions, headings,
boilerplate).
Mark load_bearing true only when the artifact's conclusions depend on the claim.
"""

CLAIMS_TOOL = {
    "name": "emit_claims",
    "description": "Record the verifiable claims extracted from the artifact.",
    "input_schema": {
        "type": "object",
        "required": ["claims"],
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "text", "kind", "load_bearing"],
                    "properties": {
                        "id": {"type": "string"},
                        "text": {"type": "string"},
                        "kind": {"enum": ["fact", "reference", "behavior", "quantity", "decision"]},
                        "load_bearing": {"type": "boolean"},
                        "anchor": {
                            "type": ["object", "null"],
                            "properties": {
                                "line_start": {"type": "integer"},
                                "line_end": {"type": "integer"},
                                "quote": {"type": "string"},
                            },
                        },
                        "supports": {"type": "array", "items": {"type": "string"}},
                        "checkers": {"type": "array"},
                    },
                },
            }
        },
    },
}

# candidate-first mode: segmentation happens in code; the model only says
# WHICH pre-cut candidate blocks state checkable claims. It cannot move a
# boundary and it never authors text, so the only degree of freedom left —
# and the only thing that can churn — is the per-candidate yes/no.
CANDIDATE_PROMPT_V0 = """\
You classify pre-segmented candidate blocks of an AI-generated artifact.
Each candidate is shown as "b<INDEX> [lines A-B]" followed by its exact text.
You MUST call the emit_candidates tool with your selections — never answer in
prose. Select exactly the candidates that state verifiable claims, by index;
skip unverifiable prose (opinions, transitions, headings, boilerplate). You
cannot change candidate boundaries and you never write claim text — text is
derived from the artifact lines.
Mark load_bearing true only when the artifact's conclusions depend on the claim.
"""

CANDIDATES_TOOL = {
    "name": "emit_candidates",
    "description": "Record the candidate blocks that state verifiable claims.",
    "input_schema": {
        "type": "object",
        "required": ["candidates"],
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["index", "kind", "load_bearing"],
                    "properties": {
                        "index": {"type": "integer"},
                        "kind": {"enum": ["fact", "reference", "behavior", "quantity", "decision"]},
                        "load_bearing": {"type": "boolean"},
                    },
                },
            }
        },
    },
}

SPANS_TOOL = {
    "name": "emit_spans",
    "description": "Record the artifact line spans that state verifiable claims.",
    "input_schema": {
        "type": "object",
        "required": ["spans"],
        "properties": {
            "spans": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["line_start", "line_end", "kind", "load_bearing"],
                    "properties": {
                        "line_start": {"type": "integer"},
                        "line_end": {"type": "integer"},
                        "kind": {"enum": ["fact", "reference", "behavior", "quantity", "decision"]},
                        "load_bearing": {"type": "boolean"},
                    },
                },
            }
        },
    },
}

# mode -> (system prompt, forced tool, tool's payload array key)
_MODE_PROTOCOLS = {
    "restate": (PROMPT_V0, CLAIMS_TOOL, "claims"),
    "anchor": (ANCHOR_PROMPT_V0, SPANS_TOOL, "spans"),
    "candidate": (CANDIDATE_PROMPT_V0, CANDIDATES_TOOL, "candidates"),
}

_MAX_TOKENS = 8192


def _numbered(text: str) -> str:
    """1-based, tab-separated line numbering — the span-selection input format."""
    return "\n".join(f"{i}\t{line}" for i, line in enumerate(text.split("\n"), start=1))


# a line that opens a list item or table row starts its own candidate block
_LIST_START_RE = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|\|)")
_CANDIDATE_MAX_LINES = 6


def segment_candidates(text: str) -> list[tuple[int, int]]:
    """Deterministic candidate segmentation: maximal runs of content lines
    (non-blank, non-heading, non-rule, non-fence-marker), where every list
    item or table row starts its own block and blocks cap at
    _CANDIDATE_MAX_LINES. Pure code — the same text always yields the same
    1-based inclusive blocks."""
    blocks: list[tuple[int, int]] = []
    current: list[int] = []

    def flush() -> None:
        if current:
            blocks.append((current[0], current[-1]))
            current.clear()

    for j, line in enumerate(text.split("\n"), start=1):
        if _TRIM_RE.match(line):
            flush()
            continue
        if _LIST_START_RE.match(line) or len(current) >= _CANDIDATE_MAX_LINES:
            flush()
        current.append(j)
    flush()
    return blocks


def _render_candidates(text: str, candidates: list[tuple[int, int]]) -> str:
    """The candidate-classification input format: indexed blocks with their
    exact artifact lines."""
    lines = text.split("\n")
    parts: list[str] = []
    for i, (a, b) in enumerate(candidates):
        parts.append(f"b{i} [lines {a}-{b}]")
        parts.extend(lines[a - 1 : b])
        parts.append("")
    return "\n".join(parts)


# non-content lines trimmed from span edges: blank, markdown heading,
# horizontal rule, code-fence marker — none of them carry claim content, and
# off-by-one span edges that include them are pure boundary jitter
_TRIM_RE = re.compile(r"^(\s*|#{1,6}\s.*|\s*-{3,}\s*|\s*={3,}\s*|\s*```.*)$")


def _snap_span(lines: list[str], a: int, b: int) -> tuple[int, int] | None:
    """Deterministic boundary snapping: trim non-content edge lines from the
    1-based inclusive span [a, b]; None when nothing remains."""
    while a <= b and _TRIM_RE.match(lines[a - 1]):
        a += 1
    while b >= a and _TRIM_RE.match(lines[b - 1]):
        b -= 1
    return (a, b) if a <= b else None


def _claims_from_spans(data: dict, artifact_text: str) -> dict:
    """Deterministic stage 2 of anchor-first extraction: slice claim text out of
    the artifact by the model's line spans. Ids canonicalize from the SNAPPED
    span position (cL<start>-<end>, after _snap_span trims non-content edge
    lines), anchor.quote is the verbatim artifact slice, text is the quote with
    whitespace collapsed. Malformed spans are dropped, never guessed (non-int
    lines, bools, non-bool load_bearing, unknown kind, out-of-bounds or
    inverted ranges, empty text); spans identical after snapping collapse to
    one claim."""
    spans = data.get("spans") if isinstance(data, dict) else None
    if not isinstance(spans, list):
        raise ValueError("anchor extraction returned no spans array")
    lines = artifact_text.split("\n")
    claims: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for raw in spans:
        if not isinstance(raw, dict):
            continue
        a, b = raw.get("line_start"), raw.get("line_end")
        kind, load_bearing = raw.get("kind"), raw.get("load_bearing")
        # drop, never guess: ints only (bool is an int subclass — reject), real
        # bools only, known kinds only (reachable under the tool_choice=auto
        # fallback, where the tool schema is not enforced)
        if (
            not isinstance(a, int)
            or not isinstance(b, int)
            or isinstance(a, bool)
            or isinstance(b, bool)
            or not isinstance(load_bearing, bool)
            or kind not in claims_io.VALID_KINDS
        ):
            continue
        if not (1 <= a <= b <= len(lines)):
            continue
        snapped = _snap_span(lines, a, b)
        if snapped is None:
            continue
        a, b = snapped
        if (a, b) in seen:
            continue
        quote = "\n".join(lines[a - 1 : b])
        text = " ".join(quote.split())
        if not text:
            continue
        seen.add((a, b))
        claims.append(
            {
                "id": f"cL{a}-{b}",
                "text": text,
                "kind": kind,
                "load_bearing": load_bearing,
                "anchor": {"line_start": a, "line_end": b, "quote": quote},
                "supports": [],
                "checkers": [],
            }
        )
    if not claims:
        raise ValueError("anchor extraction yielded no valid spans")
    claims.sort(key=lambda c: (c["anchor"]["line_start"], c["anchor"]["line_end"]))
    return {"claims": claims}


def _claims_from_candidates(
    data: dict, artifact_text: str, candidates: list[tuple[int, int]]
) -> dict:
    """Deterministic stage 2 of candidate-first extraction: selected candidate
    indexes become spans, then _claims_from_spans derives text/anchor/id.
    Malformed selections are dropped, never guessed (non-int or bool indexes,
    out-of-range indexes, non-bool load_bearing, unknown kinds); duplicate
    selections collapse."""
    chosen = data.get("candidates") if isinstance(data, dict) else None
    if not isinstance(chosen, list):
        raise ValueError("candidate extraction returned no candidates array")
    spans: list[dict] = []
    for raw in chosen:
        if not isinstance(raw, dict):
            continue
        idx, kind, load_bearing = raw.get("index"), raw.get("kind"), raw.get("load_bearing")
        if (
            not isinstance(idx, int)
            or isinstance(idx, bool)
            or not 0 <= idx < len(candidates)
            or not isinstance(load_bearing, bool)
            or kind not in claims_io.VALID_KINDS
        ):
            continue
        a, b = candidates[idx]
        spans.append({"line_start": a, "line_end": b, "kind": kind, "load_bearing": load_bearing})
    if not spans:
        raise ValueError("candidate extraction yielded no valid selections")
    return _claims_from_spans({"spans": spans}, artifact_text)


class ExtractUnavailable(RuntimeError):
    """The anthropic package is not installed (extraction is an optional extra)."""


# models this process saw reject the temperature parameter (API 400 "deprecated")
_TEMP_UNSUPPORTED: set[str] = set()

# models this process saw reject FORCED tool_choice (API 400 "tool_choice forces
# tool use is not compatible with this model"); they fall back to tool_choice auto
_FORCED_TOOLS_UNSUPPORTED: set[str] = set()


def temperature_unsupported(model: str) -> bool:
    """True if this process saw `model` reject the temperature parameter."""
    return model in _TEMP_UNSUPPORTED


def forced_tools_unsupported(model: str) -> bool:
    """True if this process saw `model` reject forced tool_choice (auto was used)."""
    return model in _FORCED_TOOLS_UNSUPPORTED


def _temperature_deprecated(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "temperature" in msg and "deprecat" in msg


def _forced_tools_rejected(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "tool_choice" in msg and ("not compatible" in msg or "forces tool use" in msg)


def prompt_hash(mode: str = "restate") -> str:
    """Full sha256 hex of the extraction protocol — system prompt + tool schema
    for the given mode (the cache filename keeps the 12-char short form). Either
    changing invalidates cached extractions and re-identifies churn measurements;
    the restate value is unchanged from the pre-anchor protocol."""
    system, tool, _ = _MODE_PROTOCOLS[mode]
    return hashlib.sha256(system.encode("utf-8") + b"\n" + canonical_json(tool)).hexdigest()


def _cache_path(cache_dir: Path, artifact_hash: str, model: str, mode: str = "restate") -> Path:
    return cache_dir / f"{artifact_hash}-{model}-{prompt_hash(mode)[:12]}.json"


def extract_claims(
    artifact_text: str,
    *,
    model: str,
    cache_dir: Path,
    artifact_hash: str,
    use_cache: bool = True,
    temperature: float = 0.0,
    mode: str = "restate",
) -> list[Claim]:
    if mode not in _MODE_PROTOCOLS:
        raise ValueError(f"unknown extraction mode {mode!r} (choose restate|anchor|candidate)")
    stub = os.environ.get("DORIAN_EXTRACT_STUB")
    if stub:
        return claims_io.load_claims(Path(stub))

    cache = _cache_path(cache_dir, artifact_hash, model, mode)
    if use_cache and cache.is_file():
        try:
            return claims_io.claims_from_dict(json.loads(cache.read_text(encoding="utf-8")))
        except ValueError:  # corrupt/stale cache entry: drop it and re-extract
            cache.unlink()

    try:
        import anthropic
    except ImportError:
        raise ExtractUnavailable("pip install dorian-vwp[extract]") from None

    system, tool, payload_key = _MODE_PROTOCOLS[mode]
    candidates = segment_candidates(artifact_text) if mode == "candidate" else []
    if mode == "anchor":
        content = _numbered(artifact_text)
    elif mode == "candidate":
        content = _render_candidates(artifact_text, candidates)
    else:
        content = artifact_text
    client = anthropic.Anthropic()
    kwargs: dict = {
        "model": model,
        "max_tokens": _MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": content}],
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": tool["name"]},
    }
    if model in _FORCED_TOOLS_UNSUPPORTED:
        kwargs["tool_choice"] = {"type": "auto"}
    if temperature is not None and model not in _TEMP_UNSUPPORTED:
        kwargs["temperature"] = temperature

    # adaptive degradation: a model may reject temperature AND forced tool_choice
    # (e.g. claude-fable-5 rejects both) — drop exactly the rejected parameter and
    # retry, at most once per known degradation, remembering for this process so
    # re-runs (bench.churn) skip the bad calls
    for _ in range(3):
        try:
            msg = client.messages.create(**kwargs)
            break
        except Exception as exc:
            if "temperature" in kwargs and _temperature_deprecated(exc):
                _TEMP_UNSUPPORTED.add(model)
                del kwargs["temperature"]
            elif kwargs["tool_choice"]["type"] == "tool" and _forced_tools_rejected(exc):
                _FORCED_TOOLS_UNSUPPORTED.add(model)
                kwargs["tool_choice"] = {"type": "auto"}
            else:
                raise
    if getattr(msg, "stop_reason", None) == "max_tokens":
        raise ValueError(
            f"extraction truncated at max_tokens={_MAX_TOKENS}: "
            "the artifact is too large for one extraction — split it"
        )
    # under forced tool_choice there is exactly one tool block; under the auto
    # fallback the model may chunk the payload across several calls — merge
    blocks = [
        b.input
        for b in msg.content
        if getattr(b, "type", None) == "tool_use" and getattr(b, "name", "") == tool["name"]
    ]
    if not blocks:
        raise ValueError(f"extraction returned no {tool['name']} tool call")
    data = blocks[0]
    for extra in blocks[1:]:
        if isinstance(extra, dict) and isinstance(extra.get(payload_key), list):
            data[payload_key] = list(data.get(payload_key, [])) + extra[payload_key]
    if mode == "anchor":
        data = _claims_from_spans(data, artifact_text)
    elif mode == "candidate":
        data = _claims_from_candidates(data, artifact_text, candidates)
    claims = claims_io.claims_from_dict(data)  # validate before caching
    if use_cache:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return claims


def extract_claims_consensus(
    artifact_text: str,
    *,
    k: int = 3,
    model: str,
    cache_dir: Path,
    artifact_hash: str,
    temperature: float = 0.0,
    mode: str = "anchor",
) -> list[Claim]:
    """Consensus-of-k extraction: k independent selections, then a
    deterministic majority vote. Anchor mode votes per document line: a line
    is selected iff covered by a strict majority (k//2 + 1) of runs, and
    adjacent selected lines stay one claim only if a majority of runs spanned
    them together. Candidate mode votes per candidate block (the segmentation
    is identical across runs, so spans align exactly and never merge).
    kind/load_bearing by majority with deterministic tie-breaks
    (lexicographically smallest kind; load_bearing ties resolve to False).
    The component runs always bypass the cache (identical cached runs would
    make voting meaningless) and the result is not cached. Voting needs line
    identity, so restate mode is not supported."""
    if mode not in ("anchor", "candidate"):
        raise ValueError("consensus supports modes anchor|candidate only")
    if k < 2:
        raise ValueError("consensus k must be >= 2 (a single run has nothing to vote on)")
    majority = k // 2 + 1
    runs = [
        extract_claims(
            artifact_text,
            model=model,
            cache_dir=cache_dir,
            artifact_hash=artifact_hash,
            use_cache=False,
            temperature=temperature,
            mode=mode,
        )
        for _ in range(k)
    ]

    if mode == "candidate":
        span_votes: Counter[tuple[int, int]] = Counter()
        span_meta: dict[tuple[int, int], list[tuple[str, bool]]] = {}
        for claims in runs:
            seen_spans: set[tuple[int, int]] = set()
            for c in claims:
                assert c.anchor is not None  # candidate mode derives anchors by construction
                key = (c.anchor.line_start, c.anchor.line_end)
                if key in seen_spans:
                    continue
                seen_spans.add(key)
                span_votes[key] += 1
                span_meta.setdefault(key, []).append((c.kind, c.load_bearing))
        data: dict = {"spans": []}
        for a, b in sorted(key for key, votes in span_votes.items() if votes >= majority):
            votes = span_meta[(a, b)]
            kind_counts = Counter(kind for kind, _ in votes)
            top = max(kind_counts.values())
            kind = sorted(k_ for k_, v in kind_counts.items() if v == top)[0]
            load_bearing = sum(1 for _, lb in votes if lb) * 2 > len(votes)
            data["spans"].append(
                {"line_start": a, "line_end": b, "kind": kind, "load_bearing": load_bearing}
            )
        return claims_io.claims_from_dict(_claims_from_spans(data, artifact_text))

    line_votes: Counter[int] = Counter()
    pair_votes: Counter[tuple[int, int]] = Counter()
    meta_votes: dict[int, list[tuple[str, bool]]] = {}
    for claims in runs:
        covered: set[int] = set()
        adjacent: set[tuple[int, int]] = set()
        for c in claims:
            assert c.anchor is not None  # anchor mode produces anchors by construction
            a, b = c.anchor.line_start, c.anchor.line_end
            for ln in range(a, b + 1):
                covered.add(ln)
                meta_votes.setdefault(ln, []).append((c.kind, c.load_bearing))
            for ln in range(a, b):
                adjacent.add((ln, ln + 1))
        for ln in covered:
            line_votes[ln] += 1
        for pair in adjacent:
            pair_votes[pair] += 1

    consensus = sorted(ln for ln, votes in line_votes.items() if votes >= majority)
    spans: list[list[int]] = []
    for ln in consensus:
        if spans and ln == spans[-1][1] + 1 and pair_votes[(ln - 1, ln)] >= majority:
            spans[-1][1] = ln
        else:
            spans.append([ln, ln])

    data: dict = {"spans": []}
    for a, b in spans:
        votes = [m for ln in range(a, b + 1) for m in meta_votes.get(ln, [])]
        kind_counts = Counter(kind for kind, _ in votes)
        top = max(kind_counts.values())
        kind = sorted(k_ for k_, v in kind_counts.items() if v == top)[0]
        load_bearing = sum(1 for _, lb in votes if lb) * 2 > len(votes)
        data["spans"].append(
            {"line_start": a, "line_end": b, "kind": kind, "load_bearing": load_bearing}
        )
    return claims_io.claims_from_dict(_claims_from_spans(data, artifact_text))
