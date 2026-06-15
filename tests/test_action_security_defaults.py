"""The GitHub Action's security posture is honest and conservative.

Pins that the Action exposes a deny-exec opt-in defaulting to OFF (so trusted
repos are unchanged), wires it through the env fallback dorian honors, never
recommends the pull_request_target footgun, and that the security docs state the
public-fork limitation plainly. These are doc/config invariants — no network.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTION_YML = REPO_ROOT / "action" / "action.yml"
ACTION_README = REPO_ROOT / "action" / "README.md"


def _action() -> dict:
    return yaml.safe_load(ACTION_YML.read_text(encoding="utf-8"))


def test_action_exposes_deny_exec_inputs_defaulting_off() -> None:
    inputs = _action()["inputs"]
    assert "deny_exec" in inputs and "deny_shell" in inputs
    # default OFF: trusted/internal repos get exactly today's behavior
    assert str(inputs["deny_exec"]["default"]) == "false"
    assert str(inputs["deny_shell"]["default"]) == "false"


def test_action_wires_deny_flags_through_env_fallback() -> None:
    text = ACTION_YML.read_text(encoding="utf-8")
    assert "DORIAN_DENY_EXEC: ${{ inputs.deny_exec }}" in text
    assert "DORIAN_DENY_SHELL: ${{ inputs.deny_shell }}" in text


def test_action_exposes_checker_trust_defaulting_head() -> None:
    inputs = _action()["inputs"]
    assert "checker_trust" in inputs
    # default head = today's behavior; trusted repos are unchanged unless they opt in
    assert str(inputs["checker_trust"]["default"]) == "head"


def test_action_wires_checker_trust_through_env() -> None:
    text = ACTION_YML.read_text(encoding="utf-8")
    assert "DORIAN_CHECKER_SOURCE: ${{ inputs.checker_trust }}" in text


def test_action_does_not_recommend_pull_request_target() -> None:
    readme = ACTION_README.read_text(encoding="utf-8")
    # it is named only to forbid it
    assert "never" in readme.lower() and "pull_request_target" in readme


def test_security_docs_state_public_fork_limitation() -> None:
    sec = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    boundary = (REPO_ROOT / "docs" / "SECURITY_BOUNDARY.md").read_text(encoding="utf-8")
    for doc in (sec, boundary):
        low = doc.lower()
        assert "--deny-exec" in doc
        assert "not a sandbox" in low
        assert "fork" in low  # public-fork posture is addressed explicitly
