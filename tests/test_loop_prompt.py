"""Loop prompt: a compact, agent-readable next-iteration instruction."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import CONFIG_PY, write
from dorian import cli, commands, gitio
from test_revalidate import _sealed


def _ns(*argv: str):
    return cli.build_parser().parse_args(list(argv))


def test_prompt_repair_mentions_broken_claim(fixture_repo: Path, capsys) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    write(fixture_repo, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT = 10"))
    rc = commands.cmd_loop(_ns("--repo", str(fixture_repo), "loop", "prompt", "--since", base))
    out = capsys.readouterr().out
    assert rc == 0
    assert "REPAIR" in out
    assert "c2" in out
    assert "Boundary" in out  # the standing not-a-judge / not-a-sandbox reminder


def test_prompt_continue(fixture_repo: Path, capsys) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    rc = commands.cmd_loop(_ns("--repo", str(fixture_repo), "loop", "prompt", "--since", base))
    assert rc == 0
    assert "CONTINUE" in capsys.readouterr().out


def test_prompt_from_saved_json(fixture_repo: Path, tmp_path: Path, capsys) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    write(fixture_repo, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT = 10"))
    commands.cmd_loop(
        _ns("--repo", str(fixture_repo), "loop", "preflight", "--since", base, "--format", "json")
    )
    packet = capsys.readouterr().out
    saved = tmp_path / "packet.json"
    saved.write_text(packet)
    # rendering from the saved packet must not need the repo at all
    rc = commands.cmd_loop(_ns("loop", "prompt", "--from-json", str(saved)))
    out = capsys.readouterr().out
    assert rc == 0
    assert "REPAIR" in out
    assert "c2" in out
    # the saved packet and a fresh render agree on the decision
    assert json.loads(packet)["decision"] == "repair"
