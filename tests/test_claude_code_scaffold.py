"""`dorian claude-code install-claim-warrants` — scaffolder, skill, and templates.

The scaffolder writes files only: it never runs a checker, executes code, writes
outside the target repo, or overwrites without ``--force`` (re-running is
idempotent). The load-bearing end-to-end test seals a real claim against a real
change through the scaffolded workflow and then REVOKEs it on drift — the same
born-verifiable contract ``dorian init`` is held to.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from dorian import claims_io, claude_code
from dorian.cli import main

SKILL = ".claude/skills/dorian-claim-warrants"
HOOK = ".claude/hooks/dorian_claim_warrants_stop.py"

# Phrases the feature must NEVER use — it is "claim warrants", not "Agent Receipts"
# (a distinct action-audit protocol). Mentioning Agent Receipts in a *contrast* is
# fine; branding the feature as it is not.
AGENT_RECEIPTS_NO_GO = (
    "Agent Receipts for code",
    "cryptographic agent receipts",
    "records what the agent did",
    "auditable tool-call chain",
    "proves all agent actions",
)

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=repo, env={**os.environ, **_GIT_ENV}, check=True, capture_output=True
    )


def _seed_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")


def _install(repo: Path, *flags: str) -> int:
    return main(["--repo", str(repo), "claude-code", "install-claim-warrants", *flags])


# --- packaging / manifest integrity ------------------------------------------


def test_every_manifest_template_is_readable_package_data() -> None:
    """Each manifest source resolves through importlib.resources (works from wheel)."""
    for t in claude_code.MANIFEST:
        content = claude_code._read_template(t.src)
        assert content, f"empty/missing template: {t.src}"


def test_manifest_dests_are_repo_contained() -> None:
    for t in claude_code.MANIFEST:
        assert not t.dest.startswith("/")
        assert ".." not in t.dest.split("/")
        assert t.dest.startswith(".claude/")


# --- CLI surface --------------------------------------------------------------


def test_command_is_wired(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert _install(repo, "--dry-run") == 0


def test_dry_run_writes_nothing(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert _install(repo, "--dry-run") == 0
    assert not (repo / ".claude").exists()
    out = capsys.readouterr().out
    assert "Would create:" in out
    assert f"{SKILL}/SKILL.md" in out


def test_default_install_writes_skill_and_settings_no_hook(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert _install(repo) == 0
    assert (repo / SKILL / "SKILL.md").is_file()
    assert (repo / SKILL / "README.md").is_file()
    assert (repo / ".claude/settings.dorian-claim-warrants.review-first.example.json").is_file()
    assert (repo / ".claude/settings.dorian-claim-warrants.trusted-local.example.json").is_file()
    # hook is opt-in: NOT written by default
    assert not (repo / HOOK).exists()


def test_with_hook_installs_hook(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert _install(repo, "--with-hook") == 0
    assert (repo / HOOK).is_file()
    assert "stop_hook_active" in (repo / HOOK).read_text()


def test_settings_only_writes_only_settings(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert _install(repo, "--settings-only") == 0
    assert not (repo / SKILL / "SKILL.md").exists()
    assert not (repo / HOOK).exists()
    assert (repo / ".claude/settings.dorian-claim-warrants.review-first.example.json").is_file()


def test_with_hook_and_no_hook_conflict_is_usage_error(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert _install(repo, "--with-hook", "--no-hook") == 2
    assert not (repo / ".claude").exists()


def test_idempotent_without_force(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert _install(repo) == 0
    skill = repo / SKILL / "SKILL.md"
    edited = "MY EDITS\n"
    skill.write_text(edited, encoding="utf-8")
    assert _install(repo) == 0  # second run does not clobber
    assert skill.read_text(encoding="utf-8") == edited


def test_force_overwrites_only_scaffolded_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert _install(repo) == 0
    skill = repo / SKILL / "SKILL.md"
    skill.write_text("MY EDITS\n", encoding="utf-8")
    # an unrelated .claude file must be left untouched by --force
    other = repo / ".claude" / "settings.json"
    other.write_text('{"mine": true}\n', encoding="utf-8")
    assert _install(repo, "--force") == 0
    assert "dorian-claim-warrants" in skill.read_text(encoding="utf-8")  # regenerated
    assert other.read_text(encoding="utf-8") == '{"mine": true}\n'  # untouched


def test_works_from_subdirectory(tmp_path: Path) -> None:
    """--target a subdir: files land in the repo root .claude, not the subdir."""
    repo = tmp_path / "repo"
    _seed_repo(repo)
    sub = repo / "pkg" / "deep"
    sub.mkdir(parents=True)
    assert main(["claude-code", "install-claim-warrants", "--target", str(sub)]) == 0
    assert (repo / SKILL / "SKILL.md").is_file()
    assert not (sub / ".claude").exists()


def test_json_output_is_machine_readable(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert main(["--repo", str(repo), "--json", "claude-code", "install-claim-warrants"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert f"{SKILL}/SKILL.md" in payload["created"]
    assert payload["is_git"] is True
    assert payload["hook_installed"] is False
    assert payload["trust_boundary"]


def test_non_git_target_warns_but_installs(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "plain"  # no `git init`
    repo.mkdir()
    assert _install(repo) == 0
    out = capsys.readouterr().out
    assert "not a git repository" in out
    assert (repo / SKILL / "SKILL.md").is_file()


def test_print_next_steps_writes_nothing(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert _install(repo, "--print-next-steps") == 0
    assert not (repo / ".claude").exists()
    assert "Trust boundary:" in capsys.readouterr().out


# --- skill / template content -------------------------------------------------


def test_skill_frontmatter_is_parseable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert _install(repo) == 0
    text = (repo / SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    fm = text.split("---\n", 2)[1]
    assert "description:" in fm  # the key that drives auto-load
    # directory name (not frontmatter name) is the /command -> /dorian-claim-warrants
    assert Path(SKILL).name == "dorian-claim-warrants"


def test_required_safety_phrases_present(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert _install(repo) == 0
    text = (repo / SKILL / "SKILL.md").read_text(encoding="utf-8")
    for phrase in (
        "DRAFT",
        "not verified until Dorian verify passes",
        "not a sandbox",
        "trusted repo",
        "strength-gate=fail",
        "binding-gate=warn",
    ):
        assert phrase in text, f"SKILL.md missing required phrase: {phrase!r}"


def test_example_and_template_json_is_valid(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert _install(repo) == 0
    good = repo / SKILL / "examples/good-claims.json"
    skeleton = repo / SKILL / "templates/claims.json"
    # both are valid JSON and load through Dorian's real claims loader
    assert len(claims_io.load_claims(good)) == 5
    assert len(claims_io.load_claims(skeleton)) == 1


def test_no_installed_file_brands_itself_agent_receipts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert _install(repo, "--with-hook") == 0
    for p in (repo / ".claude").rglob("*"):
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        for nogo in AGENT_RECEIPTS_NO_GO:
            assert nogo not in text, f"{p} contains no-go branding {nogo!r}"


def test_safety_boundary_distinguishes_agent_receipts(tmp_path: Path) -> None:
    """The comparison must exist (so users aren't confused) — just not as branding."""
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert _install(repo) == 0
    text = (repo / SKILL / "reference/safety-boundary.md").read_text(encoding="utf-8")
    assert "Agent Receipts" in text
    assert "claim warrants" in text


# --- end to end ---------------------------------------------------------------


def test_scaffold_seal_and_revoke_end_to_end(tmp_path: Path) -> None:
    """Scaffold -> author a real claim from the templates -> verify seals (exit 0) ->
    mutate the source -> revalidate folds the warrant to REVOKED (exit 4)."""
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert _install(repo) == 0

    # a real, checkable change: a config value the change note asserts
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.4.0"\n', encoding="utf-8"
    )
    notes = repo / "docs" / "changes"
    notes.mkdir(parents=True)
    (notes / "bump.md").write_text("# Bump\n\nThe package version is 1.4.0.\n", encoding="utf-8")
    (notes / "bump.claims.json").write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "version-1-4-0",
                        "text": "pyproject version is 1.4.0.",
                        "kind": "quantity",
                        "load_bearing": True,
                        "checkers": [
                            {
                                "type": "C3",
                                "program": 'config-value:pyproject.toml:project.version:"1.4.0"',
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change + claim")

    # seal under the strength gate (the command the skill prints)
    assert (
        main(
            [
                "--repo",
                str(repo),
                "verify",
                "docs/changes/bump.md",
                "--claims",
                str(notes / "bump.claims.json"),
                "--strength-gate=fail",
                "--binding-gate=warn",
            ]
        )
        == 0
    )
    assert (notes / "bump.md.warrant").is_file()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seal")

    # drift: the version changes; the sealed claim is now false
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.5.0"\n', encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "bump again — breaks the sealed claim")

    assert main(["--repo", str(repo), "revalidate", "--since", "HEAD~1"]) == 4  # REVOKED
