#!/usr/bin/env python3
"""Dorian claim-warrants Stop hook — reminder-only, opt-in.

When a Claude Code turn ends (the ``Stop`` event), this hook may inject a short
reminder asking Claude to draft Dorian *claim warrants* for the checkable facts
in its summary — config values, signatures/defaults, constants, references — via
the ``/dorian-claim-warrants`` skill.

It is **reminder-only**. It returns ``hookSpecificOutput.additionalContext`` (a
soft nudge Claude reads on its next request); it NEVER returns ``decision: block``,
so it cannot loop or trap the agent. It also:

- never runs ``dorian verify``, tests, or any project code;
- never writes files;
- only ever shells out to read-only ``git status`` to see whether anything
  changed (a VCS query, not project execution);
- fails open: any error → stay silent and exit 0 (it must never break a turn).

Skip it for a turn by setting any of these env vars (or putting the marker in the
final message): ``DORIAN_CLAIM_WARRANTS_SKIP``, ``NO_DORIAN_CLAIM_WARRANTS``,
``DORIAN_RECEIPTS_SKIP``, ``NO_DORIAN_RECEIPTS``.

Install: copy to ``.claude/hooks/`` and register under ``hooks.Stop`` in your
project ``.claude/settings.json`` (see the review-first settings example). The
hook is OFF until you add that entry — scaffolding the file does not enable it.

Stdlib only. Tested by ``tests/test_claim_warrants_hook.py``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

# Env vars (or final-message markers) that suppress the reminder for one turn.
SKIP_MARKERS = (
    "DORIAN_CLAIM_WARRANTS_SKIP",
    "NO_DORIAN_CLAIM_WARRANTS",
    "DORIAN_RECEIPTS_SKIP",
    "NO_DORIAN_RECEIPTS",
)

# A change is "relevant" (worth a claim-warrant reminder) when a code/config file
# moved — the families Dorian's checkers can falsify. Docs-only churn is excluded
# to keep the nudge quiet; the user can still invoke the skill by hand.
RELEVANT_SUFFIXES = (
    ".py",
    ".pyi",
    ".toml",
    ".cfg",
    ".ini",
    ".json",
    ".yaml",
    ".yml",
    ".txt",
    ".lock",
)

# Final-message phrasings that mean "nothing to warrant" — suppress the nudge even
# when files moved (e.g. a formatting-only or investigation turn).
NO_CHANGE_PHRASES = (
    "no code change",
    "no code changes",
    "no changes were made",
    "did not change any",
    "research only",
    "investigation only",
    "read-only",
)

REMINDER = (
    "Before ending: consider creating Dorian claim warrants for the checkable "
    "facts in your summary. Invoke /dorian-claim-warrants. Draft only checkable "
    "claims (config values, signatures/defaults, constants, file/symbol "
    "references); leave vague prose ('cleaner', 'faster', 'refactored') out. "
    "Dorian verify is the deterministic proof step — the skill only drafts; run "
    "it with --strength-gate=fail --binding-gate=warn. A claim is not verified "
    "until dorian verify exits 0 and writes a .warrant."
)


def load_input(stdin_text: str) -> dict:
    """Parse the hook stdin JSON. Invalid/empty input → ``{}`` (caller no-ops)."""
    try:
        data = json.loads(stdin_text)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def skip_markers_present(env: dict, message: str) -> bool:
    """True if a skip marker is set as an env var or appears in the final message."""
    for marker in SKIP_MARKERS:
        if env.get(marker):
            return True
        if marker in message:
            return True
    return False


def changed_paths(cwd: str) -> list[str] | None:
    """Repo-relative paths with uncommitted changes, via read-only ``git status``.

    Returns ``None`` when ``cwd`` is not a git work tree or git is unavailable —
    the caller treats that as "no signal, stay silent". Never raises.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", cwd or ".", "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None  # not a git repo (status exits non-zero) → no signal
    paths: list[str] = []
    for line in proc.stdout.splitlines():
        # porcelain v1: 'XY <path>' or 'XY <old> -> <new>'; take the final path.
        entry = line[3:] if len(line) > 3 else ""
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        entry = entry.strip().strip('"')
        if entry:
            paths.append(entry)
    return paths


def has_relevant_change(paths: list[str]) -> bool:
    return any(p.lower().endswith(RELEVANT_SUFFIXES) for p in paths)


def already_has_warrant_artifacts(paths: list[str]) -> bool:
    """True if the diff already contains claim-warrant artifacts (the work is done)."""
    for p in paths:
        low = p.lower()
        if low.endswith(".warrant"):
            return True
        if "docs/changes/" in low and low.endswith(".claims.json"):
            return True
    return False


def last_assistant_message(payload: dict) -> str:
    """Best-effort final assistant text.

    Prefers a ``last_assistant_message`` field if the runtime supplies one (e.g.
    SubagentStop); otherwise parses the JSONL at ``transcript_path`` from the end
    and returns the most recent assistant text block. Any error → ``""``.
    """
    direct = payload.get("last_assistant_message")
    if isinstance(direct, str) and direct:
        return direct
    path = payload.get("transcript_path")
    if not isinstance(path, str) or not path:
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return ""
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        text = _assistant_text(obj)
        if text:
            return text
    return ""


def _assistant_text(obj: dict) -> str:
    """Extract assistant text from one transcript record, or ``""`` if it is not
    an assistant text turn. Tolerant of shape drift across transcript versions."""
    if not isinstance(obj, dict):
        return ""
    msg = obj.get("message", obj)
    role = obj.get("role") or (msg.get("role") if isinstance(msg, dict) else None)
    kind = obj.get("type")
    if role != "assistant" and kind != "assistant":
        return ""
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            b["text"]
            for b in content
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        ]
        return "\n".join(parts).strip()
    return ""


def message_says_no_change(message: str) -> bool:
    low = message.lower()
    return any(phrase in low for phrase in NO_CHANGE_PHRASES)


def should_remind(payload: dict, env: dict) -> bool:
    """The full gate. True only when a reminder is warranted; never raises."""
    if payload.get("hook_event_name") != "Stop":
        return False
    if payload.get("stop_hook_active"):
        return False  # already continuing from a stop hook → never re-fire
    if skip_markers_present(env, ""):
        return False
    paths = changed_paths(str(payload.get("cwd") or env.get("CLAUDE_PROJECT_DIR") or "."))
    if paths is None:  # not a git repo / git unavailable
        return False
    if not has_relevant_change(paths):
        return False
    if already_has_warrant_artifacts(paths):
        return False
    message = last_assistant_message(payload)
    if skip_markers_present(env, message):
        return False
    # remind unless the final message explicitly says nothing was changed
    return not (message and message_says_no_change(message))


def reminder_output() -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": REMINDER,
        }
    }


def main() -> int:
    try:
        payload = load_input(sys.stdin.read())
        if should_remind(payload, dict(os.environ)):
            sys.stdout.write(json.dumps(reminder_output()))
    except Exception:  # a hook must never break the turn; fail open and stay silent.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
