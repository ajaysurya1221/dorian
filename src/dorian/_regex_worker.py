"""Isolated regex matcher for C3 ``regex:`` checks.

Run in a separate (spawned) process so a catastrophic-backtracking pattern can be
stopped by a wall-clock timeout. A thread cannot do this: a single C-level
``re.search()`` never yields the GIL back to the interpreter, so neither a timer
thread nor a Python-level signal handler runs until the match returns. A child
process, by contrast, can be killed by the OS mid-match (SIGTERM/SIGKILL).

Kept deliberately import-light (stdlib ``re`` only, no dorian imports) so the
``spawn`` start method — which re-imports this module in the child — stays cheap.
"""

from __future__ import annotations

import re

# result.value sentinels (signed char, typecode "b"): the parent seeds -1 and
# only the worker overwrites it, so -1 survives iff the process was killed.
MATCH = 1
NO_MATCH = 0
WORKER_ERROR = -2


def search_worker(pattern: str, flags: int, text: str, result) -> None:
    """Set ``result.value`` to MATCH / NO_MATCH, or WORKER_ERROR on an unexpected
    failure (the pattern is pre-compiled in the parent, so this is defensive)."""
    try:
        result.value = MATCH if re.search(pattern, text, flags) else NO_MATCH
    except Exception:
        result.value = WORKER_ERROR
