"""Anchor-first extraction: stage-2 determinism + protocol isolation.

Matrix:
(a) _numbered: 1-based, tab-separated, preserves empty lines
(b) _claims_from_spans: verbatim quote slicing, whitespace-collapsed text,
    canonical ids cL<a>-<b>, position sort, duplicate-span dedup, drop of
    out-of-bounds/malformed/empty spans, ValueError when nothing valid remains,
    ValueError when the spans array itself is missing
(c) determinism: the same spans payload -> byte-identical claims dict
(d) anchor.quote is an exact artifact substring (C1-compatible by construction)
(e) protocol isolation: prompt_hash("anchor") differs from the (unchanged)
    restate hash; cache paths differ by mode so modes never share entries
(f) extract_claims(mode="anchor"): numbered payload sent, emit_spans forced,
    derived claims validate, anchor cache round-trips; unknown mode raises
(g) churn --mode anchor: mode reaches extract_claims and is recorded in the
    result JSON next to the anchor prompt hash
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # bench/ is a repo-root package, not installed
    sys.path.insert(0, str(REPO_ROOT))

from bench import churn  # noqa: E402

from dorian import extract  # noqa: E402
from dorian.model import Claim  # noqa: E402

DOC = "# Title\nThe timeout is 30 seconds.\nLogin is at /v1/login.\n  spaced   out  \n"

# --- (a) numbering ----------------------------------------------------------------


def test_numbered_is_one_based_tab_separated() -> None:
    assert extract._numbered("a\n\nb") == "1\ta\n2\t\n3\tb"


# --- (b)/(c)/(d) deterministic stage 2 --------------------------------------------


def _spans(*triples: tuple[int, int, str]) -> dict:
    return {
        "spans": [
            {"line_start": a, "line_end": b, "kind": kind, "load_bearing": False}
            for a, b, kind in triples
        ]
    }


def test_claims_from_spans_slices_dedups_sorts_and_drops() -> None:
    data = _spans(
        (3, 3, "reference"),
        (2, 2, "quantity"),
        (2, 2, "quantity"),  # duplicate span -> one claim
        (99, 99, "fact"),  # out of bounds -> dropped
        (0, 1, "fact"),  # 0 is not a valid 1-based line -> dropped
        (3, 2, "fact"),  # inverted range -> dropped
        (5, 5, "fact"),  # the trailing empty line -> empty text -> dropped
        (4, 4, "fact"),  # whitespace-collapsed text
    )
    got = extract._claims_from_spans(data, DOC)["claims"]
    assert [c["id"] for c in got] == ["cL2-2", "cL3-3", "cL4-4"]  # position-sorted
    assert got[0]["text"] == "The timeout is 30 seconds."
    assert got[2]["text"] == "spaced out"  # collapsed for matching...
    assert got[2]["anchor"]["quote"] == "  spaced   out  "  # ...quote stays verbatim
    for claim in got:
        assert claim["anchor"]["quote"] in DOC  # (d) exact substring by construction
        assert claim["supports"] == [] and claim["checkers"] == []


def test_claims_from_spans_multiline_and_malformed() -> None:
    got = extract._claims_from_spans(_spans((2, 3, "fact")), DOC)["claims"]
    assert got[0]["id"] == "cL2-3"
    assert got[0]["text"] == "The timeout is 30 seconds. Login is at /v1/login."
    assert got[0]["anchor"]["quote"] == "The timeout is 30 seconds.\nLogin is at /v1/login."

    with pytest.raises(ValueError, match="no valid spans"):
        extract._claims_from_spans(_spans((50, 60, "fact")), DOC)
    with pytest.raises(ValueError, match="no spans array"):
        extract._claims_from_spans({"claims": []}, DOC)
    # structurally malformed entries are dropped — never coerced — valid ones survive
    ok = _spans((3, 3, "fact"))["spans"][0]
    data = {
        "spans": [
            {"line_start": 2},  # missing fields
            "junk",  # not an object
            dict(ok, line_start=2.7, line_end=3),  # float line -> dropped, not truncated
            dict(ok, line_start=True, line_end=1),  # bool is not a line number
            dict(ok, load_bearing="false"),  # truthy string is not a bool
            dict(ok, kind="opinion"),  # unknown kind -> dropped, not failed
            ok,
        ]
    }
    assert [c["id"] for c in extract._claims_from_spans(data, DOC)["claims"]] == ["cL3-3"]


def test_claims_from_spans_is_deterministic() -> None:
    data = _spans((2, 2, "quantity"), (3, 3, "reference"))
    first = json.dumps(extract._claims_from_spans(data, DOC), sort_keys=True)
    second = json.dumps(extract._claims_from_spans(data, DOC), sort_keys=True)
    assert first == second


# --- (e) protocol isolation -------------------------------------------------------


def test_mode_hashes_and_cache_paths_are_isolated(tmp_path: Path) -> None:
    assert extract.prompt_hash() == extract.prompt_hash("restate")  # default unchanged
    # pinned: editing PROMPT_V0/CLAIMS_TOOL invalidates every cache entry and
    # re-identifies all historical churn baselines — that must be deliberate
    assert extract.prompt_hash("restate").startswith("8bfff1ff98d8")
    assert extract.prompt_hash("anchor") != extract.prompt_hash("restate")
    # 3-arg legacy call == explicit restate; anchor never shares a cache file
    assert extract._cache_path(tmp_path, "sha256:x", "m") == extract._cache_path(
        tmp_path, "sha256:x", "m", "restate"
    )
    assert extract._cache_path(tmp_path, "sha256:x", "m", "anchor") != extract._cache_path(
        tmp_path, "sha256:x", "m", "restate"
    )


# --- (f) end-to-end anchor extraction against a fake SDK --------------------------


def _install_fake_anthropic(monkeypatch: pytest.MonkeyPatch, spans: dict) -> list[dict]:
    calls: list[dict] = []

    class _Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            block = types.SimpleNamespace(type="tool_use", name="emit_spans", input=spans)
            return types.SimpleNamespace(content=[block], stop_reason="tool_use")

    class _Anthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return calls


def test_extract_claims_anchor_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    calls = _install_fake_anthropic(monkeypatch, _spans((2, 2, "quantity")))

    kwargs = {"model": "m", "cache_dir": tmp_path, "artifact_hash": "sha256:x"}
    got = extract.extract_claims(DOC, mode="anchor", **kwargs)
    assert [c.id for c in got] == ["cL2-2"]
    assert got[0].text == "The timeout is 30 seconds."
    assert got[0].anchor is not None and got[0].anchor.quote in DOC

    sent = calls[0]
    assert sent["system"] == extract.ANCHOR_PROMPT_V0
    assert sent["tool_choice"] == {"type": "tool", "name": "emit_spans"}
    assert sent["messages"][0]["content"].startswith("1\t# Title")  # numbered payload

    # anchor cache round-trip: second call is served from cache, no new API call
    again = extract.extract_claims(DOC, mode="anchor", **kwargs)
    assert len(calls) == 1
    assert [c.id for c in again] == ["cL2-2"]

    with pytest.raises(ValueError, match="unknown extraction mode"):
        extract.extract_claims(DOC, mode="verbatim", **kwargs)


# --- (g) churn --mode passthrough -------------------------------------------------


def test_churn_mode_passthrough_and_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    seen: list[str] = []

    def fake_extract(
        text, *, model, cache_dir, artifact_hash, use_cache=True, temperature=0.0, mode="restate"
    ):
        seen.append(mode)
        return [
            Claim(id="cL2-2", text="The timeout is 30 seconds.", kind="fact", load_bearing=False)
        ]

    monkeypatch.setattr(extract, "extract_claims", fake_extract)
    doc = tmp_path / "doc.md"
    doc.write_text(DOC, encoding="utf-8")
    out = tmp_path / "churn.json"
    rc = churn.main(["--doc", str(doc), "--mode", "anchor", "--out", str(out)])
    assert rc == 0  # identical runs -> zero churn -> PASS
    assert seen == ["anchor"] * 3
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["mode"] == "anchor"
    assert record["prompt_hash"] == extract.prompt_hash("anchor")
