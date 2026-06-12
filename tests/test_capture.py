"""Capture acceptance: transcript JSONL -> ReadSet, manual specs -> ReadSet (W1 capture)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dorian import gitio
from dorian.capture.manual import parse_manual
from dorian.capture.transcript import parse_transcript
from dorian.model import ReadSet


def _tu(name: str, **inp) -> dict:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]},
    }


def _write_jsonl(tmp_path: Path, records: list[dict], name: str = "session.jsonl") -> Path:
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return p


# --- (a) transcript fixture ----------------------------------------------------


def test_transcript_captures_reads_with_selectors(transcript_file, fixture_repo):
    rs = parse_transcript(transcript_file, fixture_repo)
    captured = {(e.uri, e.selector) for e in rs.entries}
    assert ("src/auth.py", None) in captured
    assert ("src/config.py", "L1-2") in captured
    assert ("data/lots.csv", None) in captured  # from the Bash `cat`


def test_transcript_ignores_writes_and_directories(transcript_file, fixture_repo):
    rs = parse_transcript(transcript_file, fixture_repo)
    uris = {e.uri for e in rs.entries}
    assert not any("design.md" in u for u in uris)  # Write block: output, not read
    assert "src" not in uris  # Grep directory path: not recorded


def test_transcript_coverage_hashes_version(transcript_file, fixture_repo):
    rs = parse_transcript(transcript_file, fixture_repo)
    assert rs.coverage >= 0.75
    head = gitio.head_ref(fixture_repo)
    for e in rs.entries:
        assert e.scope == "project"
        assert e.version == head
        assert e.hash == gitio.working_hash(fixture_repo, e.uri, e.selector)


def test_transcript_produced_by(transcript_file, fixture_repo):
    rs = parse_transcript(transcript_file, fixture_repo)
    assert rs.produced_by.runner == "claude-code"
    assert rs.produced_by.run_ref == str(transcript_file)
    assert rs.produced_by.captured_at != ""


def test_transcript_dedupes_and_skips_non_read_bash(tmp_path, fixture_repo):
    records = [
        _tu("Read", file_path=str(fixture_repo / "src/auth.py")),
        _tu("Read", file_path=str(fixture_repo / "src/auth.py")),  # duplicate -> one entry
        _tu("Bash", command=f"python {fixture_repo}/src/routes.py"),  # not a read command
    ]
    rs = parse_transcript(_write_jsonl(tmp_path, records, name="dup.jsonl"), fixture_repo)
    assert [(e.uri, e.selector) for e in rs.entries] == [("src/auth.py", None)]


# --- (a') transcript robustness (review hardening) -------------------------------


def test_transcript_read_offset_zero_clamps_selector(tmp_path, fixture_repo):
    # The Claude Code Read schema allows offset=0; 'L0-4' is an invalid selector
    # and must not abort the parse — clamp to line 1.
    p = _write_jsonl(
        tmp_path, [_tu("Read", file_path=str(fixture_repo / "src/auth.py"), offset=0, limit=5)]
    )
    rs = parse_transcript(p, fixture_repo)
    assert [(e.uri, e.selector) for e in rs.entries] == [("src/auth.py", "L1-5")]
    assert rs.entries[0].hash == gitio.working_hash(fixture_repo, "src/auth.py", "L1-5")


def test_transcript_external_read_recorded_as_external(tmp_path, fixture_repo):
    ext = tmp_path / "notes.txt"
    ext.write_text("external notes\n")
    rs = parse_transcript(_write_jsonl(tmp_path, [_tu("Read", file_path=str(ext))]), fixture_repo)
    assert len(rs.entries) == 1
    e = rs.entries[0]
    assert e.scope == "external"
    assert e.uri == str(ext.resolve())
    assert Path(e.uri).is_absolute()


def _block(name: str, inp) -> dict:
    # Like _tu but with a raw (possibly non-dict) input value, e.g. JSON null.
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]},
    }


def test_transcript_tolerates_non_string_inputs(tmp_path, fixture_repo):
    records = [
        _tu("Read", file_path=123),
        _tu("Grep", pattern="x", path=123),
        _tu("Bash", command=123),
        _block("Read", None),  # input present as JSON null
        _block("Read", [1, 2]),  # input present as a list
        _block("Bash", "cat /etc/hosts"),  # input present as a bare string
        _tu("Read", file_path=str(fixture_repo / "src/auth.py")),
    ]
    rs = parse_transcript(_write_jsonl(tmp_path, records), fixture_repo)
    assert [(e.uri, e.selector) for e in rs.entries] == [("src/auth.py", None)]


def test_transcript_tolerates_malformed_jsonl_and_bad_bytes(tmp_path, fixture_repo):
    good = json.dumps(_tu("Read", file_path=str(fixture_repo / "src/auth.py")))
    bad_lines = [
        b"{not json",
        b"\xff\xfegarbage",
        b'"hello"',  # valid JSON, but a scalar, not an object
        b"42",
        b"[1,2]",
        json.dumps({"type": "assistant", "message": None}).encode(),
        json.dumps({"type": "assistant", "message": "oops"}).encode(),
        good.encode(),
    ]
    p = tmp_path / "bad.jsonl"
    p.write_bytes(b"\n".join(bad_lines) + b"\n")
    rs = parse_transcript(p, fixture_repo)
    assert [(e.uri, e.selector) for e in rs.entries] == [("src/auth.py", None)]


def test_transcript_empty_yields_zero_coverage(tmp_path, fixture_repo):
    # Spec formula: coverage = recorded / max(1, observed) -> 0.0 for a read-free run.
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    rs = parse_transcript(p, fixture_repo)
    assert rs.entries == ()
    assert rs.coverage == 0.0


def test_transcript_bash_quoted_path_with_spaces(tmp_path, fixture_repo):
    spaced = fixture_repo / "data" / "lot notes.csv"
    spaced.write_text("a,b\n1,2\n")
    rs = parse_transcript(
        _write_jsonl(tmp_path, [_tu("Bash", command=f'cat "{spaced}"')]), fixture_repo
    )
    assert [(e.uri, e.selector) for e in rs.entries] == [("data/lot notes.csv", None)]
    assert rs.coverage == 1.0


def test_transcript_bash_unbalanced_quote_degrades_to_whitespace_split(tmp_path, fixture_repo):
    # shlex.split raises ValueError on the unbalanced quote; the parser must
    # degrade to a plain whitespace split and still capture the real path.
    cmd = f"cat {fixture_repo}/data/lots.csv 'oops"
    rs = parse_transcript(_write_jsonl(tmp_path, [_tu("Bash", command=cmd)]), fixture_repo)
    assert [(e.uri, e.selector) for e in rs.entries] == [("data/lots.csv", None)]
    assert rs.coverage == 1.0  # the quote fragment is not a path token


# --- (b) manual ------------------------------------------------------------------


def test_manual_span_selector(fixture_repo):
    rs = parse_manual(["src/config.py:L1-2", "src/auth.py"], fixture_repo)
    cfg = next(e for e in rs.entries if e.uri == "src/config.py")
    assert cfg.selector == "L1-2"
    assert cfg.hash == gitio.working_hash(fixture_repo, "src/config.py", "L1-2")
    assert rs.coverage == 1.0
    assert rs.produced_by.runner == "manual"


def test_manual_missing_file_raises(fixture_repo):
    with pytest.raises(ValueError):
        parse_manual(["src/nope.py"], fixture_repo)


def test_manual_bad_selector_raises(fixture_repo):
    with pytest.raises(ValueError):
        parse_manual(["src/config.py:L5-2"], fixture_repo)
    with pytest.raises(ValueError):
        parse_manual(["src/config.py:Lx-y"], fixture_repo)


def test_manual_relative_traversal_raises(tmp_path, fixture_repo):
    # The file exists outside the repo: must be rejected, not hashed as 'project'.
    (tmp_path / "outside.txt").write_text("secret\n")
    with pytest.raises(ValueError, match="outside repo"):
        parse_manual(["../outside.txt"], fixture_repo)


def test_manual_dotdot_inside_spec_raises(tmp_path, fixture_repo):
    (tmp_path / "x").write_text("secret\n")
    with pytest.raises(ValueError, match="outside repo"):
        parse_manual(["src/../../x"], fixture_repo)


def test_manual_absolute_outside_repo_raises(tmp_path, fixture_repo):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n")
    with pytest.raises(ValueError, match="outside repo"):
        parse_manual([str(outside)], fixture_repo)


def test_manual_empty_specs(fixture_repo):
    rs = parse_manual([], fixture_repo)
    assert rs.entries == ()
    assert rs.coverage == 1.0


def test_manual_duplicate_specs_not_deduped(fixture_repo):
    # Documented behavior: manual specs are taken literally — unlike transcript
    # capture, duplicates are NOT deduped; each spec yields its own entry.
    rs = parse_manual(["src/auth.py", "src/auth.py"], fixture_repo)
    assert [e.uri for e in rs.entries] == ["src/auth.py", "src/auth.py"]
    assert [e.id for e in rs.entries] == ["rs-0", "rs-1"]


# --- (c) round-trip ----------------------------------------------------------------


def test_readset_roundtrips_dump_load(tmp_path, transcript_file, fixture_repo):
    rs = parse_transcript(transcript_file, fixture_repo)
    out = tmp_path / "readset.json"
    rs.dump(out)
    assert ReadSet.load(out) == rs
