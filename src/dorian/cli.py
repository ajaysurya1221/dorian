"""dorian CLI: init | capture | seal | verify | status | blast | bindings |
revalidate | report | suggest-data-checks | suggest-claims | sync | export | bench.

Exit codes: 0 ok/TRUSTED · 2 usage/infra · 3 DEGRADED · 4 REVOKED/integrity ·
5 ERRORED-only · 6 scope violation (ring 1).
"""

from __future__ import annotations

import argparse
import sys

from dorian import __version__

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DEGRADED = 3
EXIT_REVOKED = 4
EXIT_ERRORED = 5
EXIT_SCOPE = 6


def _add_exec_policy_flags(parser: argparse.ArgumentParser) -> None:
    """Opt-in execution-policy flags shared by seal/verify/revalidate. Defaults
    are unset → today's behavior (all checkers run). Env fallbacks DORIAN_DENY_EXEC
    / DORIAN_DENY_SHELL compose with the flags (either denies)."""
    parser.add_argument(
        "--deny-exec",
        action="store_true",
        help="refuse to RUN executable checkers (C4 pytest and C5 shell): they"
        " ERROR instead of executing, so a blocked claim never seals trusted and"
        " never silently passes revalidate. Use for untrusted/public-fork CI."
        " Env: DORIAN_DENY_EXEC=1.",
    )
    parser.add_argument(
        "--deny-shell",
        action="store_true",
        help="narrower than --deny-exec: block only C5 shell, still allow C4"
        " pytest. Env: DORIAN_DENY_SHELL=1.",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dorian",
        description="Hold AI agents to what they said they did: deterministic, "
        "token-free verification of the claims a change makes about its sources.",
    )
    p.add_argument("--version", action="version", version=f"dorian {__version__}")
    p.add_argument("--repo", default=".", help="repository root (default: .)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="command", required=True)

    ini = sub.add_parser(
        "init",
        help="scaffold a starter claims.json, change note, and GitHub Action workflow",
        description="Scaffold a born-verifiable starter setup so a first run reaches a"
        " sealed warrant in minutes: a starter claims.json, the change note it backs, and"
        " a GitHub Action workflow that re-checks the claims on every pull request. Writes"
        " files only — never runs a checker or executes code, never writes outside the repo,"
        " and never overwrites an existing file without --force. Use the global --json for a"
        " machine-readable summary.",
    )
    ini.add_argument(
        "--force", action="store_true", help="overwrite existing files (default: skip them)"
    )
    ini.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")

    cap = sub.add_parser("capture", help="build a read-set from a run")
    cap.add_argument("--transcript", help="Claude Code session .jsonl")
    cap.add_argument("--manual", action="append", default=[], help="path[:Lx-y] (repeatable)")
    cap.add_argument("--stdin", action="store_true", help="read manual specs from stdin")
    cap.add_argument("--out", default="rs.json", help="output read-set file")

    seal = sub.add_parser("seal", help="extract/bind claims and seal a warrant")
    seal.add_argument("artifact")
    seal.add_argument("--readset", required=True)
    seal.add_argument(
        "--extract",
        action="store_true",
        help="LLM claim drafting (extra) — FROZEN/experimental; prefer agent-emitted"
        " claims via `dorian verify --claims` (see docs/AGENT_CLAIMS.md)",
    )
    seal.add_argument(
        "--extract-mode",
        choices=["restate", "anchor", "candidate"],
        default="restate",
        help="--extract strategy: restate (model words each claim), anchor"
        " (model selects line spans; text derives from the artifact), or"
        " candidate (deterministic segmentation; model only classifies blocks)",
    )
    seal.add_argument(
        "--extract-consensus",
        type=int,
        default=0,
        metavar="K",
        help="consensus-of-K voting for --extract-mode anchor or candidate"
        " (0 = off): K independent selections, majority-voted deterministically",
    )
    seal.add_argument("--model", default="claude-fable-5")
    seal.add_argument("--claims", help="claims.json produced by review")
    seal.add_argument(
        "--supersede",
        help="warrant id being superseded; keeps downstream warrants sealed against"
        " the old id reachable by blast/recall",
    )
    seal.add_argument(
        "--allow-restricted",
        action="store_true",
        help="seal even when read-set uris match [tool.dorian.scopes] restricted globs",
    )
    seal.add_argument(
        "--no-quotes",
        action="store_true",
        help="content-free sidecar: drop anchor quotes (line numbers stay; changes the warrant id)",
    )
    seal.add_argument(
        "--binding-gate",
        choices=["off", "warn", "fail"],
        default="off",
        help="opt-in weak-binding review gate (default off): 'warn' prints binding"
        " diagnostics after a successful seal; 'fail' refuses the seal (writing nothing)"
        " on a high-risk weak binding. Never marks a claim false; 'single-file' is warn-only.",
    )
    seal.add_argument(
        "--strength-gate",
        choices=["off", "warn", "fail"],
        default="off",
        help="opt-in TRUTH-axis review gate (default off), the companion to --binding-gate:"
        " 'warn' prints checker-strength/adequacy diagnostics after a successful seal; 'fail'"
        " refuses the seal (writing nothing) when a load-bearing claim's checker is too weak to"
        " falsify its kind (e.g. a behavior claim backed only by an existence check). Never"
        " marks a claim false.",
    )
    _add_exec_policy_flags(seal)

    vf = sub.add_parser(
        "verify",
        help="one-shot: auto-capture a read-set from the claims, then seal"
        " (the agent-claims workflow; C3/C4/C5 claims)",
    )
    vf.add_argument("artifact")
    vf.add_argument("--claims", required=True, help="claims.json (agent-emitted or hand-written)")
    vf.add_argument(
        "--supersede",
        help="warrant id being superseded; keeps downstream warrants sealed against"
        " the old id reachable by blast/recall",
    )
    vf.add_argument(
        "--allow-restricted",
        action="store_true",
        help="seal even when referenced files match [tool.dorian.scopes] restricted globs",
    )
    vf.add_argument(
        "--no-quotes",
        action="store_true",
        help="content-free sidecar: drop anchor quotes (changes the warrant id)",
    )
    vf.add_argument(
        "--binding-gate",
        choices=["off", "warn", "fail"],
        default="off",
        help="opt-in weak-binding review gate (default off): 'warn' prints binding"
        " diagnostics after a successful seal; 'fail' refuses the seal (writing nothing)"
        " on a high-risk weak binding. Never marks a claim false; 'single-file' is warn-only.",
    )
    vf.add_argument(
        "--strength-gate",
        choices=["off", "warn", "fail"],
        default="off",
        help="opt-in TRUTH-axis review gate (default off), the companion to --binding-gate:"
        " 'warn' prints checker-strength/adequacy diagnostics after a successful seal; 'fail'"
        " refuses the seal (writing nothing) when a load-bearing claim's checker is too weak to"
        " falsify its kind (e.g. a behavior claim backed only by an existence check). Never"
        " marks a claim false.",
    )
    _add_exec_policy_flags(vf)

    st = sub.add_parser("status", help="trust state of warranted artifacts")
    st.add_argument("artifact", nargs="?")
    st.add_argument(
        "--check", action="store_true", help="report read-set hash drift (no checker runs)"
    )

    bl = sub.add_parser("blast", help="downstream warrants affected by a path or warrant")
    bl.add_argument("target", help="repo-relative path or warrant id (sha256:...)")
    bl.add_argument("--max-depth", type=int, default=8, help="traversal depth bound (default: 8)")

    bd = sub.add_parser(
        "bindings", help="binding-quality diagnostics for a warranted artifact (not a gate)"
    )
    bd.add_argument("artifact")

    bs = sub.add_parser(
        "bind-suggest",
        help="read-only: the symbol-definer files `verify` would auto-bind for each"
        " claim (and ambiguous symbols it would skip); writes nothing, never a gate",
    )
    bs.add_argument("--claims", required=True, help="claims.json")

    rb = sub.add_parser(
        "rebind",
        help="re-derive a warrant's symbol-definer watches with the current binding"
        " logic and re-seal it (born-verifiable, superseding the old id)",
    )
    rb.add_argument("artifact")
    # rebind re-RUNS every checker to re-seal, so it is an executable surface too
    _add_exec_policy_flags(rb)

    rv = sub.add_parser("revalidate", help="incremental re-check after changes")
    rv.add_argument("--since", help="git ref to diff from (e.g. HEAD~1)")
    rv.add_argument("--changed-paths", help="file listing changed paths (one per line)")
    rv.add_argument(
        "--format",
        choices=["text", "json", "md"],
        default="text",
        help="output format; md is a PR-comment body for the GitHub Action",
    )
    rv.add_argument("--enable-c2lite", action="store_true")
    rv.add_argument(
        "--checker-source",
        choices=["head", "base"],
        default=None,
        help="which sidecar a claim's checker SPEC is read from (sources checked are"
        " always the working tree). 'head' (default) runs the checked-out spec —"
        " trusted/internal repos. 'base' resolves each spec from the --since (base) ref"
        " so a PR-added or PR-modified executable checker is never executed — for"
        " public/fork PRs; fail-closed, NOT a sandbox. Env: DORIAN_CHECKER_SOURCE.",
    )
    _add_exec_policy_flags(rv)

    rp = sub.add_parser("report", help="event-log digest")
    rp.add_argument("--since", help="event window, e.g. 7d or 24h (digest default: 7d)")
    rp.add_argument(
        "--audit",
        action="store_true",
        help="full event log as dorian-audit-v1 JSONL (--since filters only when given)",
    )

    sd = sub.add_parser(
        "suggest-data-checks",
        help="suggest C5 data checkers from a data file's current state"
        " (SUGGESTIONS: review them, then paste into claims.json)",
        description="Derive C5 checker SUGGESTIONS from the current state of a data file."
        ' Review them, then paste the keepers into a claim\'s "checkers" list in claims.json.',
    )
    sd.add_argument("path", help="repo-relative data file (.csv, .sqlite/.db, .parquet)")
    sd.add_argument("--columns", help="comma-separated columns to suggest for (default: all)")
    sd.add_argument("--out", help="also write the JSON fragment to this file")

    sc = sub.add_parser(
        "suggest-claims",
        help="suggest born-verifiable C3 claims (symbol:/py-const:) from a Python file"
        " (SUGGESTIONS: review, then paste into claims.json)",
        description="Derive deterministic C3 claim SUGGESTIONS from a Python file's current"
        " state (symbol: for defs/classes, py-const: for literal constants). Each is run and"
        " only passing ones are emitted; load_bearing defaults to false. Review them, then"
        " paste the keepers into claims.json. Suggestions check existence/value, not behavior.",
    )
    sc.add_argument("path", help="repo-relative Python file (.py)")
    sc.add_argument("--out", help="also write the JSON fragment to this file")

    sub.add_parser("sync", help="rebuild the index from sidecars")

    ex = sub.add_parser(
        "export",
        help="export a sealed warrant for interop (experimental in-toto predicate)",
        description="Project a sealed .warrant into an in-toto Statement with an experimental"
        " ClaimVerification predicate (JSON to stdout). Deterministic; no signing or network.",
    )
    ex.add_argument("artifact", help="repo-relative artifact whose .warrant to export")
    ex.add_argument(
        "--in-toto",
        action="store_true",
        help="emit an in-toto Statement with a ClaimVerification predicate",
    )

    bench = sub.add_parser(
        "bench", help="repo-local benchmark tooling (mutation, large-mutation, churn)"
    )
    bench.add_argument("rest", nargs=argparse.REMAINDER)

    cc = sub.add_parser(
        "claude-code",
        help="scaffold Claude Code integrations (claim-warrants skill + opt-in hook)",
        description="Scaffold Claude Code integrations for Dorian. Writes files only —"
        " never runs a checker, executes code, or writes outside the target repo.",
    )
    cc_sub = cc.add_subparsers(dest="cc_command", required=True)
    icw = cc_sub.add_parser(
        "install-claim-warrants",
        help="scaffold the Dorian claim-warrants skill (and optional reminder Stop hook)"
        " into .claude/ so /dorian-claim-warrants drafts claim warrants you then verify",
        description="Scaffold a project-local Claude Code skill at"
        " .claude/skills/dorian-claim-warrants/ (invoked as /dorian-claim-warrants) that"
        " DRAFTS Dorian claim warrants for the checkable facts in a change summary, plus"
        " review-first settings examples and an opt-in, reminder-only Stop hook. The skill"
        " only drafts; `dorian verify` proves the claims deterministically. Writes files"
        " only; never overwrites without --force; idempotent. Not a sandbox — trusted repos.",
    )
    icw.add_argument(
        "--force", action="store_true", help="overwrite existing scaffolded files (default: skip)"
    )
    icw.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")
    icw.add_argument(
        "--with-hook",
        action="store_true",
        help="also scaffold the opt-in reminder Stop hook (a file only — not auto-enabled)",
    )
    icw.add_argument(
        "--no-hook",
        action="store_true",
        help="skill + settings only, no hook (this is already the default)",
    )
    icw.add_argument(
        "--settings-only", action="store_true", help="write only the settings examples"
    )
    icw.add_argument(
        "--print-next-steps",
        action="store_true",
        help="print the post-install usage guide and trust boundary, then exit (no writes)",
    )
    icw.add_argument(
        "--target", help="target repo/project root (default: --repo, i.e. current directory)"
    )

    _add_loop_parser(sub)
    return p


def _add_loop_steer_flags(parser: argparse.ArgumentParser) -> None:
    """Inputs shared by `loop preflight` and `loop prompt`: the change window, the
    steering policy, repair-cap accounting, scope/denylist, and the execution policy."""
    parser.add_argument("--since", help="git ref to diff from (e.g. the loop's base ref)")
    parser.add_argument("--changed-paths", help="file listing changed paths (one per line)")
    parser.add_argument(
        "--policy",
        choices=["cautious", "assist", "unattended"],
        default="assist",
        help="steering policy (default assist). cautious: repair even non-load-bearing breaks,"
        " cap 1. assist: repair load-bearing, continue past non-load-bearing, cap 3. unattended:"
        " like assist but REQUIRES --scope before repairing a load-bearing break (L3 needs a"
        " bounded lane), cap 3.",
    )
    parser.add_argument(
        "--max-repairs",
        type=int,
        default=None,
        help="repair-attempt cap before escalating (default: per-policy — cautious 1, else 3)",
    )
    parser.add_argument(
        "--repair-attempts",
        type=int,
        default=0,
        help="prior repair attempts for the current broken set (the loop threads this in;"
        " reaching --max-repairs escalates as an infinite-fix-loop guard)",
    )
    parser.add_argument(
        "--state-file",
        help="optional JSON loop-state file; reads repair_attempts from it (a --repair-attempts"
        " flag wins). Dorian never writes it — the loop owns its state.",
    )
    parser.add_argument(
        "--scope",
        action="append",
        default=[],
        metavar="GLOB",
        help="allowlist glob (repeatable): a load-bearing break whose files fall outside every"
        " --scope glob ESCALATES (over-reach guard) instead of being repaired",
    )
    parser.add_argument(
        "--deny-path",
        action="append",
        default=[],
        metavar="GLOB",
        help="extra sensitive-path glob (repeatable), added to the built-in security/infra/secrets"
        " set; a break touching one ESCALATES regardless of policy",
    )
    parser.add_argument(
        "--checker-source",
        choices=["head", "base"],
        default=None,
        help="which sidecar a claim's checker SPEC is read from (passed through to revalidate);"
        " 'base' never executes a PR-added checker. Env: DORIAN_CHECKER_SOURCE.",
    )
    parser.add_argument("--enable-c2lite", action="store_true")
    _add_exec_policy_flags(parser)


def _add_loop_parser(sub: argparse._SubParsersAction) -> None:
    """`dorian loop`: deterministic CONTINUE/REPAIR/ESCALATE steering for AI coding loops."""
    lp = sub.add_parser(
        "loop",
        help="loop steering: preflight (continue/repair/escalate), prompt, and install the skill",
        description="Dorian Loop Guard — a deterministic, token-free steering layer for AI coding"
        " loops. `preflight` re-checks the warrants a change touched and classifies"
        " the result into CONTINUE / REPAIR / ESCALATE; `prompt` renders that as a next-iteration"
        " instruction; `install` scaffolds the Claude Code loop-guard skill. No model runs at check"
        " time, and it never judges whole-loop success — not a sandbox, trusted repos only.",
    )
    lp_sub = lp.add_subparsers(dest="loop_command", required=True)

    pf = lp_sub.add_parser(
        "preflight",
        help="re-check touched warrants and emit a continue/repair/escalate decision packet",
        description="Re-check the claim warrants the change touched and classify the deterministic"
        " result into a CONTINUE/REPAIR/ESCALATE loop-decision packet. Exits 0 on success by"
        " default (the decision is in the output — Dorian does not stop the loop by default); use"
        " --fail-on to map a decision to exit 4 for a hard CI gate.",
    )
    _add_loop_steer_flags(pf)
    pf.add_argument(
        "--format",
        choices=["json", "md", "text"],
        default="json",
        help="output format (default json)",
    )
    pf.add_argument(
        "--fail-on",
        choices=["never", "repair", "escalate"],
        default="never",
        help="exit non-zero (4) when the decision is at/above this severity (default never: always"
        " exit 0 on success, so preflight never blocks the loop by itself)",
    )

    pr = lp_sub.add_parser(
        "prompt",
        help="render the decision as a compact next-iteration instruction for the coding agent",
        description="Run preflight (or read a saved packet via --from-json) and render a compact,"
        " agent-readable markdown instruction for the next loop iteration.",
    )
    _add_loop_steer_flags(pr)
    pr.add_argument(
        "--from-json",
        help="render from a saved preflight packet (path, or '-' for stdin) instead of re-running",
    )

    ins = lp_sub.add_parser(
        "install",
        help="scaffold the Claude Code loop-guard skill (/dorian-loop-guard) into .claude/",
        description="Scaffold a Claude Code skill at .claude/skills/dorian-loop-guard/"
        " (invoked as /dorian-loop-guard) plus example LOOP.md / STATE.md / run-log and a GitHub"
        " Actions snippet. Writes files only; never overwrites without --force; idempotent. Not a"
        " sandbox — trusted repos.",
    )
    ins.add_argument(
        "--force", action="store_true", help="overwrite existing scaffolded files (default: skip)"
    )
    ins.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")
    ins.add_argument(
        "--with-state",
        action="store_true",
        help="also write LOOP.md, STATE.md, and loop-run-log.md to the repo root",
    )
    ins.add_argument(
        "--with-action",
        action="store_true",
        help="also write a GitHub Actions example to .github/workflows/dorian-loop.yml",
    )
    ins.add_argument(
        "--target", help="target repo/project root (default: --repo, i.e. current directory)"
    )
    ins.add_argument(
        "--print-next-steps",
        action="store_true",
        help="print the post-install usage guide and trust boundary, then exit (no writes)",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from dorian import commands

        handler = getattr(commands, f"cmd_{args.command.replace('-', '_')}", None)
        if handler is None:
            print(f"dorian: '{args.command}' not implemented yet", file=sys.stderr)
            return EXIT_USAGE
        return int(handler(args))
    except ImportError:
        print(f"dorian: '{args.command}' not implemented in scaffold", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
