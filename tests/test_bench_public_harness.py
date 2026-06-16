"""End-to-end harness behavior on a tiny LOCAL git fixture (never clones a real repo).

Exercises the real seal -> mutate -> revalidate -> compare loop deterministically, keeps
ERROR distinct from BROKEN, honors --deny-exec as a fail-closed policy, and proves the
trigger-vs-truth ceiling (a body change is re-checked but a signature checker stays VERIFIED).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # bench/ is a repo-root package, not installed
    sys.path.insert(0, str(REPO_ROOT))

from bench import public_repos as pr  # noqa: E402

from dorian.policy import ExecutionPolicy  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "dorian-test",
    "GIT_AUTHOR_EMAIL": "test@dorian.local",
    "GIT_COMMITTER_NAME": "dorian-test",
    "GIT_COMMITTER_EMAIL": "test@dorian.local",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}

MOD_PY = "TIMEOUT = 30\n\n\ndef add(a, b):\n    return a + b\n"

CLAIMS_READY = {
    "schema_version": 1,
    "status": "benchmark-ready",
    "artifact": "change-note.md",
    "claims": [
        {
            "id": "add-sig",
            "text": "add takes parameters a and b",
            "kind": "behavior",
            "load_bearing": True,
            "anchor": None,
            "supports": [],
            "checkers": [{"type": "C3", "program": "py-signature:src/mod.py::add::a, b"}],
        },
        {
            "id": "timeout-const",
            "text": "the default timeout is 30",
            "kind": "quantity",
            "load_bearing": True,
            "anchor": None,
            "supports": [],
            "checkers": [{"type": "C3", "program": "py-const:src/mod.py::TIMEOUT::30"}],
        },
    ],
}

MUTATIONS = [
    pr.Mutation(
        "break-sig",
        "add-sig",
        "src/mod.py",
        "replace",
        "def add(a, b)",
        "def add(a, b, c)",
        "BROKEN",
    ),
    pr.Mutation(
        "break-const",
        "timeout-const",
        "src/mod.py",
        "replace",
        "TIMEOUT = 30",
        "TIMEOUT = 60",
        "BROKEN",
    ),
    pr.Mutation(
        "body-change", "add-sig", "src/mod.py", "replace", "return a + b", "return b + a", "TRUSTED"
    ),
]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        env={**GIT_ENV, "PATH": __import__("os").environ["PATH"]},
        check=True,
        capture_output=True,
    )


def _fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "checkout"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "mod.py").write_text(MOD_PY, encoding="utf-8")
    (repo / "change-note.md").write_text(
        "# change\n\nadd takes a, b; timeout is 30.\n", encoding="utf-8"
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")
    return repo


def _spec(needs_exec: bool = False) -> pr.RepoSpec:
    return pr.RepoSpec(
        name="fixture",
        url="local",
        frozen_sha="LOCAL",
        license="MIT",
        public=True,
        eligible=True,
        needs_exec=needs_exec,
    )


def test_fixture_run_truth_and_trigger_layers(tmp_path: Path) -> None:
    checkout = _fixture(tmp_path)
    result = pr.run_repo(
        _spec(),
        checkout,
        CLAIMS_READY,
        MUTATIONS,
        policy=ExecutionPolicy(),
        workdir=tmp_path / "work",
    )
    assert result["status"] == "PASS"
    assert result["claims_total"] == 2
    assert result["mutations_total"] == 3
    # truth layer: two BROKEN, one stays VERIFIED (TRUSTED) -> all match expectations
    tl = result["truth_layer"]
    assert tl["broken_expected"] == 2 and tl["broken_observed"] == 2
    assert tl["trusted_expected"] == 1 and tl["trusted_observed"] == 1
    assert tl["errored"] == 0
    # trigger layer: every mutation touches src/mod.py, so each target claim is re-checked
    assert result["trigger_layer"]["candidate_claims_checked"] == 3
    assert result["trigger_layer"]["claims_skipped"] == 0
    # the body-change mutation is the trigger-vs-truth ceiling: selected but VERIFIED
    body = next(r for r in result["results"] if r["mutation_id"] == "body-change")
    assert (
        body["selected"] is True and body["observed_state"] == "TRUSTED" and body["match"] is True
    )


def test_fixture_run_is_byte_stable(tmp_path: Path) -> None:
    checkout = _fixture(tmp_path)
    r1 = pr.run_repo(
        _spec(),
        checkout,
        CLAIMS_READY,
        MUTATIONS,
        policy=ExecutionPolicy(),
        workdir=tmp_path / "w1",
    )
    r2 = pr.run_repo(
        _spec(),
        checkout,
        CLAIMS_READY,
        MUTATIONS,
        policy=ExecutionPolicy(),
        workdir=tmp_path / "w2",
    )
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
    # no wall-clock timestamp leaks into the deterministic artifact
    assert "timestamp" not in json.dumps(r1) and "_at" not in json.dumps(r1)


def test_write_results_emits_json_and_jsonl(tmp_path: Path) -> None:
    checkout = _fixture(tmp_path)
    result = pr.run_repo(
        _spec(),
        checkout,
        CLAIMS_READY,
        MUTATIONS,
        policy=ExecutionPolicy(),
        workdir=tmp_path / "work",
    )
    out = tmp_path / "results"
    json_path, jsonl_path = pr.write_results(out, result)
    assert json_path.is_file() and jsonl_path.is_file()
    loaded = json.loads(json_path.read_text())
    assert loaded["status"] == "PASS"
    lines = [json.loads(ln) for ln in jsonl_path.read_text().splitlines() if ln.strip()]
    # one header event + one event per mutation result
    assert lines[0]["event"] == "repo"
    assert sum(1 for ln in lines if ln["event"] == "mutation") == 3


def test_draft_claims_yield_no_claims_not_a_number(tmp_path: Path) -> None:
    checkout = _fixture(tmp_path)
    draft = {**CLAIMS_READY, "status": "draft-human-review-required"}
    result = pr.run_repo(
        _spec(), checkout, draft, MUTATIONS, policy=ExecutionPolicy(), workdir=tmp_path / "work"
    )
    assert result["status"] == "NO_CLAIMS"
    assert result["results"] == []
    assert result["truth_layer"]["broken_observed"] == 0
    assert pr.is_benchmark_ready(CLAIMS_READY) is True
    assert pr.is_benchmark_ready(draft) is False


def test_generated_claims_cannot_be_benchmark_ready() -> None:
    # a 'generated'/'draft' status is never executable evidence, regardless of content
    for status in ("generated", "draft-human-review-required", "extracted", "", None):
        assert pr.is_benchmark_ready({"status": status, "claims": []}) is False


def test_c4_c5_claims_require_explicit_needs_exec(tmp_path: Path) -> None:
    checkout = _fixture(tmp_path)
    exec_claims = {
        "schema_version": 1,
        "status": "benchmark-ready",
        "artifact": "change-note.md",
        "claims": [
            {
                "id": "suite-passes",
                "text": "the test suite passes",
                "kind": "behavior",
                "load_bearing": True,
                "anchor": None,
                "supports": [],
                "checkers": [{"type": "C4", "program": "pytest:tests/test_x.py::test_y"}],
            }
        ],
    }
    # needs_exec defaults False -> a C4 claim must be refused
    with pytest.raises(pr.ManifestError, match="needs_exec"):
        pr.run_repo(
            _spec(needs_exec=False),
            checkout,
            exec_claims,
            [],
            policy=ExecutionPolicy(),
            workdir=tmp_path / "work",
        )


def test_needs_exec_repo_skipped_under_deny_exec(tmp_path: Path) -> None:
    """A needs_exec repo is SKIPPED under --deny-exec (matching the dry-run plan and
    manifest.v1.yaml), so a code-executing checker never folds to a spurious ERRORED ->
    false FAIL. The skip happens before any seal/clone, so no subprocess runs."""
    checkout = _fixture(tmp_path)
    exec_claims = {
        "schema_version": 1,
        "status": "benchmark-ready",
        "artifact": "change-note.md",
        "claims": [
            {
                "id": "suite-passes",
                "text": "the suite passes",
                "kind": "behavior",
                "load_bearing": True,
                "anchor": None,
                "supports": [],
                "checkers": [{"type": "C4", "program": "pytest:tests/test_x.py::test_y"}],
            }
        ],
    }
    muts = [
        pr.Mutation(
            "break",
            "suite-passes",
            "src/mod.py",
            "replace",
            "TIMEOUT = 30",
            "TIMEOUT = 60",
            "BROKEN",
        )
    ]
    result = pr.run_repo(
        _spec(needs_exec=True),
        checkout,
        exec_claims,
        muts,
        policy=pr.build_policy(deny_exec=True),
        workdir=tmp_path / "work",
    )
    assert result["status"] == "SKIPPED_DENY_EXEC"
    assert result["results"] == []  # not run -> no spurious FAIL


def test_deny_exec_runs_nonexec_repo_normally(tmp_path: Path) -> None:
    """deny-exec is supported and leaves a read-only (C3) repo undisturbed: nothing is
    blocked, so the structural mutations are scored exactly as without the flag."""
    checkout = _fixture(tmp_path)
    result = pr.run_repo(
        _spec(needs_exec=False),
        checkout,
        CLAIMS_READY,
        MUTATIONS,
        policy=pr.build_policy(deny_exec=True),
        workdir=tmp_path / "work",
    )
    assert result["status"] == "PASS"
    assert result["truth_layer"]["errored"] == 0


ERR_CLAIMS = {
    "schema_version": 1,
    "status": "benchmark-ready",
    "artifact": "change-note.md",
    "claims": [
        {
            "id": "add-sig",
            "text": "add takes parameters a and b",
            "kind": "behavior",
            "load_bearing": True,
            "anchor": None,
            "supports": [],
            "checkers": [{"type": "C3", "program": "py-signature:src/mod.py::add::a, b"}],
        }
    ],
}


def test_errored_is_distinct_from_broken(tmp_path: Path) -> None:
    """A mutation that makes the target file unparseable makes the checker ERROR (not FAIL).
    The harness records ERRORED, distinct from BROKEN (boundary 9) — no deny-exec needed."""
    checkout = _fixture(tmp_path)
    muts = [
        pr.Mutation(
            "unparseable",
            "add-sig",
            "src/mod.py",
            "replace",
            "return a + b",
            "return a + ",
            "ERRORED_EXPECTED",
        )
    ]
    result = pr.run_repo(
        _spec(needs_exec=False),
        checkout,
        ERR_CLAIMS,
        muts,
        policy=ExecutionPolicy(),
        workdir=tmp_path / "work",
    )
    rec = result["results"][0]
    assert rec["observed_state"] == "ERRORED"
    assert rec["observed_state"] != "BROKEN"
    assert result["truth_layer"]["errored"] == 1
    assert result["status"] == "PASS"  # ERRORED matched ERRORED_EXPECTED


# --- Phase 0.5: cached-checkout verification (fail closed on unverifiable cache) ---


def _make_git_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    (path / "f.txt").write_text("x\n", encoding="utf-8")
    _git(path, "init", "-q")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "c")
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _cache_spec(sha: str) -> pr.RepoSpec:
    # url points nowhere: a verified cache must be REUSED, never re-cloned over the network
    return pr.RepoSpec(
        name="humanize", url="https://invalid.invalid/none", frozen_sha=sha, license="MIT"
    )


def test_clone_or_reuse_reuses_valid_cache_at_expected_sha(tmp_path: Path) -> None:
    workdir = tmp_path / "work"
    sha = _make_git_repo(tmp_path / "_seed")
    cache = workdir / "checkouts" / f"humanize-{sha[:12]}"
    cache.parent.mkdir(parents=True)
    (tmp_path / "_seed").rename(cache)  # move the real checkout into the cache slot
    got = pr._clone_or_reuse(_cache_spec(sha), tmp_path, workdir)
    assert got == cache


def test_clone_or_reuse_wrong_sha_cache_fails_closed(tmp_path: Path) -> None:
    workdir = tmp_path / "work"
    _make_git_repo(tmp_path / "_seed")  # real HEAD != the wrong sha below
    wrong = "0" * 40
    cache = workdir / "checkouts" / f"humanize-{wrong[:12]}"
    cache.parent.mkdir(parents=True)
    (tmp_path / "_seed").rename(cache)
    with pytest.raises(pr.ManifestError, match="expected frozen"):
        pr._clone_or_reuse(_cache_spec(wrong), tmp_path, workdir)


def test_clone_or_reuse_non_git_cache_fails_closed(tmp_path: Path) -> None:
    workdir = tmp_path / "work"
    sha = "a" * 40
    cache = workdir / "checkouts" / f"humanize-{sha[:12]}"
    cache.mkdir(parents=True)
    (cache / "stuff.txt").write_text("not a git repo\n", encoding="utf-8")
    with pytest.raises(pr.ManifestError, match="not a git"):
        pr._clone_or_reuse(_cache_spec(sha), tmp_path, workdir)
