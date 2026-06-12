"""Checker registry. Checker modules register a callable per CheckerSpec.type.

A registered checker is `fn(ctx: CheckContext, spec: CheckerSpec) -> CheckResult`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dorian.checkers.base import CheckContext, CheckResult
    from dorian.model import CheckerSpec

_REGISTRY: dict[str, Callable[[CheckContext, CheckerSpec], CheckResult]] = {}


class registry:
    @staticmethod
    def register(checker_type: str, fn: Callable) -> None:
        _REGISTRY[checker_type] = fn

    @staticmethod
    def get(checker_type: str) -> Callable | None:
        _ensure_loaded()
        return _REGISTRY.get(checker_type)


def _ensure_loaded() -> None:
    """Import checker modules so they self-register (idempotent)."""
    import contextlib
    from importlib import import_module

    for mod in (
        "dorian.checkers.c1_span",
        "dorian.checkers.c3_ref",
        "dorian.checkers.c4_test",
        "dorian.checkers.c5_data",
    ):
        # module not implemented yet (build-time) or optional engine missing
        with contextlib.suppress(ImportError):
            import_module(mod)
