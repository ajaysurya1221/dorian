"""Human-authored Goal records — durable context for a governed run. Stdlib only.

A Goal is the human-authored "charge" for a run: the objective plus its jurisdiction
(scope / deny-paths), a policy reference, the base ref that changed paths are computed
against, and a structural coverage contract. It is written as a sibling sidecar via
``dorian.sidecars`` and read back deterministically.

IMPORTANT (Non-Negotiable): the goal ``statement`` is human context ONLY. Dorian never feeds
it to a model and never uses it — or any field here — to decide whether the goal is
"complete" or whether a loop may continue. Nothing in this module is imported by the verdict
path (model / checkers / seal / revalidate / fold / policy / loop); there is no
model-evaluated goal satisfaction. Scope/policy are human-set, never model-set at runtime.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dorian import sidecars

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Goal:
    goal_id: str
    title: str
    statement: str  # human prose; never fed to a model; never in verdict/completion logic
    policy_ref: str = "default-assist"
    scope: tuple[str, ...] = ()  # human-set jurisdiction; never model-set at runtime
    deny_paths: tuple[str, ...] = ()
    base_ref: str = ""  # the ref changed paths are computed against (used by a later task)
    coverage_contract: dict = field(default_factory=dict)  # structural contract only
    status: str = "open"
    warrant_ids: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        d = asdict(self)
        d["scope"] = list(self.scope)
        d["deny_paths"] = list(self.deny_paths)
        d["warrant_ids"] = list(self.warrant_ids)
        return d


def goal_path(goal_id: str) -> str:
    """Repo-relative sidecar path for a goal record."""
    return f".dorian/goals/{goal_id}.goal.json"


def save(repo: Path, goal: Goal) -> Path:
    """Write a goal record as a deterministic sibling sidecar (not a ledger). Returns the path.

    Path containment (no ``../`` escape) is enforced by ``sidecars.write_sidecar``.
    """
    return sidecars.write_sidecar(repo, goal_path(goal.goal_id), goal.to_dict())


def load(repo: Path, goal_id: str) -> Goal:
    """Read back a goal record, validating its schema version.

    Raises ``ValueError`` for a malformed record (not JSON / not an object / missing required
    field) or an unsupported ``schema_version``.
    """
    raw = (repo / goal_path(goal_id)).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed goal record {goal_id!r}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"malformed goal record {goal_id!r}: expected a JSON object")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported goal schema_version {version!r} for {goal_id!r} "
            f"(expected {SCHEMA_VERSION})"
        )
    try:
        return Goal(
            goal_id=data["goal_id"],
            title=data["title"],
            statement=data["statement"],
            policy_ref=data.get("policy_ref", "default-assist"),
            scope=tuple(data.get("scope", ())),
            deny_paths=tuple(data.get("deny_paths", ())),
            base_ref=data.get("base_ref", ""),
            coverage_contract=data.get("coverage_contract", {}),
            status=data.get("status", "open"),
            warrant_ids=tuple(data.get("warrant_ids", ())),
            schema_version=version,
        )
    except KeyError as exc:
        raise ValueError(f"malformed goal record {goal_id!r}: missing field {exc}") from exc
