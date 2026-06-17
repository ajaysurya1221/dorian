"""dorian CLI: capture | seal | verify | status | blast | bindings | revalidate |
report | suggest-data-checks | sync | export | bench.

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
    return p


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
