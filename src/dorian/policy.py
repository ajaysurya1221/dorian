"""Checker execution policy: one place that decides whether a checker is allowed
to *execute code* on the machine running dorian.

Two checker shapes execute code rather than only reading files:
  - C4 ``pytest:<nodeid>``  — runs ``python -m pytest`` in a subprocess.
  - C5 ``shell:<command>``  — runs an arbitrary command in a subprocess.
Every other checker (C1 span, C3 path/symbol/string/regex, and the typed C5
data forms rowcount/schema/nullrate/domain/freshness/snapshot/reconcile) only
reads files in-process and never spawns a command.

``ExecutionPolicy`` is the single, central gate. It is consulted once, in
``checkers.base.run_checker``, before a checker runs. A blocked checker becomes
``Verdict.ERROR`` — never PASS and never FAIL: a checker that was refused
permission to run has *not* proven the claim true, and it has *not* proven the
claim false. ERROR is exactly the verdict the rest of the protocol already
fails-closed on: seal refuses to be born (``ERRORED_AT_SEAL``) and revalidate
folds it to ERRORED, never to a silent pass. This keeps the policy from ever
laundering a weak binding into confidence, and from ever marking a claim false.

This is NOT a sandbox. Allowed checkers still run with the caller's privileges.
The policy only decides *whether* the executable families run at all; it does
not constrain what an allowed checker may read or write. See
``docs/SECURITY_BOUNDARY.md``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dorian.model import CheckerSpec

# truthy environment fallbacks (the CLI flag and the env var compose with OR)
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def executable_kind(spec: CheckerSpec) -> str | None:
    """Classify a checker by whether it spawns a process. Returns the executable
    kind (``"pytest"`` or ``"shell"``) or ``None`` for a read-only checker.

    This is the single source of truth for "what executes"; the policy and the
    docs both derive from it, so a new executable family is gated by editing
    exactly one function.
    """
    if spec.type == "C4":
        return "pytest"
    if spec.type == "C5" and spec.program.partition(":")[0] == "shell":
        return "shell"
    return None


@dataclass(frozen=True)
class ExecutionPolicy:
    """Whether the executable checker families may run.

    Defaults allow everything — i.e. today's behavior, unchanged — so an
    existing caller that does not pass a policy is completely unaffected.

    - ``allow_exec=False`` (deny-exec) blocks BOTH C4 pytest and C5 shell.
    - ``allow_shell=False`` (deny-shell) blocks only C5 shell, leaving the
      narrower C4 pytest path available for callers that trust their test
      bindings but not arbitrary shell.
    """

    allow_exec: bool = True
    allow_shell: bool = True

    @classmethod
    def from_flags_and_env(
        cls, *, deny_exec: bool = False, deny_shell: bool = False
    ) -> ExecutionPolicy:
        """Build a policy from CLI flags OR-ed with their environment fallbacks
        (``DORIAN_DENY_EXEC`` / ``DORIAN_DENY_SHELL``). A flag or a truthy env var
        denies; deny-exec implies deny-shell. Only ``1``/``true``/``yes``/``on``
        (case-insensitive) are truthy — any other env value, including a typo like
        ``disable``, leaves execution ENABLED (fail-open on the env fallback), so
        the explicit flag is the primary, unambiguous control."""
        env_exec = os.environ.get("DORIAN_DENY_EXEC", "").strip().lower() in _TRUTHY
        env_shell = os.environ.get("DORIAN_DENY_SHELL", "").strip().lower() in _TRUTHY
        no_exec = deny_exec or env_exec
        no_shell = deny_shell or env_shell or no_exec
        return cls(allow_exec=not no_exec, allow_shell=not no_shell)

    def block_reason(self, spec: CheckerSpec) -> str | None:
        """Return a human-readable reason this checker is blocked, or ``None`` if
        it is allowed. The reason is surfaced as the ERROR detail so a blocked
        load-bearing claim is loud, not silent."""
        kind = executable_kind(spec)
        if kind == "pytest" and not self.allow_exec:
            return "blocked by execution policy: C4 pytest disabled (deny-exec)"
        if kind == "shell" and not self.allow_shell:
            mode = "deny-exec" if not self.allow_exec else "deny-shell"
            return f"blocked by execution policy: C5 shell disabled ({mode})"
        return None
