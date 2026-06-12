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
system prompt still demands the tool call; multiple emit_claims calls in one
auto response are merged). Each degradation retries once and is remembered for
the process — queryable via temperature_unsupported() / forced_tools_unsupported()
so measurements record what was actually sent.
"""

from __future__ import annotations

import hashlib
import json
import os
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

_MAX_TOKENS = 8192


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


def prompt_hash() -> str:
    """Full sha256 hex of the extraction protocol — system prompt + tool schema —
    (the cache filename keeps the 12-char short form). Either changing invalidates
    cached extractions and re-identifies churn measurements."""
    return hashlib.sha256(
        PROMPT_V0.encode("utf-8") + b"\n" + canonical_json(CLAIMS_TOOL)
    ).hexdigest()


def _cache_path(cache_dir: Path, artifact_hash: str, model: str) -> Path:
    return cache_dir / f"{artifact_hash}-{model}-{prompt_hash()[:12]}.json"


def extract_claims(
    artifact_text: str,
    *,
    model: str,
    cache_dir: Path,
    artifact_hash: str,
    use_cache: bool = True,
    temperature: float = 0.0,
) -> list[Claim]:
    stub = os.environ.get("DORIAN_EXTRACT_STUB")
    if stub:
        return claims_io.load_claims(Path(stub))

    cache = _cache_path(cache_dir, artifact_hash, model)
    if use_cache and cache.is_file():
        try:
            return claims_io.claims_from_dict(json.loads(cache.read_text(encoding="utf-8")))
        except ValueError:  # corrupt/stale cache entry: drop it and re-extract
            cache.unlink()

    try:
        import anthropic
    except ImportError:
        raise ExtractUnavailable("pip install dorian-vwp[extract]") from None

    client = anthropic.Anthropic()
    kwargs: dict = {
        "model": model,
        "max_tokens": _MAX_TOKENS,
        "system": PROMPT_V0,
        "messages": [{"role": "user", "content": artifact_text}],
        "tools": [CLAIMS_TOOL],
        "tool_choice": {"type": "tool", "name": "emit_claims"},
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
    # fallback the model may chunk claims across several emit_claims calls — merge
    blocks = [
        b.input
        for b in msg.content
        if getattr(b, "type", None) == "tool_use" and getattr(b, "name", "") == "emit_claims"
    ]
    if not blocks:
        raise ValueError("extraction returned no emit_claims tool call")
    data = blocks[0]
    for extra in blocks[1:]:
        if isinstance(extra, dict) and isinstance(extra.get("claims"), list):
            data["claims"] = list(data.get("claims", [])) + extra["claims"]
    claims = claims_io.claims_from_dict(data)  # validate before caching
    if use_cache:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return claims
