"""C1 span-anchor checker acceptance matrix (content-relocatable).

Entries are hashed BEFORE mutating the repo, then the working tree drifts and
check_c1 must classify: unmoved, relocated (moved/renamed), changed (FAIL),
gone (FAIL), or unverifiable (ERROR).
"""

from __future__ import annotations

from pathlib import Path

from conftest import AUTH_PY, git, write
from dorian import gitio
from dorian.checkers import registry
from dorian.checkers.base import CheckContext, Verdict, run_checker
from dorian.checkers.c1_span import check_c1
from dorian.model import CheckerSpec, Claim, ReadSetEntry

SELECTOR = "L4-7"  # verify_token(): the RS256 span in src/auth.py
SPEC = CheckerSpec(type="C1", program="r1")

# minor paraphrase of the span's docstring (same meaning, ~0.96 similarity)
PARAPHRASED = AUTH_PY.replace(
    '"""Verify an RS256-signed JWT."""', '"""Verify the RS256-signed JWT token."""'
)

# rewritten meaning: same signature, contradicting body
REWRITTEN = AUTH_PY.replace(
    '    """Verify an RS256-signed JWT."""\n    algo = "RS256"\n    return _check(token, algo)',
    '    """Trust the gateway; callers are pre-authenticated upstream."""\n'
    "    del token\n"
    "    return True",
)


def entry_for(repo: Path, version: str | None = None) -> ReadSetEntry:
    """Capture-time read-set entry for the RS256 span (call before mutating)."""
    return ReadSetEntry(
        id="r1",
        uri="src/auth.py",
        selector=SELECTOR,
        hash=gitio.working_hash(repo, "src/auth.py", SELECTOR),
        version=version or gitio.head_ref(repo),
    )


def ctx_for(
    repo: Path,
    entry: ReadSetEntry,
    rename_map: dict[str, str] | None = None,
    enable_c2lite: bool = False,
) -> CheckContext:
    claim = Claim(
        id="cl1",
        text="token verification uses RS256",
        kind="fact",
        load_bearing=True,
        supports=("r1",),
        checkers=(SPEC,),
    )
    return CheckContext(
        repo=repo,
        claim=claim,
        supports=[entry],
        rename_map=rename_map or {},
        enable_c2lite=enable_c2lite,
    )


def test_c1_is_registered():
    assert registry.get("C1") is check_c1


def test_unmoved_span_passes(fixture_repo):
    res = check_c1(ctx_for(fixture_repo, entry_for(fixture_repo)), SPEC)
    assert res.verdict is Verdict.PASS
    assert not res.relocated


def test_moved_within_file_passes_relocated(fixture_repo):
    entry = entry_for(fixture_repo)
    moved = AUTH_PY.replace('"""Auth helpers."""\n', '"""Auth helpers."""\n\n# nb\n# nb\n')
    write(fixture_repo, "src/auth.py", moved)
    res = check_c1(ctx_for(fixture_repo, entry), SPEC)
    assert res.verdict is Verdict.PASS
    assert res.relocated
    assert res.detail == "anchor_moved"


def test_renamed_file_passes_relocated(fixture_repo):
    entry = entry_for(fixture_repo)
    git(fixture_repo, "mv", "src/auth.py", "src/tokens.py")
    ctx = ctx_for(fixture_repo, entry, rename_map={"src/auth.py": "src/tokens.py"})
    res = check_c1(ctx, SPEC)
    assert res.verdict is Verdict.PASS
    assert res.relocated


def test_edited_span_fails(fixture_repo):
    entry = entry_for(fixture_repo)
    write(fixture_repo, "src/auth.py", AUTH_PY.replace("RS256", "HS256"))
    res = check_c1(ctx_for(fixture_repo, entry), SPEC)
    assert res.verdict is Verdict.FAIL
    assert res.detail == "span_changed_or_removed"


def test_deleted_file_fails_file_gone(fixture_repo):
    entry = entry_for(fixture_repo)
    (fixture_repo / "src/auth.py").unlink()
    res = check_c1(ctx_for(fixture_repo, entry), SPEC)
    assert res.verdict is Verdict.FAIL
    assert res.detail == "file_gone"


def test_unreachable_version_is_error_not_fail(fixture_repo):
    entry = entry_for(fixture_repo, version="0" * 40)
    write(fixture_repo, "src/auth.py", AUTH_PY.replace('algo = "RS256"', 'algo = "HS256"'))
    res = check_c1(ctx_for(fixture_repo, entry), SPEC)
    assert res.verdict is Verdict.ERROR
    assert res.detail == "original_unreachable"


def test_missing_support_entry_is_error(fixture_repo):
    entry = entry_for(fixture_repo)
    res = check_c1(ctx_for(fixture_repo, entry), CheckerSpec(type="C1", program="nope"))
    assert res.verdict is Verdict.ERROR
    assert "support entry not found" in res.detail


def test_paraphrase_fails_without_c2lite(fixture_repo):
    entry = entry_for(fixture_repo)
    write(fixture_repo, "src/auth.py", PARAPHRASED)
    res = check_c1(ctx_for(fixture_repo, entry), SPEC)
    assert res.verdict is Verdict.FAIL
    assert res.detail == "span_changed_or_removed"


