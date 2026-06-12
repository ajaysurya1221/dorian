"""bench.churn (extraction-churn measurement) + extract cache-bypass acceptance tests.

Matrix:
normalization / distance math (hand-computed):
(a) normalize: lowercase, backtick/asterisk/quote strip, whitespace collapse,
    trailing-period strip
(b) exact_distance: empty/identical/disjoint/partial/one-empty sets
(c) fuzzy_distance: empty/identical/dissimilar; near-miss ratio exactly AT thr
    matches (>=), just below does not; greedy match consumes each B item once
end-to-end (churn.main):
(d) stub mode: 3 identical runs -> exact_mean 0.0, pass true, exit 0; JSON
    records prompt_hash (full sha256) and the doc BASENAME only (no path leak)
(e) varying extractions (monkeypatched extract_claims) -> known Jaccard values,
    exit 3 above the 0.20 gate
(f) missing doc / extractor unavailable -> exit 2 with one-line stderr, no
    traceback
extract:
(g) use_cache=False bypasses BOTH cache read (a poisoned entry is not returned)
    and cache write (the poison is not overwritten); temperature is passed
    explicitly to the SDK call
(h) prompt_hash() covers the extraction protocol (PROMPT_V0 + the emit_claims
    tool schema); the cache filename keeps
    its 12-char short form
"""

from __future__ import annotations

import hashlib
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
from dorian.model import Claim, canonical_json  # noqa: E402

# --- normalization ----------------------------------------------------------------


def test_normalize() -> None:
    assert churn.normalize("  The `TIMEOUT`  is **30**\tseconds.  ") == "the timeout is 30 seconds"
    assert churn.normalize("\"double\" and 'single' quotes") == "double and single quotes"
    assert churn.normalize("plain") == "plain"
    assert churn.normalize("") == ""


# --- exact distance ---------------------------------------------------------------


def test_exact_distance_hand_computed() -> None:
    assert churn.exact_distance(set(), set()) == 0.0
    assert churn.exact_distance({"a", "b"}, {"a", "b"}) == 0.0
    assert churn.exact_distance({"a"}, {"b"}) == 1.0
    assert churn.exact_distance(set(), {"a"}) == 1.0
    assert churn.exact_distance({"a", "b"}, {"b", "c"}) == pytest.approx(2 / 3)


# --- fuzzy distance ---------------------------------------------------------------


def test_fuzzy_distance_hand_computed() -> None:
    assert churn.fuzzy_distance(set(), set(), 0.75) == 0.0
    assert churn.fuzzy_distance({"abcd"}, {"abcd"}, 0.75) == 0.0
    assert churn.fuzzy_distance({"abcd"}, {"wxyz"}, 0.75) == 1.0
    assert churn.fuzzy_distance(set(), {"abcd"}, 0.75) == 1.0


def test_fuzzy_threshold_boundary() -> None:
    # SequenceMatcher("abcd", "abcx").ratio() == 0.75 exactly: >= thr counts
    assert churn.fuzzy_distance({"abcd"}, {"abcx"}, 0.75) == 0.0
    # ratio 0.5 ("abcd" vs "abxy") is below thr: no match
    assert churn.fuzzy_distance({"abcd"}, {"abxy"}, 0.75) == 1.0
    # raising thr above 0.75 turns the boundary case into a miss
    assert churn.fuzzy_distance({"abcd"}, {"abcx"}, 0.76) == 1.0


def test_fuzzy_greedy_consumes_matches() -> None:
    # both A items resemble the single B item; only one match may be counted:
    # 1 - 1 / (2 + 1 - 1) = 0.5
    assert churn.fuzzy_distance({"aaaa", "aaab"}, {"aaaa"}, 0.75) == 0.5


# --- end-to-end: stub mode ---------------------------------------------------------


