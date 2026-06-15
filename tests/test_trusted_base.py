"""Trusted-base checker-source mode (WP7): `revalidate --checker-source base`.

The exploit class: the Action runs the checker programs found in the CHECKED-OUT
(PR/head) `.warrant` sidecars. On a forked PR, the attacker controls those sidecars,
so a PR-added or PR-modified C4 `pytest:`/C5 `shell:` checker would execute attacker
code on the runner, and a rewritten non-executable checker could self-attest a green
verdict. `--checker-source base` resolves every claim's checker SPEC from the trusted
base ref instead, runs it against the PR-head SOURCES, and fails closed when the base
spec cannot be trusted.

This is the security matrix from docs/TRUSTED_BASE_ACTION_DESIGN.md §6. Each
"executed?" case proves it with a filesystem side effect (a sentinel `touch`): the
sentinel must NOT appear under base mode. It is NOT a sandbox — a base-approved
pytest checker can still execute head code — which the design and these tests state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import commit_all, git, write
from dorian import cli
from dorian.model import (
    CheckerSpec,
    Claim,
    FoldPolicy,
    ProducedBy,
    ReadSet,
    Warrant,
    sha256_hex,
)
from dorian.policy import ExecutionPolicy
from dorian.revalidate import revalidate
from dorian.seal import seal_artifact

PB = ProducedBy(runner="manual", captured_at="2026-01-01T00:00:00Z")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "src/config.py", "TIMEOUT = 30\n")
    write(repo, "src/auth.py", "def verify_token(t):\n    return bool(t)\n")
    write(repo, "note.md", "# note\n\nThe timeout is 30.\n")
    commit_all(repo, "init")  # seal needs a resolvable HEAD
    return repo


def _forge_head_warrant(repo: Path, artifact_uri: str, claims: list[Claim]) -> Warrant:
    """Write a content-addressed `.warrant` to the working tree directly, simulating a
    sidecar a forked PR fully controls (a real attacker computes the same valid id)."""
    data = (repo / artifact_uri).read_bytes()
    w = Warrant.create(
        artifact_uri=artifact_uri,
        artifact_hash=sha256_hex(data),
        git_ref=git(repo, "rev-parse", "HEAD"),
        produced_by=PB,
        read_set=(),
        claims=tuple(claims),
        fold_policy=FoldPolicy(),
        sealed_at="2026-01-01T00:00:00Z",
    )
    w.dump(w.sidecar_path(repo))
    return w


def _claim(cid: str, program: str, ctype: str = "C3", *, watch=(), load_bearing=True) -> Claim:
    return Claim(
        id=cid,
        text=f"claim {cid}",
        kind="reference",
        load_bearing=load_bearing,
        checkers=(CheckerSpec(type=ctype, program=program, watch=tuple(watch)),),
    )


# --- matrix #2: a base-unchanged checker still runs and catches real drift ----


def test_base_unchanged_checker_catches_drift(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    seal_artifact(
        repo,
        "note.md",
        ReadSet(entries=(), produced_by=PB),
        [_claim("t", r"regex:src/config.py::TIMEOUT\s*=\s*30")],
    )
    base = commit_all(repo, "base: sealed warrant")
    write(repo, "src/config.py", "TIMEOUT = 10\n")  # head drift
    res = revalidate(repo, since=base, checker_source="base")
    assert {cid for _, cid, _ in res.broken} == {"t"}  # base spec ran, caught the drift
    assert res.exit_code == cli.EXIT_REVOKED


# --- matrix #3: a PR-ADDED executable checker is never executed ---------------


def test_pr_added_shell_checker_does_not_execute(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    # base warrant carries only a benign non-executing claim
    seal_artifact(
        repo, "note.md", ReadSet(entries=(), produced_by=PB), [_claim("ok", "path:src/config.py")]
    )
    base = commit_all(repo, "base")

    base_sentinel = tmp_path / "BASE_PWNED"
    head_sentinel = tmp_path / "HEAD_PWNED"
    write(repo, "src/auth.py", "def verify_token(t):\n    return t\n")  # head source change

    def forge(sentinel: Path) -> None:
        _forge_head_warrant(
            repo,
            "note.md",
            [
                _claim("ok", "path:src/config.py"),
                _claim("evil", f"shell:touch {sentinel}", "C5", watch=("src/auth.py",)),
            ],
        )

    # base mode: the PR-added 'evil' claim is absent on base -> skipped, never executed
    forge(base_sentinel)
    res = revalidate(repo, since=base, checker_source="base")
    assert not base_sentinel.exists(), "PR-added shell checker MUST NOT execute under base mode"
    assert "evil" in {cid for _, cid, _ in res.errored}

    # head mode (the unsafe default for forks): proves the checker is genuinely live
    forge(head_sentinel)
    revalidate(repo, since=base, checker_source="head")
    assert head_sentinel.exists(), "sanity: head mode does run the PR's shell checker"


# --- matrix #4: a PR-MODIFIED executable checker is never executed ------------


def test_pr_modified_executable_checker_uses_base_spec(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    seal_artifact(
        repo,
        "note.md",
        ReadSet(entries=(), produced_by=PB),
        [_claim("c", r"regex:src/config.py::TIMEOUT\s*=\s*30", watch=("src/config.py",))],
    )
    base = commit_all(repo, "base: regex checker")

    sentinel = tmp_path / "MOD_PWNED"
    write(repo, "src/config.py", "TIMEOUT = 10\n")  # base regex would FAIL on this
    write(repo, "src/auth.py", "def verify_token(t):\n    return t\n")
    # PR rewrites claim 'c' from the base regex to a shell command
    _forge_head_warrant(
        repo, "note.md", [_claim("c", f"shell:touch {sentinel}", "C5", watch=("src/auth.py",))]
    )

    res = revalidate(repo, since=base, checker_source="base")
    assert not sentinel.exists(), "PR-modified executable checker MUST NOT execute"
    assert {cid for _, cid, _ in res.broken} == {"c"}  # the BASE regex ran (and failed)
    assert any("changed on PR" in n for n in res.notes)  # trust-root change surfaced


# --- trust-root change: a PR-weakened NON-executable checker -----------------


def test_pr_weakened_nonexec_checker_is_reported_and_base_spec_wins(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    seal_artifact(
        repo,
        "note.md",
        ReadSet(entries=(), produced_by=PB),
        [_claim("c", r"regex:src/config.py::TIMEOUT\s*=\s*30", watch=("src/config.py",))],
    )
    base = commit_all(repo, "base: strict regex")
    write(repo, "src/config.py", "TIMEOUT = 10\n")  # the fact is now false
    # PR weakens the checker to a mere existence check that always passes
    _forge_head_warrant(
        repo, "note.md", [_claim("c", "path:src/config.py", watch=("src/config.py",))]
    )

    # head mode: the weakening attack succeeds — the existence check passes
    head = revalidate(repo, since=base, checker_source="head")
    assert not head.broken and {cid for _, cid, _ in head.passed} == {"c"}

    # base mode: the base regex spec wins -> BROKEN, and the spec change is surfaced
    res = revalidate(repo, since=base, checker_source="base")
    assert {cid for _, cid, _ in res.broken} == {"c"}
    assert any("changed on PR" in n for n in res.notes)


# --- matrix #6: a missing/unreadable base sidecar fails closed ----------------


def test_missing_base_sidecar_fails_closed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")  # base has the source but NO warrant for note.md
    write(repo, "src/auth.py", "def verify_token(t):\n    return t\n")
    sentinel = tmp_path / "NOBASE_PWNED"
    _forge_head_warrant(
        repo, "note.md", [_claim("c", f"shell:touch {sentinel}", "C5", watch=("src/auth.py",))]
    )
    res = revalidate(repo, since=base, checker_source="base")
    assert not sentinel.exists(), "no base sidecar -> must not execute the PR checker"
    assert "c" in {cid for _, cid, _ in res.errored}
    assert res.exit_code == cli.EXIT_ERRORED  # ERRORED, never BROKEN, never green


# --- deny-exec composes with base mode ----------------------------------------


def test_base_mode_with_deny_shell_errors_base_executable(tmp_path: Path) -> None:
    """Even a BASE-approved executable checker is blocked under deny-exec/deny-shell:
    the two controls compose. base mode picks the trusted spec; the policy still
    refuses to run it -> ERRORED, never executed."""
    repo = _repo(tmp_path)
    sentinel = tmp_path / "DENY_PWNED"
    seal_artifact(
        repo,
        "note.md",
        ReadSet(entries=(), produced_by=PB),
        [_claim("c", f"shell:touch {sentinel}", "C5", watch=("src/config.py",))],
    )
    sentinel.unlink(missing_ok=True)  # seal-time run created it; reset for the assertion
    base = commit_all(repo, "base: shell checker")
    write(repo, "src/config.py", "TIMEOUT = 31\n")
    res = revalidate(
        repo,
        since=base,
        checker_source="base",
        policy=ExecutionPolicy(allow_exec=True, allow_shell=False),
    )
    assert not sentinel.exists()
    assert "c" in {cid for _, cid, _ in res.errored}


# --- head is the default; base requires --since -------------------------------


def test_head_is_default_and_unchanged(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    seal_artifact(
        repo,
        "note.md",
        ReadSet(entries=(), produced_by=PB),
        [_claim("t", r"regex:src/config.py::TIMEOUT\s*=\s*30")],
    )
    base = commit_all(repo, "base")
    write(repo, "src/config.py", "TIMEOUT = 10\n")
    default = revalidate(repo, since=base)
    head = revalidate(repo, since=base, checker_source="head")
    assert {c for _, c, _ in default.broken} == {c for _, c, _ in head.broken} == {"t"}
    assert default.notes == [] and head.notes == []


def test_base_mode_requires_since(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    changed = repo / "changed.txt"
    changed.write_text("src/config.py\n", encoding="utf-8")
    with pytest.raises(ValueError, match="base"):
        revalidate(repo, changed_paths_file=changed, checker_source="base")


def test_cli_base_without_since_is_usage_error(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    changed = repo / "changed.txt"
    changed.write_text("src/config.py\n", encoding="utf-8")
    rc = cli.main(
        [
            "--repo",
            str(repo),
            "revalidate",
            "--changed-paths",
            str(changed),
            "--checker-source",
            "base",
        ]
    )
    assert rc == cli.EXIT_USAGE


def test_cli_env_fallback_selects_base(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    seal_artifact(
        repo,
        "note.md",
        ReadSet(entries=(), produced_by=PB),
        [_claim("t", r"regex:src/config.py::TIMEOUT\s*=\s*30", watch=("src/config.py",))],
    )
    base = commit_all(repo, "base")
    write(repo, "src/config.py", "TIMEOUT = 10\n")
    monkeypatch.setenv("DORIAN_CHECKER_SOURCE", "base")
    rc = cli.main(["--repo", str(repo), "revalidate", "--since", base])
    assert rc == cli.EXIT_REVOKED  # base spec ran and caught the drift
