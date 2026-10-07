"""The README's "Try it" recipe, executed as a black box.

This pins the headline runnable example to reality: it runs the sequence the README
shows (out-of-process, via `python -m dorian`) and asserts the observable result, and it
checks the README still contains those commands — so the demo a new user copy-pastes can
never silently become a broken claim. (A tool whose whole pitch is "don't ship false
claims" must not ship a false claim in its own README.)

The recipe commits with a command-local Git identity, so the test strips inherited identity
variables and ignores global/system Git config: the README's own commit command must supply
the identity (Git can still guess one from the hostname on some hosts). The recipe's
`pip install` step is not run here (no network); the test exercises this checkout and pins
the README's install line to its version.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_IDENTITY_VARS = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "EMAIL",
)

# the README's commit command, identity included (kept identical to the README block)
_COMMIT_ARGS = (
    "-c",
    "user.name=Demo",
    "-c",
    "user.email=demo@example.invalid",
    "-c",
    "commit.gpgsign=false",
    "commit",
    "-q",
    "-m",
    "app + note",
)


def _clean_env() -> dict[str, str]:
    """No inherited identity, no global or system Git config: a machine without Git setup."""
    env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_VARS}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


# the claims.json the README's recipe writes (kept identical to the README block)
_CLAIMS_JSON = (
    '{"claims": [\n'
    '  {"id": "handler-exists", "text": "handler() lives in app.py.",\n'
    '   "kind": "reference", "load_bearing": true,\n'
    '   "checkers": [{"type": "C3", "program": "symbol:app.py::handler"}]}\n'
    "]}\n"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, env=_clean_env(), check=True, capture_output=True)


def _dorian(*args: str, repo: Path) -> subprocess.CompletedProcess:
    # mirror the README recipe exactly: cd into the repo, default --repo=".", relative paths
    cmd = [sys.executable, "-m", "dorian", *args]
    return subprocess.run(
        cmd, cwd=repo, env=_clean_env(), capture_output=True, text=True, timeout=120
    )


def test_readme_try_it_recipe_runs_end_to_end(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_text(".venv/\n")
    (repo / "app.py").write_text("def handler():\n    return 200\n")
    (repo / "note.md").write_text("# change note\n\n`handler()` lives in app.py.\n")
    _git(repo, "add", "app.py", "note.md", ".gitignore")
    _git(repo, *_COMMIT_ARGS)
    (repo / "claims.json").write_text(_CLAIMS_JSON, encoding="utf-8")

    # verify: the claim holds against the real code -> sealed, exit 0
    r = _dorian("verify", "note.md", "--claims", "claims.json", repo=repo)
    assert r.returncode == 0, r.stderr
    assert "verified 1/1 claim(s)" in r.stdout
    assert (repo / "note.md.warrant").is_file()

    # a refactor renames the function the note claims exists; note.md is untouched
    (repo / "app.py").write_text("def renamed():\n    return 200\n")

    r = _dorian("revalidate", "--since", "HEAD", repo=repo)
    assert r.returncode == 4, f"{r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "handler-exists" in r.stdout
    assert "BROKEN" in r.stdout
    assert "REVOKED" in r.stdout


def test_readme_still_contains_the_runnable_commands() -> None:
    """If the recipe's commands drift, this fails — keeping the README honest vs the test."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "dorian verify note.md --claims claims.json" in readme
    assert "dorian revalidate --since HEAD" in readme
    assert "symbol:app.py::handler" in readme
    assert "git add app.py note.md .gitignore" in readme
    assert "git -c user.name=Demo -c user.email=demo@example.invalid" in readme
    assert '-c commit.gpgsign=false commit -q -m "app + note"' in readme


def test_readme_recipe_installs_the_current_release() -> None:
    """The recipe starts from a fresh venv with a pinned install; the pin must be this version."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    version = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    assert "python3 -m venv .venv" in readme
    pins = re.findall(r"python -m pip install dorian-vwp==(\d+\.\d+\.\d+)", readme)
    assert pins, "the Try it recipe must install a pinned dorian-vwp release"
    assert all(pin == version for pin in pins), f"README pins {pins}, package is {version}"


def _github_slug(heading_text: str) -> str:
    """GitHub-style anchor slug for a markdown heading (lowercase, drop punctuation, spaces->-)."""
    slug = heading_text.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)  # drop punctuation, keep word chars / space / hyphen
    slug = re.sub(r"\s+", "-", slug)
    return slug


def test_readme_demo_badge_points_at_the_runnable_demo() -> None:
    """The top "Demo" badge must anchor to a REAL, runnable heading — not the illustrative one.

    A new reader who clicks "Demo" lands on the first hands-on section; if that section is the
    copy-paste-fails "60-second aha" the demo path is broken. We resolve the badge's `#anchor`
    to an actual heading via GitHub-style slugs and assert it is the runnable "Try it" section.
    """
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    # the badge link wraps the "Demo" shields.io image: <a href="#anchor">...alt="Demo"...</a>
    m = re.search(r'<a href="#([^"]+)">\s*<img[^>]*alt="Demo"', readme)
    assert m is not None, "could not find the Demo badge link in README.md"
    badge_anchor = m.group(1)

    # GitHub-style slug of every ## / ### heading
    heading_slugs = {
        _github_slug(text): text
        for text in re.findall(r"^#{2,3}\s+(.+?)\s*$", readme, flags=re.MULTILINE)
    }

    # the anchor must resolve to a heading that actually exists
    assert badge_anchor in heading_slugs, (
        f"Demo badge anchor #{badge_anchor} does not match any README heading; "
        f"headings are: {sorted(heading_slugs)}"
    )

    target_heading = heading_slugs[badge_anchor]
    # ...and it must be the runnable demo, not the illustrative "60-second aha"
    assert "60-second aha" not in target_heading.lower(), (
        f"Demo badge points at the illustrative section ({target_heading!r}); "
        "it must point at the runnable copy-paste demo."
    )
    assert "try it" in target_heading.lower(), (
        f"Demo badge should point at the runnable 'Try it' demo, got {target_heading!r}"
    )
