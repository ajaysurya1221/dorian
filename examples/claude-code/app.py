"""Tiny example module for the dorian + Claude Code walkthrough.

A coding agent just claimed it added a login handler with a 30-second timeout.
The `claims.json` next to this file binds those two claims to deterministic
checkers; `dorian verify` seals them into `change-note.md.warrant`.
"""

LOGIN_TIMEOUT = 30  # seconds


def login_handler(request):
    """Handle a login request, enforcing the login timeout."""
    return _authenticate(request, timeout=LOGIN_TIMEOUT)


def _authenticate(request, timeout):
    return {"ok": True, "timeout": timeout}
