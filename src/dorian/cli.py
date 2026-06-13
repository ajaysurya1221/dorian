"""dorian CLI: capture | seal | status | blast | bindings | revalidate | report |
suggest-data-checks | sync | bench.

Exit codes: 0 ok/TRUSTED · 2 usage/infra · 3 DEGRADED · 4 REVOKED/integrity ·
5 ERRORED-only · 6 scope violation (ring 1).
"""

from __future__ import annotations

import argparse
import sys

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DEGRADED = 3
EXIT_REVOKED = 4
EXIT_ERRORED = 5
EXIT_SCOPE = 6


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dorian",
        description="Validity warrants for AI-generated artifacts: "
        "your doc still looks perfect; its portrait doesn't.",
    )
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
        help="LLM claim extraction (extra) (EXPERIMENTAL: see README)",
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

    bench = sub.add_parser("bench", help="repo-local benchmark tooling (owner spot-check)")
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