def test_paraphrase_passes_with_c2lite(fixture_repo):
    entry = entry_for(fixture_repo)
    write(fixture_repo, "src/auth.py", PARAPHRASED)
    res = check_c1(ctx_for(fixture_repo, entry, enable_c2lite=True), SPEC)
    assert res.verdict is Verdict.PASS
    assert res.relocated
    assert res.detail == "c2lite"


def test_rewritten_meaning_fails_even_with_c2lite(fixture_repo):
    entry = entry_for(fixture_repo)
    write(fixture_repo, "src/auth.py", REWRITTEN)
    res = check_c1(ctx_for(fixture_repo, entry, enable_c2lite=True), SPEC)
    assert res.verdict is Verdict.FAIL
    assert res.detail == "span_changed_or_removed"


def whole_file_entry(repo: Path) -> ReadSetEntry:
    """A selector=None (whole-file) read-set entry for src/auth.py."""
    return ReadSetEntry(
        id="r1",
        uri="src/auth.py",
        selector=None,
        hash=gitio.working_hash(repo, "src/auth.py"),
        version=gitio.head_ref(repo),
    )


def test_whole_file_entry_unmoved_passes(fixture_repo):
    res = check_c1(ctx_for(fixture_repo, whole_file_entry(fixture_repo)), SPEC)
    assert res.verdict is Verdict.PASS
    assert not res.relocated


def test_whole_file_entry_edited_fails(fixture_repo):
    entry = whole_file_entry(fixture_repo)
    write(fixture_repo, "src/auth.py", AUTH_PY.replace("RS256", "HS256"))
    res = check_c1(ctx_for(fixture_repo, entry), SPEC)
    assert res.verdict is Verdict.FAIL
    assert res.detail == "span_changed_or_removed"


def hostile_entry(uri: str) -> ReadSetEntry:
    """An entry whose uri points outside the repo (hostile .warrant sidecar)."""
    return ReadSetEntry(id="r1", uri=uri, selector=None, hash="sha256:bogus", version="0" * 40)


def test_dotdot_uri_is_error_bad_program(fixture_repo):
    (fixture_repo.parent / "outside.txt").write_text("secret\n")
    res = check_c1(ctx_for(fixture_repo, hostile_entry("../outside.txt")), SPEC)
    assert res.verdict is Verdict.ERROR
    assert res.detail == "bad_program"


def test_absolute_uri_is_error_bad_program(fixture_repo):
    outside = fixture_repo.parent / "outside.txt"
    outside.write_text("secret\n")
    res = check_c1(ctx_for(fixture_repo, hostile_entry(str(outside))), SPEC)
    assert res.verdict is Verdict.ERROR
    assert res.detail == "bad_program"


def test_rename_map_escaping_repo_is_error_bad_program(fixture_repo):
    """Without the guard this would PASS: the outside copy hash-matches the entry."""
    (fixture_repo.parent / "outside.py").write_text(AUTH_PY)
    entry = entry_for(fixture_repo)
    ctx = ctx_for(fixture_repo, entry, rename_map={"src/auth.py": "../outside.py"})
    res = check_c1(ctx, SPEC)
    assert res.verdict is Verdict.ERROR
    assert res.detail == "bad_program"


def test_none_version_is_error_original_unreachable(fixture_repo):
    entry = ReadSetEntry(
        id="r1",
        uri="src/auth.py",
        selector=SELECTOR,
        hash=gitio.working_hash(fixture_repo, "src/auth.py", SELECTOR),
        version=None,
    )
    write(fixture_repo, "src/auth.py", AUTH_PY.replace("RS256", "HS256"))
    res = check_c1(ctx_for(fixture_repo, entry), SPEC)
    assert res.verdict is Verdict.ERROR
    assert res.detail == "original_unreachable"


def test_malformed_selector_is_error_via_dispatch(fixture_repo):
    """parse_selector's ValueError must surface as ERROR through run_checker."""
    for selector in ("L7-4", "garbage"):
        entry = ReadSetEntry(
            id="r1",
            uri="src/auth.py",
            selector=selector,
            hash="sha256:bogus",
            version=gitio.head_ref(fixture_repo),
        )
        res = run_checker(ctx_for(fixture_repo, entry), 0)
        assert res.verdict is Verdict.ERROR


def test_dirty_capture_out_of_range_span_is_error_not_pass(fixture_repo):
    """Dirty-tree capture: the selector covers appended lines absent at HEAD, so
    the ref-resolved span is empty and inconsistent with entry.hash. Must be
    ERROR — an empty original under c2lite would otherwise match any blank line."""
    write(fixture_repo, "src/auth.py", AUTH_PY + "# extra\n# extra2\n")
    entry = ReadSetEntry(
        id="r1",
        uri="src/auth.py",
        selector="L12-13",  # the appended lines; out of range at HEAD
        hash=gitio.working_hash(fixture_repo, "src/auth.py", "L12-13"),
        version=gitio.head_ref(fixture_repo),  # HEAD predates the appended lines
    )
    write(fixture_repo, "src/auth.py", AUTH_PY + "# changed\n# lines\n")
    res = check_c1(ctx_for(fixture_repo, entry, enable_c2lite=True), SPEC)
    assert res.verdict is Verdict.ERROR
    assert res.detail == "capture_inconsistent"
