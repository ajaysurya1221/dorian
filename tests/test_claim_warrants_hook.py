"""The opt-in, reminder-only Dorian claim-warrants Stop hook.

The hook must be safe above all: it never blocks, never writes files, never runs
``dorian``/tests/project code (its only side effect is a read-only ``git status``),
and fails open on any error. It emits a soft ``additionalContext`` reminder only
when a turn left relevant, un-warranted changes. These tests load the ACTUAL
shipped template so a regression in the template fails CI.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_SRC = (
    Path(__file__).resolve().parent.parent
    / "src/dorian/templates/claude_code/hooks/dorian_claim_warrants_stop.py"
)


def _load_hook():
    spec = importlib.util.spec_from_file_location("dorian_claim_warrants_stop", HOOK_SRC)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


hook = _load_hook()

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=repo, env={**os.environ, **_GIT_ENV}, check=True, capture_output=True
    )


# --- pure helpers -------------------------------------------------------------


def test_load_input_tolerates_garbage() -> None:
    assert hook.load_input("") == {}
    assert hook.load_input("not json") == {}
    assert hook.load_input("[1,2,3]") == {}  # not a dict
    assert hook.load_input('{"a": 1}') == {"a": 1}


def test_skip_markers_env_and_message() -> None:
    assert hook.skip_markers_present({"DORIAN_CLAIM_WARRANTS_SKIP": "1"}, "")
    assert hook.skip_markers_present({"NO_DORIAN_RECEIPTS": "1"}, "")
    assert hook.skip_markers_present({}, "please NO_DORIAN_CLAIM_WARRANTS here")
    assert not hook.skip_markers_present({}, "normal message")


def test_relevant_change_detection() -> None:
    assert hook.has_relevant_change(["src/app.py"])
    assert hook.has_relevant_change(["pyproject.toml"])
    assert not hook.has_relevant_change(["README.md", "docs/guide.md"])
    assert not hook.has_relevant_change([])


def test_already_has_warrant_artifacts() -> None:
    assert hook.already_has_warrant_artifacts(["docs/changes/x.claims.json"])
    assert hook.already_has_warrant_artifacts(["docs/changes/x.md.warrant"])
    assert not hook.already_has_warrant_artifacts(["src/app.py"])


def test_message_says_no_change() -> None:
    assert hook.message_says_no_change("This was research only.")
    assert hook.message_says_no_change("No code changes were needed.")
    assert not hook.message_says_no_change("I added a function and a constant.")


def test_reminder_output_shape() -> None:
    out = hook.reminder_output()
    assert out["hookSpecificOutput"]["hookEventName"] == "Stop"
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "/dorian-claim-warrants" in ctx
    assert "strength-gate=fail" in ctx
    # reminder-only: never a block/decision field
    assert "decision" not in out


def test_last_assistant_message_prefers_direct_field() -> None:
    assert hook.last_assistant_message({"last_assistant_message": "hi"}) == "hi"


def test_last_assistant_message_parses_transcript(tmp_path: Path) -> None:
    t = tmp_path / "t.jsonl"
    t.write_text(
        "\n".join(
            [
                json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "first"}],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "LAST one"}],
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    assert hook.last_assistant_message({"transcript_path": str(t)}) == "LAST one"


def test_last_assistant_message_missing_transcript_is_empty() -> None:
    assert hook.last_assistant_message({"transcript_path": "/no/such/file.jsonl"}) == ""
    assert hook.last_assistant_message({}) == ""


# --- should_remind gating (changed_paths/message monkeypatched) ---------------


def _payload(**kw):
    base = {"hook_event_name": "Stop", "stop_hook_active": False, "cwd": "/x"}
    base.update(kw)
    return base


def test_no_op_on_non_stop_event(monkeypatch) -> None:
    monkeypatch.setattr(hook, "changed_paths", lambda cwd: ["src/app.py"])
    monkeypatch.setattr(hook, "last_assistant_message", lambda p: "changed stuff")
    assert hook.should_remind(_payload(hook_event_name="PreToolUse"), {}) is False


def test_no_op_when_stop_hook_active(monkeypatch) -> None:
    monkeypatch.setattr(hook, "changed_paths", lambda cwd: ["src/app.py"])
    assert hook.should_remind(_payload(stop_hook_active=True), {}) is False


def test_no_op_on_env_skip_marker(monkeypatch) -> None:
    monkeypatch.setattr(hook, "changed_paths", lambda cwd: ["src/app.py"])
    assert hook.should_remind(_payload(), {"NO_DORIAN_CLAIM_WARRANTS": "1"}) is False


def test_no_op_outside_git_repo(monkeypatch) -> None:
    monkeypatch.setattr(hook, "changed_paths", lambda cwd: None)  # not a git repo
    assert hook.should_remind(_payload(), {}) is False


def test_no_op_when_no_relevant_change(monkeypatch) -> None:
    monkeypatch.setattr(hook, "changed_paths", lambda cwd: ["README.md"])
    assert hook.should_remind(_payload(), {}) is False


def test_no_op_when_warrant_artifacts_already_present(monkeypatch) -> None:
    monkeypatch.setattr(
        hook, "changed_paths", lambda cwd: ["src/app.py", "docs/changes/x.claims.json"]
    )
    assert hook.should_remind(_payload(), {}) is False


def test_no_op_when_message_says_no_change(monkeypatch) -> None:
    monkeypatch.setattr(hook, "changed_paths", lambda cwd: ["src/app.py"])
    monkeypatch.setattr(hook, "last_assistant_message", lambda p: "This was research only.")
    assert hook.should_remind(_payload(), {}) is False


def test_reminds_on_relevant_change(monkeypatch) -> None:
    monkeypatch.setattr(hook, "changed_paths", lambda cwd: ["src/app.py"])
    monkeypatch.setattr(hook, "last_assistant_message", lambda p: "added a function and a constant")
    assert hook.should_remind(_payload(), {}) is True


# --- changed_paths against a real git repo ------------------------------------


def test_changed_paths_reads_real_git(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    paths = hook.changed_paths(str(repo))
    assert paths is not None and "app.py" in paths


def test_changed_paths_none_outside_git(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert hook.changed_paths(str(plain)) is None


# --- the real entry point via subprocess --------------------------------------


def _run_hook(payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK_SRC)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
        env={k: v for k, v in os.environ.items() if not k.startswith("DORIAN_")},
        timeout=30,
    )


def test_entrypoint_emits_reminder_and_writes_nothing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps(
            {"type": "assistant", "message": {"role": "assistant", "content": "I added f()."}}
        )
        + "\n",
        encoding="utf-8",
    )
    before = {p.name for p in repo.rglob("*")}
    r = _run_hook(
        {
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "cwd": str(repo),
            "transcript_path": str(transcript),
        },
        cwd=repo,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["additionalContext"]
    # the hook wrote nothing into the repo
    assert {p.name for p in repo.rglob("*")} == before


def test_entrypoint_silent_on_non_stop(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "app.py").write_text("x=1\n", encoding="utf-8")
    r = _run_hook({"hook_event_name": "PreToolUse", "cwd": str(repo)}, cwd=repo)
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_entrypoint_silent_on_invalid_json(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    r = subprocess.run(
        [sys.executable, str(HOOK_SRC)],
        input="this is not json",
        capture_output=True,
        text=True,
        cwd=repo,
        timeout=30,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == ""


@pytest.mark.parametrize("marker", hook.SKIP_MARKERS)
def test_entrypoint_silent_on_env_skip(tmp_path: Path, marker: str) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "app.py").write_text("x=1\n", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(HOOK_SRC)],
        input=json.dumps({"hook_event_name": "Stop", "stop_hook_active": False, "cwd": str(repo)}),
        capture_output=True,
        text=True,
        cwd=repo,
        env={**os.environ, marker: "1"},
        timeout=30,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == ""
