"""Integration tests for the C4 import-aware binding benchmark.

Pins the EVIDENCE properties, not just that it runs: the pre-fix (test-file-only)
watcher misses implementation-only edits while the import-aware watcher selects
them; ambiguity is an honest skip (not credited); the verdict layer tracks the
test (broken impl -> BROKEN, benign impl -> not BROKEN) with zero false BROKEN
from a behavior-preserving edit; the summary is deterministic and content-safe.

Slow: the verdict layer seals + revalidates with real pytest (C4) subprocesses.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # bench/ is a repo-root package, not installed
    sys.path.insert(0, str(REPO_ROOT))

from bench import c4_import_binding as bench  # noqa: E402

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def _interpreter_on_path():
    # the verdict layer spawns `python -m pytest`; make pytest resolvable on PATH
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]


@pytest.fixture(scope="module")
def run(tmp_path_factory, _interpreter_on_path) -> tuple[dict, list[dict]]:
    ws = tmp_path_factory.mktemp("c4ib-bench")
    return bench.run_benchmark(ws, quick=True)


@pytest.fixture(scope="module")
def summary(run) -> dict:
    return run[0]


def test_schema_and_composition(summary: dict) -> None:
    assert summary["schema"] == bench.SCHEMA
    comp = summary["composition"]
    assert comp["direct_import_scenarios"] >= 4
    assert comp["ambiguous_skip_scenarios"] >= 1
    assert comp["verdict_scenarios"] == 2


def test_selection_recall_is_the_headline_improvement(summary: dict) -> None:
    sel = summary["selection_layer"]
    # the gap this patch closes: the pre-fix test-file-only watcher selects NONE of the
    # implementation-only edits; the import-aware watcher selects ALL direct-import ones.
    assert sel["test_file_watcher_recall_direct"] == 0.0
    assert sel["import_aware_watcher_recall_direct"] == 1.0


def test_ambiguous_import_is_an_honest_skip(summary: dict) -> None:
    # a wrong watch is a false alarm, so an ambiguous import (two tracked tail matches) is
    # left unbound — selected 0 times, scored as a miss rather than credited as a win.
    assert summary["selection_layer"]["import_aware_selected_ambiguous"] == 0


def test_verdict_layer_tracks_the_test_not_the_file_change(summary: dict) -> None:
    v = summary["verdict_layer"]
    # selection is not alarm: of the selected+rechecked claims, the verdict matches the test
    # (broken impl -> BROKEN, benign impl -> not BROKEN) and a benign edit NEVER alarms.
    assert v["alarm_match"] == "2/2"
    assert v["false_broken_from_benign_edit"] == 0


def test_deterministic_rerun_is_byte_identical(tmp_path_factory, _interpreter_on_path) -> None:
    a = bench.run_benchmark(tmp_path_factory.mktemp("c4ib-a"))[0]
    b = bench.run_benchmark(tmp_path_factory.mktemp("c4ib-b"))[0]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_no_forbidden_overclaim_wording(summary: dict) -> None:
    prose = (bench._render_md(summary) + " " + summary["limits"]).lower()
    for word in bench.FORBIDDEN_WORDS:
        assert word not in prose, f"overclaim wording in benchmark output: {word!r}"


def test_records_are_content_free_paths_only(run) -> None:
    # resolved deps are repo-relative paths, never source content
    _summary, records = run
    for r in records:
        for dep in r.get("resolved_deps", []):
            assert dep.endswith(".py")
            assert "\n" not in dep and "def " not in dep
