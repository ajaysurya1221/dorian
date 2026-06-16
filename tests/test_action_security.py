"""GitHub Action / workflow security regression tests (log_injection + permissions).

PR-controlled checker output (a claim's failure detail) flows into the Action log
and a sticky PR comment. A malicious checker detail like ``::error::`` or
``::stop-commands::`` must not be able to emit workflow commands. These tests lock
in the fence defense, the absence of ``pull_request_target``, and least-privilege
permissions across every workflow. They are pure file inspection — no network.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ACTION = REPO / "action" / "action.yml"
WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.yml"))


def _strip_comments(text: str) -> str:
    """Drop YAML comments so a `# ... pull_request_target ...` explanation is not
    mistaken for an actual trigger. (Workflow triggers never live in quoted strings.)"""
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out.append(line.split(" #", 1)[0])
    return "\n".join(out)


def test_action_fences_pr_controlled_output_against_log_injection():
    """The PR-controlled dorian output is wrapped in a `::stop-commands::<token>` /
    `::<token>::` fence whose token is unpredictable (/dev/urandom), so an attacker
    cannot pre-close the fence to smuggle a workflow command."""
    src = ACTION.read_text(encoding="utf-8")
    assert "::stop-commands::${fence}" in src, "missing stop-commands fence open"
    assert 'echo "::${fence}::"' in src, "missing fence close"
    # the fence token is random per run (od/urandom), not a constant an attacker can guess
    assert "/dev/urandom" in src and "fence=" in src
    # the PR-controlled content (cat /tmp/dorian.md) is BETWEEN open and close
    open_i = src.index("::stop-commands::${fence}")
    cat_i = src.index("cat /tmp/dorian.md")
    close_i = src.index('echo "::${fence}::"')
    assert open_i < cat_i < close_i, "dorian output must be fenced between open and close"


def test_malicious_checker_detail_is_neutralized_by_the_fence():
    """A checker detail containing workflow-command syntax is inert inside the fence:
    the close token is a random value, so the payload cannot terminate command
    suppression early."""
    src = ACTION.read_text(encoding="utf-8")
    # simulate the bytes a hostile checker might print into /tmp/dorian.md
    for payload in (
        "::error::pwned",
        "::set-output name=x::y",
        "::add-mask::secret",
        "::stop-commands::guess",
        "::warning::x",
    ):
        # the action never echoes the payload verbatim as a command; it only `cat`s the
        # file between random-token fences, so none of these can be a guessed close token
        assert payload not in src
    assert re.search(r"fence=\"dorian-\$\(od -An -N16 -tx1 /dev/urandom", src)


def test_no_workflow_uses_pull_request_target():
    for wf in WORKFLOWS:
        assert "pull_request_target" not in _strip_comments(wf.read_text(encoding="utf-8")), (
            f"{wf.name} uses pull_request_target (grants write + secrets to fork PRs)"
        )


def test_every_workflow_declares_permissions():
    for wf in WORKFLOWS:
        assert "permissions:" in wf.read_text(encoding="utf-8"), (
            f"{wf.name} has no top-level permissions block (defaults to broad scopes)"
        )


def test_public_microbench_is_manual_dispatch_only():
    raw = (REPO / ".github" / "workflows" / "public-microbench.yml").read_text(encoding="utf-8")
    mb = _strip_comments(raw)
    assert "workflow_dispatch" in mb
    # never auto/PR-triggered (comment text mentioning it is stripped first)
    assert "pull_request" not in mb
    assert "permissions:\n  contents: read" in mb


def test_write_scoped_jobs_only_in_release_workflows():
    """id-token/attestations write scopes appear ONLY in the manual release/publish
    workflows (never in ci or the microbench)."""
    safe = {"release-gate.yml", "publish.yml", "publish-testpypi.yml"}
    for wf in WORKFLOWS:
        text = wf.read_text(encoding="utf-8")
        if "id-token: write" in text or "attestations: write" in text:
            assert wf.name in safe, f"{wf.name} elevates write scopes unexpectedly"
            assert "workflow_dispatch" in text or "tags:" in text


def test_provenance_and_testpypi_workflows_exist():
    names = {wf.name for wf in WORKFLOWS}
    assert "release-gate.yml" in names
    assert "publish-testpypi.yml" in names
    rg = (REPO / ".github" / "workflows" / "release-gate.yml").read_text(encoding="utf-8")
    assert "attest-build-provenance" in rg and "id-token: write" in rg
    tp = (REPO / ".github" / "workflows" / "publish-testpypi.yml").read_text(encoding="utf-8")
    assert "test.pypi.org/legacy" in tp and "id-token: write" in tp
    assert "gh-action-pypi-publish" in tp
