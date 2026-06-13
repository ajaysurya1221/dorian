"""Contract pins for the agent-emitted claims.json (docs/AGENT_CLAIMS.md).

The existing claims.json schema IS the agent contract, so these tests lock the
required/optional field set and the rejection behaviour the doc promises — if the
parser ever drifts from the documented contract, one of these fails. The key pin is
that all four of id/text/kind/load_bearing stay REQUIRED (no silent defaults): a
defaulted load_bearing would invisibly flip a future break between REVOKE and DEGRADE.
"""

from __future__ import annotations

import pytest

from dorian import claims_io


def _valid_claim(**overrides: object) -> dict:
    claim = {
        "id": "c1",
        "text": "An asserted fact.",
        "kind": "fact",
        "load_bearing": True,
        "checkers": [{"type": "C3", "program": "path:src/x.py"}],
    }
    claim.update(overrides)
    return claim


def _parse(claims: list[dict]):
    return claims_io.claims_from_dict({"claims": claims})


def test_valid_agent_claim_round_trips() -> None:
    [claim] = _parse([_valid_claim()])
    assert claim.id == "c1"
    assert claim.kind == "fact"
    assert claim.load_bearing is True
    assert claim.checkers[0].type == "C3"
    assert set(claim.to_dict()) == {
        "id",
        "text",
        "kind",
        "anchor",
        "load_bearing",
        "supports",
        "checkers",
    }


@pytest.mark.parametrize("field", ["id", "text", "kind", "load_bearing"])
def test_each_required_field_stays_required(field: str) -> None:
    raw = _valid_claim()
    del raw[field]
    with pytest.raises(ValueError) as exc:
        _parse([raw])
    assert "claims[0]" in str(exc.value)


def test_optional_fields_default_when_omitted() -> None:
    [claim] = _parse([{"id": "c1", "text": "x", "kind": "fact", "load_bearing": False}])
    assert claim.anchor is None
    assert claim.supports == ()
    assert claim.checkers == ()


def test_bad_kind_is_rejected_naming_the_claim() -> None:
    with pytest.raises(ValueError) as exc:
        _parse([_valid_claim(kind="nope")])
    assert "nope" in str(exc.value) and "c1" in str(exc.value)


def test_bad_checker_type_is_rejected() -> None:
    with pytest.raises(ValueError) as exc:
        _parse([_valid_claim(checkers=[{"type": "C9", "program": "x"}])])
    assert "C9" in str(exc.value)


def test_duplicate_claim_id_is_rejected() -> None:
    with pytest.raises(ValueError) as exc:
        _parse([_valid_claim(), _valid_claim()])
    assert "duplicate" in str(exc.value).lower()
