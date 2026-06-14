"""Guards for the launch-train onboarding surface (README + Claude Code pack +
public-benchmark protocol scaffold + trusted-base Action design).

These pin DOC HYGIENE, not product behavior: the README must lead Claude-Code-aware
with the trusted/local boundary visible, the workflow pack must keep its safety
statements, the public-benchmark protocol must stay protocol-only and exclude the
private repo, and the trusted-base Action design must stay flagged for human review.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


README = _read("README.md")
# normalize for prose checks: drop blockquote markers (a "> " line prefix is not
# content) so a phrase that wraps inside a callout still matches, then collapse space
NORM = re.sub(r"\s+", " ", re.sub(r"(?m)^\s*>\s?", "", README)).lower()


# --- Slice A: README repositioning -------------------------------------------------


def test_readme_names_claude_code_and_links_the_section() -> None:
    assert "Claude Code" in README
    assert "using dorian with claude code" in NORM  # the section heading + ToC entry
    assert "docs/USE_WITH_CLAUDE_CODE.md" in README
    assert "examples/claude-code" in README


def test_readme_boundary_callout_is_present_near_the_top() -> None:
    # the local-first / token-free / trusted-repo boundary, made impossible to miss
    assert "trusted, internal repositories" in NORM
    assert "not public ci taking forked pull requests" in NORM
    assert "zero model tokens at check time" in NORM


# --- Slice B: Claude Code workflow pack --------------------------------------------


def test_use_with_claude_code_has_the_required_elements() -> None:
    doc = _read("docs/USE_WITH_CLAUDE_CODE.md")
    low = doc.lower()
    flat = re.sub(r"\s+", " ", low)
    assert "dorian verify" in doc and "dorian revalidate" in doc  # both loop commands
    assert "load_bearing" in doc and "symbol:" in doc  # paste-ready prompt + checker guidance
    assert "claims.json" in doc and "executable input" in flat
    assert "verify runs" in low and "review" in low
    assert "untrusted source" in low  # executable-input warning
    assert "execute code" in low  # C4/C5 warning
    assert "review-first" in low  # default Claude Code settings posture
    assert "trusted-local" in low  # faster path must be a separate opt-in
    assert "read-only and verify" not in low  # default sample must not pre-allow verify
    assert "no model at check time" in low  # token-free statement
    assert "frozen" in low  # extraction frozen/draft-only
    assert "what dorian is" in low  # is/is-not section
    assert "examples/claude-code" in doc  # links the runnable pack


def test_claude_code_example_pack_files_exist_and_parse() -> None:
    base = REPO / "examples" / "claude-code"
    for name in (
        "app.py",
        "change-note.md",
        "claims.json",
        "settings.example.json",
        "settings.trusted-local.example.json",
        "README.md",
    ):
        assert (base / name).is_file(), f"missing example file: {name}"

    claims = json.loads((base / "claims.json").read_text(encoding="utf-8"))
    ids = {c["id"] for c in claims["claims"]}
    assert {"login-handler-added", "login-timeout-30s"} <= ids
    for c in claims["claims"]:
        assert c["checkers"], f"example claim {c['id']} must be backed"

    settings = json.loads((base / "settings.example.json").read_text(encoding="utf-8"))
    allow = settings["permissions"]["allow"]
    assert allow
    assert any("dorian status" in rule for rule in allow)
    assert any("dorian bindings" in rule for rule in allow)
    assert any("dorian bind-suggest" in rule for rule in allow)
    # the default sample is review-first: no checker execution, no seal/extract, no shell wildcard
    forbidden = ("dorian verify", "dorian revalidate", "dorian seal", "--extract", "Bash(*)")
    assert not any(bad in rule for bad in forbidden for rule in allow)

    trusted = json.loads((base / "settings.trusted-local.example.json").read_text(encoding="utf-8"))
    trusted_allow = trusted["permissions"]["allow"]
    assert any("dorian verify" in rule for rule in trusted_allow)
    assert not any("--extract" in rule or "Bash(*)" in rule for rule in trusted_allow)


# --- Slice C: public-benchmark protocol scaffold -----------------------------------


def test_public_benchmark_protocol_is_protocol_only_and_scoped() -> None:
    doc = _read("docs/PUBLIC_BENCHMARK_PROTOCOL.md")
    low = doc.lower()
    assert "protocol only" in low and "no results" in low  # pre-registration, not results
    assert "reproducibility evidence" in low
    # both layers reported separately
    assert "selection layer" in low and "alarm layer" in low
    # genuinely public repos at frozen SHAs
    assert "encode/httpx" in doc and "pallets/click" in doc
    assert "d4961b9f8e7f00b654dbdbf200562bd273f598c7" in doc
    assert "5df10013f7ed8bad94da1e82d58e3711eec1afb3" in doc
    # the private repo is explicitly excluded from public evidence
    assert "genai-core" in low and "excluded" in low
    assert "bench/public/repos.public.json" in doc
    assert "bench/real/repos.real.json" not in doc
    # results-wording discipline carried in the protocol
    assert "forbidden" in low
    assert (REPO / "bench" / "public" / "README.md").is_file()


def test_public_benchmark_manifest_contains_only_public_repos() -> None:
    manifest = json.loads(_read("bench/public/repos.public.json"))
    repos = manifest["repos"]
    assert {repo["name"] for repo in repos} == {"encode/httpx", "pallets/click"}
    assert {repo["frozen_sha"] for repo in repos} == {
        "d4961b9f8e7f00b654dbdbf200562bd273f598c7",
        "5df10013f7ed8bad94da1e82d58e3711eec1afb3",
    }
    for repo in repos:
        assert repo["public"] is True
        assert repo["private"] is False
        assert "url" in repo and repo["url"].startswith("https://github.com/")
        assert "genai-core" not in json.dumps(repo).lower()

    for path in (REPO / "bench" / "public").rglob("*"):
        if path.is_file():
            assert "genai-core" not in path.read_text(encoding="utf-8").lower()


# --- Slice E: trusted-base Action design (HUMAN REVIEW REQUIRED, no code) -----------


def test_trusted_base_action_design_is_flagged_and_safe_by_default() -> None:
    doc = _read("docs/TRUSTED_BASE_ACTION_DESIGN.md")
    assert "HUMAN REVIEW REQUIRED" in doc
    assert "not implemented" in doc.lower()
    assert "pull_request_target" in doc  # the never-use constraint is stated
    assert "does not sandbox PR-head code" in doc


# --- navigation index --------------------------------------------------------------


def test_start_here_links_the_key_docs() -> None:
    doc = _read("docs/START_HERE.md")
    for needle in ("USE_WITH_CLAUDE_CODE.md", "AGENT_CLAIMS.md", "examples/claude-code"):
        assert needle in doc, f"START_HERE must link {needle}"
