"""Claims file IO. The claims file is JSON (zero-dep kernel decision): claims.json,
shaped {"claims": [{id, text, kind, load_bearing, anchor|null, supports, checkers}]}.

Kinds and checker types are validated against the model literals; bad input raises
ValueError with a message naming the offending claim.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

from dorian.model import CheckerType, Claim, ClaimKind

VALID_KINDS = frozenset(get_args(ClaimKind))
VALID_CHECKER_TYPES = frozenset(get_args(CheckerType))


def claims_from_dict(data: Any) -> list[Claim]:
    """Parse + validate {"claims": [...]}; raises ValueError on bad input."""
    if not isinstance(data, dict) or not isinstance(data.get("claims"), list):
        raise ValueError('claims file must be a JSON object {"claims": [...]}')
    claims: list[Claim] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(data["claims"]):
        label = f"claims[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{label}: expected an object, got {type(raw).__name__}")
        try:
            claim = Claim.from_dict(raw)
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"{label}: missing or malformed field {exc} "
                "(required: id, text, kind, load_bearing)"
            ) from None
        if claim.id in seen_ids:
            raise ValueError(f"{label}: duplicate claim id {claim.id!r}")
        seen_ids.add(claim.id)
        if claim.kind not in VALID_KINDS:
            raise ValueError(
                f"{label} ({claim.id!r}): bad kind {claim.kind!r}; "
                f"expected one of {sorted(VALID_KINDS)}"
            )
        for spec in claim.checkers:
            if spec.type not in VALID_CHECKER_TYPES:
                raise ValueError(
                    f"{label} ({claim.id!r}): bad checker type {spec.type!r}; "
                    f"expected one of {sorted(VALID_CHECKER_TYPES)}"
                )
        claims.append(claim)
    return claims


def claims_to_dict(claims: list[Claim]) -> dict[str, Any]:
    return {"claims": [c.to_dict() for c in claims]}


def load_claims(path: Path) -> list[Claim]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not valid JSON: {exc}") from None
    return claims_from_dict(data)


def save_claims(path: Path, claims: list[Claim]) -> None:
    path.write_text(
        json.dumps(claims_to_dict(claims), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
