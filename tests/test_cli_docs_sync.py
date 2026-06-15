"""README / CLI command-surface drift guard.

The v0.10 audit found the README advertising commands the parser did not expose
(`bind-suggest`, `rebind`, `bench binding-lifecycle`, `bench realworld-usecases`).
Those now exist; this test keeps it that way by asserting that every `dorian
<command>` the README mentions resolves to a real subparser (or a real `bench`
subcommand), so a future doc edit that names a non-existent command fails here.

It is intentionally simple: it reads the actual parser and the actual bench
dispatch table — no hand-maintained command list to drift on its own.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from dorian import cli
from dorian.commands import _BENCH_DISPATCH

REPO_ROOT = Path(__file__).resolve().parents[1]
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

# tokens that follow `dorian` but are not subcommands (global flags / help)
_NON_COMMANDS = {"--version", "--help", "--repo", "--json", "-h"}


def _subcommands() -> set[str]:
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return set(sub.choices)


def _code_text() -> str:
    """Only commands shown in code (fenced blocks + inline backticks) are claims
    about the CLI surface; prose like 'dorian verifies ...' is not a command."""
    fenced = re.findall(r"```.*?```", README, re.DOTALL)
    inline = re.findall(r"`[^`\n]+`", README)
    return "\n".join(fenced + inline)


def test_research_flagged_commands_all_exist() -> None:
    """The four commands the audit reported as missing must now be real."""
    cmds = _subcommands()
    assert {"bind-suggest", "rebind"} <= cmds
    assert {"binding-lifecycle", "realworld-usecases"} <= set(_BENCH_DISPATCH)


def test_every_readme_dorian_command_resolves() -> None:
    cmds = _subcommands()
    code = _code_text()
    # first token after `dorian ` inside a code span; de-duped
    mentioned = set(re.findall(r"\bdorian[ \t]+([a-z][a-z0-9-]+)", code))
    unknown = {tok for tok in mentioned if tok not in cmds and tok not in _NON_COMMANDS}
    assert not unknown, f"README code references unknown dorian commands: {sorted(unknown)}"


def test_every_readme_bench_subcommand_is_dispatched() -> None:
    mentioned = set(re.findall(r"\bdorian[ \t]+bench[ \t]+([a-z][a-z0-9-]+)", _code_text()))
    unknown = mentioned - set(_BENCH_DISPATCH)
    assert not unknown, f"README code references unknown bench subcommands: {sorted(unknown)}"
