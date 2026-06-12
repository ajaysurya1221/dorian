"""Scaffold acceptance tests: canonical hashing, selectors, warrant round-trip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dorian.model import (
    Anchor,
    CheckerSpec,
    Claim,
    FoldPolicy,
    IntegrityError,
    ProducedBy,
    ReadSet,
    ReadSetEntry,
    Warrant,
    canonical_json,
    extract_span,
    lf_normalize,
    parse_selector,
    sha256_hex,
    span_hash,
)


def make_warrant() -> Warrant:
    entry = ReadSetEntry(
        id="rs-0", uri="src/auth.py", selector="L4-7", hash="sha256:aa", version="abc1234"
    )
    claim = Claim(
        id="c-01",
        text="Token verification uses RS256.",
        kind="fact",
        load_bearing=True,
        anchor=Anchor(3, 3, "uses RS256"),
        supports=("rs-0",),
        checkers=(CheckerSpec(type="C1", program="rs-0", watch=("src/auth.py",)),),
    )
    return Warrant.create(
        artifact_uri="docs/design.md",
        artifact_hash="sha256:bb",
        git_ref="abc1234",
        produced_by=ProducedBy(runner="manual", captured_at="2026-06-11T00:00:00Z"),
        read_set=(entry,),
        claims=(claim,),
        fold_policy=FoldPolicy(),
        sealed_at="2026-06-11T00:00:00Z",
    )


def test_canonical_json_is_key_order_stable():
    a = {"b": 1, "a": [{"y": 2, "x": 3}]}
    b = {"a": [{"x": 3, "y": 2}], "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert sha256_hex(canonical_json(a)) == sha256_hex(canonical_json(b))


def test_lf_normalization():
    assert lf_normalize(b"a\r\nb\rc\n") == b"a\nb\nc\n"


def test_selector_parse_and_span():
    assert parse_selector(None) is None
    assert parse_selector("L2-3") == (2, 3)
    with pytest.raises(ValueError):
        parse_selector("40-88")
    text = "one\ntwo\nthree\nfour"
    assert extract_span(text, "L2-3") == "two\nthree"
    assert extract_span(text, None) == text
    assert span_hash(text, "L2-3") == sha256_hex(b"two\nthree")


def test_warrant_id_is_content_addressed_and_excludes_id():
    w = make_warrant()
    assert w.id.startswith("sha256:")
    assert w.id == Warrant.compute_id(w.body_dict())
    assert "id" not in w.body_dict()


def test_warrant_round_trip(tmp_path: Path):
    w = make_warrant()
    p = tmp_path / "design.md.warrant"
    w.dump(p)
    w2 = Warrant.load(p)
    assert w2 == w
    assert w2.to_dict() == w.to_dict()


def test_warrant_load_rejects_tampered_sidecar(tmp_path: Path):
    w = make_warrant()
    p = tmp_path / "design.md.warrant"
    w.dump(p)
    d = json.loads(p.read_text())
    d["warrant"]["claims"][0]["text"] = "tampered"
    p.write_text(json.dumps(d))
    with pytest.raises(IntegrityError):
        Warrant.load(p)


def test_readset_round_trip(tmp_path: Path):
    rs = ReadSet(
        entries=(
            ReadSetEntry(id="rs-0", uri="a.py", selector=None, hash="sha256:cc", version=None),
        ),
        produced_by=ProducedBy(runner="manual", captured_at="2026-06-11T00:00:00Z"),
        coverage=0.9,
    )
    p = tmp_path / "rs.json"
    rs.dump(p)
    assert ReadSet.load(p) == rs
    assert rs.entry("rs-0").uri == "a.py"
    with pytest.raises(KeyError):
        rs.entry("rs-9")
