"""render_md (PR-comment markdown) + composite GitHub Action metadata.

Matrix:
(a) zero-affected run -> exactly the marker line + the no-op sentinel, nothing
    else (pure function AND through `dorian revalidate --format md`)
(b) mixed run via the fixture repo + the three-change commit, plus a downstream
    warrant (recall section) and a synthetic unrunnable-checker warrant
    (ERRORED): marker first; BROKEN rows carry checker type + detail; ERRORED
    rows are listed as errors and excluded from the broken count; the recalled
    section lists downstream artifacts with depth; stats footer is correct
(c) determinism: equal RevalResult values -> byte-identical markdown
(d) action/action.yml parses, is composite, declares the three documented
    inputs with their defaults, and uses no third-party actions
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from conftest import apply_three_change_commit, apply_unrelated_commit, write
from dorian import cli, commands, gitio
from dorian.capture.manual import parse_manual
from dorian.model import (
    Anchor,
    CheckerSpec,
    Claim,
    FoldPolicy,
    ProducedBy,
    ReadSetEntry,
    Warrant,
    sha256_hex,
)
from dorian.revalidate import RevalResult, render_md, revalidate
from dorian.seal import seal_artifact

MARKER = "<!-- dorian -->"
SENTINEL = "dorian: no warranted claims affected."

SPECS = ["src/auth.py:L4-7", "src/config.py:L1-1", "src/routes.py"]


def make_claims() -> list[Claim]:
    """Demo claims hit by the three-change commit: relocated, broken, broken."""
    return [
        Claim(
            id="c1",
            text="Token verification lives in src/auth.py and uses RS256.",
            kind="fact",
            load_bearing=True,
            anchor=Anchor(3, 3, "uses RS256"),
            supports=("rs-0",),
            checkers=(CheckerSpec(type="C1", program="rs-0"),),
        ),
        Claim(
            id="c2",
            text="The default request timeout is 30 seconds.",
            kind="quantity",
            load_bearing=True,
            supports=("rs-1",),
            checkers=(
                CheckerSpec(
                    type="C5",
                    program='shell:grep -Eq "TIMEOUT *= *30" src/config.py',
                    watch=("src/config.py",),
                ),
            ),
        ),
        Claim(
            id="c3",
            text="Login is served at /v1/login.",
            kind="reference",
            load_bearing=False,
            supports=("rs-2",),
            checkers=(CheckerSpec(type="C3", program="string:src/routes.py::/v1/login"),),
        ),
    ]


def _unrunnable_warrant(repo: Path) -> Warrant:
    """A synthetic sidecar whose only claim is backed by a checker type this
    kernel cannot run (C9), watching a file the three-change commit edits."""
    content = (repo / "src/config.py").read_bytes()
    entry = ReadSetEntry(
        id="rs-0", uri="src/config.py", selector=None, hash=sha256_hex(content), version=None
    )
    claim = Claim(
        id="c0",
        text="claim backed by a checker type this kernel cannot run",
        kind="fact",
        load_bearing=False,
        supports=("rs-0",),
        checkers=(CheckerSpec(type="C9", program="rs-0", watch=("src/config.py",)),),
    )
    w = Warrant.create(
        artifact_uri="docs/g.md",
        artifact_hash=sha256_hex(b"artifact"),
        git_ref="",
        produced_by=ProducedBy(runner="bench-synthetic", captured_at="2026-01-01T00:00:00Z"),
        read_set=(entry,),
        claims=(claim,),
        fold_policy=FoldPolicy(),
        sealed_at="2026-01-01T00:00:00Z",
    )
    w.dump(w.sidecar_path(repo))
    return w


# --- (a) zero-affected -> marker + sentinel only -----------------------------------


def test_zero_affected_is_marker_plus_sentinel_only() -> None:
    assert render_md(RevalResult()) == f"{MARKER}\n{SENTINEL}\n"


def test_cmd_revalidate_format_md_zero_affected(fixture_repo: Path, capsys) -> None:
    seal_artifact(fixture_repo, "docs/design.md", parse_manual(SPECS, fixture_repo), make_claims())
    base = gitio.head_ref(fixture_repo)
    apply_unrelated_commit(fixture_repo)
    args = cli.build_parser().parse_args(
        ["--repo", str(fixture_repo), "revalidate", "--since", base, "--format", "md"]
    )
    assert commands.cmd_revalidate(args) == 0
    assert capsys.readouterr().out == f"{MARKER}\n{SENTINEL}\n"


# --- (b) mixed run ------------------------------------------------------------------


def test_mixed_run_markdown(fixture_repo: Path) -> None:
    seal_artifact(fixture_repo, "docs/design.md", parse_manual(SPECS, fixture_repo), make_claims())
    write(fixture_repo, "docs/b.md", "# B\n\nBuilds on docs/design.md.\n")
    w_b = seal_artifact(
        fixture_repo, "docs/b.md", parse_manual(["docs/design.md"], fixture_repo), []
    )
    w_g = _unrunnable_warrant(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    apply_three_change_commit(fixture_repo)

    res = revalidate(fixture_repo, since=base)
    assert {cid for _, cid, _ in res.broken} == {"c2", "c3"}
    assert [(wid, cid) for wid, cid, _ in res.errored] == [(w_g.id, "c0")]
    assert [e["warrant_id"] for e in res.recalled] == [w_b.id]
    assert res.exit_code == 4

    md = render_md(res)
    lines = md.splitlines()
    assert lines[0] == MARKER
    assert SENTINEL not in md

    # headline counts BROKEN only: 2 breaks, never 3 (the ERRORED row is not a break)
    assert "### dorian: this change breaks 2 claim(s) in warranted artifacts" in md

    # broken rows: checker type + detail in the why column
    assert "| `c2` | BROKEN | C5: exit code 1" in md
    assert "| `c3` | BROKEN | C3: string_missing |" in md
    # relocated row is VERIFIED, flagged as relocation
    assert "| `c1` | VERIFIED (relocated) |" in md

    # ERRORED listed separately as an error, never as a break
    assert "| `c0` |" not in md
    assert "- `c0`: no checker registered for C9" in md
    assert md.count("BROKEN") == 2

    # explicit allow/block verdict, scannable at the top
    assert "**Status:** Blocked — 2 broken claim(s)" in md
    # aggregate trust-outcome counts (folds record only the warrants that changed)
    assert "| REVOKED | 1 |" in md
    assert "| UNKNOWN | 1 |" in md
    # each artifact section names the sidecar its claims were sealed into
    assert "_sealed in `docs/design.md.warrant`_" in md
    # verdict-keyed remediation tells the reviewer what to do next
    assert "**What to do:**" in md

    # fold transitions labeled by artifact uri (PR readers know paths, not warrant ids)
    assert "- `docs/design.md`: WARRANTED -> REVOKED" in md
    assert "- `docs/g.md`: WARRANTED -> UNKNOWN" in md
    assert "- `docs/b.md` (depth 1)" in md

    # stats footer: checks run / broken / errored + exit-code meaning
    assert "4 checker(s) run, 2 broken, 1 errored" in lines[-1]
    assert "exit 4" in lines[-1] and "REVOKED" in lines[-1]

    # PR-comment hygiene: no timestamps, no absolute paths
    assert str(fixture_repo) not in md
    assert "T00:" not in md


# --- (c) determinism ----------------------------------------------------------------


def test_same_result_renders_identical_md() -> None:
    def result() -> RevalResult:
        return RevalResult(
            broken=[("sha256:w", "c2", "C5: exit code 1")],
            relocated=[("sha256:w", "c1", "anchor_moved")],
            errored=[("sha256:g", "c0", "no checker registered for C9")],
            passed=[("sha256:w", "c4", "ok")],
            folds={"sha256:w": ("TRUSTED", "REVOKED"), "sha256:g": ("WARRANTED", "UNKNOWN")},
            recalled=[
                {
                    "warrant_id": "sha256:b",
                    "artifact_uri": "docs/b.md",
                    "depth": 1,
                    "via": "sha256:w",
                }
            ],
            candidates=4,
            exit_code=4,
        )

    one, two = render_md(result()), render_md(result())
    assert one == two
    # round-trips as plain text: deterministic by construction, not by accident
    assert json.dumps(one) == json.dumps(two)


# --- content-carryover bound (md is the PUBLIC PR-comment body) ----------------------


def test_md_details_are_bounded_like_the_audit_export() -> None:
    """Regression: render_md once rendered C5 FAIL details unbounded — a drifted
    domain claim over a 500-distinct-value column put every raw cell value into
    the public PR comment, while `report --audit` truncated the same detail to
    160 chars. The md surface gets the same bound, on every detail row."""
    from dorian import report
    from dorian import revalidate as reval_mod

    assert reval_mod._DETAIL_MAX == report._DETAIL_MAX  # the two export surfaces agree

    leak = "C5: status values ['" + "', '".join(f"SECRET-{i:04d}" for i in range(500)) + "']"
    res = RevalResult(
        broken=[("sha256:w", "c2", leak)],
        errored=[("sha256:w", "c0", leak)],
        passed=[("sha256:w", "c4", leak)],
        artifacts={"sha256:w": "docs/design.md"},
        candidates=3,
        exit_code=4,
    )
    md = render_md(res)
    assert "SECRET-0499" not in md
    for line in md.splitlines():
        if "SECRET-" in line:  # detail cells and error bullets both bounded
            assert len(line) < reval_mod._DETAIL_MAX + 60  # detail + row scaffolding
    assert leak[: reval_mod._DETAIL_MAX][:40] in md  # head of the detail survives


# --- (d) action.yml metadata ---------------------------------------------------------


def test_action_yml_is_valid_composite() -> None:
    path = Path(__file__).resolve().parent.parent / "action" / "action.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert data["runs"]["using"] == "composite"
    inputs = data["inputs"]
    assert set(inputs) == {
        "fail_on",
        "base",
        "install",
        "deny_exec",
        "deny_shell",
        "checker_trust",
    }
    assert inputs["fail_on"]["default"] == "revoked"
    assert inputs["base"]["default"] == "${{ github.event.pull_request.base.sha }}"
    assert inputs["install"]["default"] == "dorian-vwp"
    # deny-exec/deny-shell default OFF so trusted/internal repos are unchanged
    assert str(inputs["deny_exec"]["default"]) == "false"
    assert str(inputs["deny_shell"]["default"]) == "false"
    # checker_trust defaults to head (today's behavior); base is the opt-in fork mode
    assert str(inputs["checker_trust"]["default"]) == "head"
    for name in inputs:
        assert inputs[name]["description"].strip(), f"input {name} must be documented"

    steps = data["runs"]["steps"]
    assert steps, "composite action must declare steps"
    assert all("uses" not in step for step in steps), "no third-party actions allowed"
    assert all(step.get("shell") == "bash" for step in steps if "run" in step)
