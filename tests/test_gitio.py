"""gitio acceptance: rename map, file@ref, working hashes, span oracle (W1.5)."""

from __future__ import annotations

import subprocess

from conftest import apply_three_change_commit, commit_all, write
from dorian import gitio
from dorian.model import sha256_hex


def test_changed_paths_and_rename_map(fixture_repo):
    base = gitio.head_ref(fixture_repo)
    apply_three_change_commit(fixture_repo)
    changed, renames = gitio.changed_paths(fixture_repo, base)
    assert renames == {"src/auth.py": "src/tokens.py"}
    assert "src/auth.py" in changed and "src/tokens.py" in changed
    assert "src/config.py" in changed and "src/routes.py" in changed
    assert "docs/design.md" not in changed


def test_changed_paths_sees_uncommitted_working_tree(fixture_repo):
    base = gitio.head_ref(fixture_repo)
    write(fixture_repo, "src/config.py", "TIMEOUT = 99\n")
    changed, _ = gitio.changed_paths(fixture_repo, base)
    assert changed == ["src/config.py"]


def test_file_at_ref_returns_prior_content(fixture_repo):
    base = gitio.head_ref(fixture_repo)
    apply_three_change_commit(fixture_repo)
    old = gitio.file_at_ref(fixture_repo, base, "src/config.py")
    assert old is not None and b"TIMEOUT = 30" in old
    assert gitio.file_at_ref(fixture_repo, base, "nope.py") is None


def test_working_hash_matches_span_oracle(fixture_repo):
    # oracle: sed -n '1,2p' equivalent on LF text
    sed = subprocess.run(
        ["sed", "-n", "1,2p", str(fixture_repo / "src/config.py")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.rstrip("\n")
    assert gitio.working_hash(fixture_repo, "src/config.py", "L1-2") == sha256_hex(sed.encode())
    assert gitio.working_hash(fixture_repo, "missing.py") is None


def test_span_at_ref(fixture_repo):
    base = gitio.head_ref(fixture_repo)
    write(fixture_repo, "src/config.py", "TIMEOUT = 10\n")
    commit_all(fixture_repo, "tune")
    assert gitio.span_at_ref(fixture_repo, base, "src/config.py", "L1-1") == "TIMEOUT = 30"
    assert gitio.span_at_ref(fixture_repo, base, "absent.py", None) is None


def test_actor_is_nonempty(fixture_repo):
    assert gitio.actor(fixture_repo) == "dorian-test" or gitio.actor(fixture_repo)