def _write_stub(path: Path, texts: list[str]) -> None:
    data = {
        "claims": [
            {
                "id": f"c{i + 1}",
                "text": text,
                "kind": "fact",
                "load_bearing": False,
                "anchor": None,
                "supports": [],
                "checkers": [],
            }
            for i, text in enumerate(texts)
        ]
    }
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def test_stub_mode_three_identical_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub = tmp_path / "stub-claims.json"
    _write_stub(stub, ["The timeout is 30 seconds.", "Login is served at /v1/login."])
    monkeypatch.setenv("DORIAN_EXTRACT_STUB", str(stub))
    doc = tmp_path / "docs" / "design.md"
    doc.parent.mkdir()
    doc.write_text("# Design\r\nSome claims.\r\n", encoding="utf-8")  # CRLF: LF-normalized read
    out = tmp_path / "results" / "churn.json"

    rc = churn.main(["--doc", str(doc), "--out", str(out)])
    assert rc == 0
    assert capsys.readouterr().out == "churn: exact=0.000 fuzzy=0.000 gate=0.20 -> PASS\n"

    raw = out.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert raw == json.dumps(json.loads(raw), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    data = json.loads(raw)
    assert data["schema"] == "dorian-churn-v1"
    assert data["doc"] == "design.md"  # basename only — never the full path
    assert str(tmp_path) not in raw
    assert data["model"] == "claude-fable-5"
    assert data["temperature"] == 0.0
    assert data["runs"] == 3
    assert data["per_run_claim_counts"] == [2, 2, 2]
    assert data["exact_jaccard_distances"] == [0.0, 0.0, 0.0]
    assert data["fuzzy_jaccard_distances"] == [0.0, 0.0, 0.0]
    assert data["exact_mean"] == 0.0
    assert data["fuzzy_mean"] == 0.0
    assert data["threshold"] == 0.75
    assert data["gate"] == 0.20
    assert data["pass"] is True


def test_prompt_hash_recorded_and_stable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = hashlib.sha256(
        extract.PROMPT_V0.encode("utf-8") + b"\n" + canonical_json(extract.CLAIMS_TOOL)
    ).hexdigest()
    assert extract.prompt_hash() == expected
    assert len(extract.prompt_hash()) == 64
    # the cache filename keeps its 12-char short form
    cache = extract._cache_path(Path("c"), "sha256:x", "m")
    assert extract.prompt_hash()[:12] in cache.name
    assert extract.prompt_hash() not in cache.name

    stub = tmp_path / "stub-claims.json"
    _write_stub(stub, ["A claim."])
    monkeypatch.setenv("DORIAN_EXTRACT_STUB", str(stub))
    doc = tmp_path / "doc.md"
    doc.write_text("text\n", encoding="utf-8")
    out = tmp_path / "churn.json"
    assert churn.main(["--doc", str(doc), "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["prompt_hash"] == extract.prompt_hash()


# --- end-to-end: varying extractions -----------------------------------------------


def test_varying_extractions_fail_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Run-indexed claim sets with known overlap: pairs (0,1) and (1,2) share 1 of
    3 normalized texts (distance 2/3), pair (0,2) is identical (0.0); the mean
    4/9 ~ 0.444 is above the 0.20 gate -> exit 3."""
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    per_run = [
        ["The timeout is 30 seconds.", "Login is served at /v1/login."],
        ["The timeout is 30 seconds.", "Completely different claim here."],
        ["The timeout is 30 seconds.", "Login is served at /v1/login."],
    ]
    seen: list[dict] = []

    def fake_extract(text, *, model, cache_dir, artifact_hash, use_cache=True, temperature=0.0):
        seen.append({"use_cache": use_cache, "temperature": temperature})
        texts = per_run[len(seen) - 1]
        return [
            Claim(id=f"c{i}", text=t, kind="fact", load_bearing=False) for i, t in enumerate(texts)
        ]

    monkeypatch.setattr(extract, "extract_claims", fake_extract)
    doc = tmp_path / "doc.md"
    doc.write_text("text\n", encoding="utf-8")
    out = tmp_path / "churn.json"

    rc = churn.main(["--doc", str(doc), "--out", str(out)])
    assert rc == 3
    assert seen == [{"use_cache": False, "temperature": 0.0}] * 3

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["exact_jaccard_distances"] == [pytest.approx(2 / 3), 0.0, pytest.approx(2 / 3)]
    assert data["exact_mean"] == pytest.approx(4 / 9)
    assert data["fuzzy_mean"] == pytest.approx(4 / 9)  # no fuzzy rescue: texts dissimilar
    assert data["pass"] is False
    assert capsys.readouterr().out == "churn: exact=0.444 fuzzy=0.444 gate=0.20 -> FAIL\n"


# --- end-to-end: input/infra errors -------------------------------------------------


def test_missing_doc_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = churn.main(["--doc", str(tmp_path / "nope.md"), "--out", str(tmp_path / "o.json")])
    assert rc == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and err.endswith("\n")
    assert "Traceback" not in err
    assert not (tmp_path / "o.json").exists()


def test_extractor_unavailable_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    monkeypatch.setitem(sys.modules, "anthropic", None)  # force ImportError
    doc = tmp_path / "doc.md"
    doc.write_text("text\n", encoding="utf-8")
    rc = churn.main(["--doc", str(doc), "--out", str(tmp_path / "o.json")])
    assert rc == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and err.endswith("\n")
    assert "Traceback" not in err


# --- extract: cache bypass ----------------------------------------------------------

_EXTRACT_PAYLOAD = {
    "claims": [
        {
            "id": "c1",
            "text": "extracted",
            "kind": "fact",
            "load_bearing": True,
            "anchor": None,
            "supports": [],
            "checkers": [],
        }
    ]
}


def _install_fake_anthropic(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Install a fake `anthropic` module returning _EXTRACT_PAYLOAD; returns the
    call-recording list (mirrors tests/test_seal.py)."""
    calls: list[dict] = []

    class _Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            block = types.SimpleNamespace(
                type="tool_use", name="emit_claims", input=_EXTRACT_PAYLOAD
            )
            return types.SimpleNamespace(content=[block], stop_reason="tool_use")

    class _Anthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return calls


def test_use_cache_false_bypasses_read_and_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    calls = _install_fake_anthropic(monkeypatch)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    poisoned = extract._cache_path(cache_dir, "sha256:x", "m")
    poison = json.dumps(
        {"claims": [dict(_EXTRACT_PAYLOAD["claims"][0], id="evil", text="poisoned")]}
    )
    poisoned.write_text(poison, encoding="utf-8")

    kwargs = {"model": "m", "cache_dir": cache_dir, "artifact_hash": "sha256:x"}
    got = extract.extract_claims("artifact text", use_cache=False, **kwargs)
    assert [c.text for c in got] == ["extracted"]  # poison NOT returned
    assert len(calls) == 1
    assert calls[0]["temperature"] == 0.0  # passed explicitly to the SDK call
    assert poisoned.read_text(encoding="utf-8") == poison  # poison NOT overwritten

    # a second bypassing call hits the API again (nothing was cached)
    extract.extract_claims("artifact text", use_cache=False, **kwargs)
    assert len(calls) == 2
    assert list(cache_dir.iterdir()) == [poisoned]  # no new cache entries

    # default use_cache=True still serves the (poisoned) entry: read path intact
    cached = extract.extract_claims("artifact text", **kwargs)
    assert [c.text for c in cached] == ["poisoned"]
    assert len(calls) == 2


def test_extract_temperature_forwarded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    calls = _install_fake_anthropic(monkeypatch)
    extract.extract_claims(
        "artifact text",
        model="m",
        cache_dir=tmp_path / "cache",
        artifact_hash="sha256:x",
        temperature=0.7,
    )
    assert calls[0]["temperature"] == 0.7


def test_runs_below_two_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("# doc\n")
    rc = churn.main(["--doc", str(doc), "--runs", "1", "--out", str(tmp_path / "out.json")])
    assert rc == 2
    assert "must be >= 2" in capsys.readouterr().err
    assert not (tmp_path / "out.json").exists()


def _install_temp_rejecting_anthropic(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Fake anthropic whose create() answers the real API 400 for any call that
    carries temperature: '`temperature` is deprecated for this model.'"""
    calls: list[dict] = []

    class _Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            if "temperature" in kwargs:
                raise RuntimeError(
                    "Error code: 400 - {'type': 'error', 'error': {'type': "
                    "'invalid_request_error', 'message': '`temperature` is "
                    "deprecated for this model.'}}"
                )
            block = types.SimpleNamespace(
                type="tool_use", name="emit_claims", input=_EXTRACT_PAYLOAD
            )
            return types.SimpleNamespace(content=[block], stop_reason="tool_use")

    class _Anthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return calls


def test_temperature_deprecated_model_retries_without(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    monkeypatch.setattr(extract, "_TEMP_UNSUPPORTED", set())
    calls = _install_temp_rejecting_anthropic(monkeypatch)

    claims = extract.extract_claims(
        "artifact text",
        model="fable",
        cache_dir=tmp_path / "c",
        artifact_hash="sha256:x",
        use_cache=False,
    )
    assert [c.text for c in claims]
    # first call sent temperature and was rejected; the retry dropped it
    assert "temperature" in calls[0] and "temperature" not in calls[1]
    assert extract.temperature_unsupported("fable")

    # the rejection is remembered: the next run never sends temperature
    extract.extract_claims(
        "artifact text",
        model="fable",
        cache_dir=tmp_path / "c",
        artifact_hash="sha256:x",
        use_cache=False,
    )
    assert len(calls) == 3 and "temperature" not in calls[2]


def test_non_temperature_errors_still_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    monkeypatch.setattr(extract, "_TEMP_UNSUPPORTED", set())

    class _Messages:
        def create(self, **kwargs):
            raise RuntimeError("Error code: 429 - overloaded")

    class _Anthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    with pytest.raises(RuntimeError, match="429"):
        extract.extract_claims(
            "artifact text",
            model="m",
            cache_dir=tmp_path / "c",
            artifact_hash="sha256:x",
            use_cache=False,
        )


def test_churn_records_deprecated_temperature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    monkeypatch.setattr(extract, "_TEMP_UNSUPPORTED", set())
    _install_temp_rejecting_anthropic(monkeypatch)
    doc = tmp_path / "doc.md"
    doc.write_text("# doc\n")
    out = tmp_path / "churn.json"
    rc = churn.main(["--doc", str(doc), "--runs", "2", "--model", "fable", "--out", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["temperature"] is None
    assert data["temperature_deprecated_by_model"] is True


def test_truncated_extraction_is_a_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    monkeypatch.setattr(extract, "_TEMP_UNSUPPORTED", set())

    class _Messages:
        def create(self, **kwargs):
            return types.SimpleNamespace(content=[], stop_reason="max_tokens")

    class _Anthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    with pytest.raises(ValueError, match="truncated at max_tokens"):
        extract.extract_claims(
            "artifact",
            model="m",
            cache_dir=tmp_path / "c",
            artifact_hash="sha256:x",
            use_cache=False,
        )


def test_missing_tool_call_is_a_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    monkeypatch.setattr(extract, "_TEMP_UNSUPPORTED", set())

    class _Messages:
        def create(self, **kwargs):
            block = types.SimpleNamespace(type="text", text="prose, not a tool call")
            return types.SimpleNamespace(content=[block], stop_reason="end_turn")

    class _Anthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    with pytest.raises(ValueError, match="no emit_claims tool call"):
        extract.extract_claims(
            "artifact",
            model="m",
            cache_dir=tmp_path / "c",
            artifact_hash="sha256:x",
            use_cache=False,
        )


def test_forced_tool_choice_is_sent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    monkeypatch.setattr(extract, "_TEMP_UNSUPPORTED", set())
    calls = _install_fake_anthropic(monkeypatch)
    extract.extract_claims(
        "artifact", model="m", cache_dir=tmp_path / "c", artifact_hash="sha256:x", use_cache=False
    )
    assert calls[0]["tool_choice"] == {"type": "tool", "name": "emit_claims"}
    assert calls[0]["tools"] == [extract.CLAIMS_TOOL]


def _install_degrading_anthropic(
    monkeypatch: pytest.MonkeyPatch, *, reject_temperature: bool, reject_forced_tools: bool
) -> list[dict]:
    """Fake anthropic that replays the real claude-fable-5 400s: rejects
    temperature and/or forced tool_choice, succeeds otherwise."""
    calls: list[dict] = []

    class _Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            if reject_temperature and "temperature" in kwargs:
                raise RuntimeError("Error code: 400 - `temperature` is deprecated for this model.")
            if reject_forced_tools and kwargs.get("tool_choice", {}).get("type") == "tool":
                raise RuntimeError(
                    "Error code: 400 - tool_choice forces tool use is not compatible "
                    "with this model."
                )
            block = types.SimpleNamespace(
                type="tool_use", name="emit_claims", input=_EXTRACT_PAYLOAD
            )
            return types.SimpleNamespace(content=[block], stop_reason="tool_use")

    class _Anthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return calls


def test_forced_tool_choice_rejected_falls_back_to_auto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    monkeypatch.setattr(extract, "_TEMP_UNSUPPORTED", set())
    monkeypatch.setattr(extract, "_FORCED_TOOLS_UNSUPPORTED", set())
    calls = _install_degrading_anthropic(
        monkeypatch, reject_temperature=False, reject_forced_tools=True
    )
    claims = extract.extract_claims(
        "artifact",
        model="fable",
        cache_dir=tmp_path / "c",
        artifact_hash="sha256:x",
        use_cache=False,
    )
    assert [c.text for c in claims]
    assert calls[0]["tool_choice"]["type"] == "tool"
    assert calls[1]["tool_choice"] == {"type": "auto"}
    assert extract.forced_tools_unsupported("fable")
    # remembered: the next run starts at auto, no failed call
    extract.extract_claims(
        "artifact",
        model="fable",
        cache_dir=tmp_path / "c",
        artifact_hash="sha256:x",
        use_cache=False,
    )
    assert len(calls) == 3 and calls[2]["tool_choice"] == {"type": "auto"}


def test_double_degradation_temperature_then_forced_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """claude-fable-5 rejects both: two adaptive retries land the call."""
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    monkeypatch.setattr(extract, "_TEMP_UNSUPPORTED", set())
    monkeypatch.setattr(extract, "_FORCED_TOOLS_UNSUPPORTED", set())
    calls = _install_degrading_anthropic(
        monkeypatch, reject_temperature=True, reject_forced_tools=True
    )
    claims = extract.extract_claims(
        "artifact",
        model="fable",
        cache_dir=tmp_path / "c",
        artifact_hash="sha256:x",
        use_cache=False,
    )
    assert [c.text for c in claims]
    assert len(calls) == 3
    assert "temperature" not in calls[2] and calls[2]["tool_choice"] == {"type": "auto"}
    assert extract.temperature_unsupported("fable")
    assert extract.forced_tools_unsupported("fable")


def test_auto_mode_merges_multiple_tool_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    monkeypatch.setattr(extract, "_TEMP_UNSUPPORTED", set())
    monkeypatch.setattr(extract, "_FORCED_TOOLS_UNSUPPORTED", {"m"})

    half_a = {"claims": [dict(_EXTRACT_PAYLOAD["claims"][0])]}
    half_b = {"claims": [dict(_EXTRACT_PAYLOAD["claims"][0], id="c99", text="second half")]}

    class _Messages:
        def create(self, **kwargs):
            blocks = [
                types.SimpleNamespace(type="text", text="extracting..."),
                types.SimpleNamespace(type="tool_use", name="emit_claims", input=half_a),
                types.SimpleNamespace(type="tool_use", name="emit_claims", input=half_b),
            ]
            return types.SimpleNamespace(content=blocks, stop_reason="end_turn")

    class _Anthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    claims = extract.extract_claims(
        "artifact",
        model="m",
        cache_dir=tmp_path / "c",
        artifact_hash="sha256:x",
        use_cache=False,
    )
    assert [c.id for c in claims][-1] == "c99" and len(claims) == 2


def test_churn_records_tool_choice_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    monkeypatch.setattr(extract, "_TEMP_UNSUPPORTED", set())
    monkeypatch.setattr(extract, "_FORCED_TOOLS_UNSUPPORTED", set())
    _install_degrading_anthropic(monkeypatch, reject_temperature=True, reject_forced_tools=True)
    doc = tmp_path / "doc.md"
    doc.write_text("# doc\n")
    out = tmp_path / "churn.json"
    rc = churn.main(["--doc", str(doc), "--runs", "2", "--model", "fable", "--out", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["tool_choice"] == "auto"
    assert data["temperature"] is None and data["temperature_deprecated_by_model"] is True
