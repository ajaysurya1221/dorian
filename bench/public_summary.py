"""Public-safe benchmark summary (markdown + json mirror).

Usage:
    python -m bench.public_summary [--summary ...] [--results ...]
        [--allow-repo NAME ...] [--out ...] [--json-out ...]
    (or: dorian bench public-summary ... from a dorian checkout)

Reads the owner-checked summary written by `python -m bench.owner_review
owner-metrics --summary-out`, plus results.json — used ONLY for aggregate
composition counts — and renders a public-safe markdown summary with a json
mirror ("schema": "dorian-public-summary-v1").

Structural privacy rule: the outputs may contain only (a) numeric/boolean
fields, (b) the enumerated recommendation/reasons strings from the summary,
(c) allow-listed repo names (--allow-repo, repeatable; default: none allowed),
and (d) this module's own fixed template strings. Artifact paths, claim
texts, commit shas/subjects, changed-file lists, and rationales never flow
through; repos not on the allow-list appear as "private repository A"/"B"/...
assigned in sorted-name order. When the recommendation is HOLD_PUBLIC_CLAIMS
the markdown still generates but leads with a NOT CLEARED FOR PUBLIC USE
banner, and the json carries "cleared": false ("cleared" is true only on
PASS; EXPAND_TO_FULL_201 is also false).

Outputs are deterministic — no timestamps; json is dumped with indent=2 +
sort_keys and a trailing newline.
"""

from __future__ import annotations

import argparse
import json
import string
import sys
from pathlib import Path

RESULTS_DIR = "bench/real/results"

SCHEMA = "dorian-public-summary-v1"

# the ONLY summary fields the generator copies (structural privacy rule);
# recommendation/reasons are enumerated strings, everything else is numeric
_METRIC_FIELDS = (
    "pairs",
    "excluded",
    "fp_reduction",
    "fp_reduction_ci",
    "dorian_recall",
    "dorian_recall_ci",
    "dorian_precision",
    "dorian_precision_ci",
    "baseline_precision",
    "baseline_precision_ci",
)
_SPOT_CHECK_FIELDS = ("reviewed_pairs", "overrides", "unsure", "out_of_scope")
_PANEL_FIELDS = ("pairs_judged", "unanimous", "labeled_true")

_CAVEAT = (
    "These numbers come from an owner-checked but model-adjudicated benchmark: "
    "ground-truth labels were produced by a blind model panel and audited by an "
    "owner spot-check, not by independent human raters. See the dorian "
    "repository for the full methodology before relying on them."
)


def _read_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_text(path: str, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def compose(summary: dict, results: dict, allow: set[str]) -> dict:
    """The public record: enumerated summary fields + composition counts only."""
    repos = results["repos"]
    names = sorted({r["name"] for r in repos})
    private = [n for n in names if n not in allow]
    label = {n: f"private repository {string.ascii_uppercase[i]}" for i, n in enumerate(private)}
    spot = summary["spot_check"]
    return {
        "schema": SCHEMA,
        "cleared": spot["recommendation"] == "PASS",
        "composition": {
            "repo_windows": len(repos),
            "replay_commits": sum(len(r["commits"]) for r in repos),
            "artifacts": sum(len(r["artifacts"]) for r in repos),
            "claims": sum(len(a["claims"]) for r in repos for a in r["artifacts"]),
            "pairs": sum(len(r["records"]) for r in repos),
        },
        "repos": [label.get(n, n) for n in names],
        "metrics": {name: summary["metrics"][name] for name in _METRIC_FIELDS},
        "panel": {name: summary["panel"][name] for name in _PANEL_FIELDS},
        "spot_check": {
            **{name: spot[name] for name in _SPOT_CHECK_FIELDS},
            "recommendation": spot["recommendation"],
            "reasons": list(spot["reasons"]),
        },
    }


def _fmt(value: float, ci: list[float]) -> str:
    return f"{value:.2f} ({ci[0]:.2f}-{ci[1]:.2f})"


def render_markdown(pub: dict) -> str:
    m, comp = pub["metrics"], pub["composition"]
    spot, panel = pub["spot_check"], pub["panel"]
    lines: list[str] = []
    if spot["recommendation"] == "HOLD_PUBLIC_CLAIMS":
        lines += [
            "> **NOT CLEARED FOR PUBLIC USE** — the owner recommendation is",
            "> HOLD_PUBLIC_CLAIMS; do not publish or quote these numbers.",
            "",
        ]
    lines += [
        "# dorian benchmark — public summary",
        "",
        "## Headline metrics",
        "",
        "| metric | value (95% CI) |",
        "| --- | --- |",
        f"| baseline precision | {_fmt(m['baseline_precision'], m['baseline_precision_ci'])} |",
        f"| dorian precision | {_fmt(m['dorian_precision'], m['dorian_precision_ci'])} |",
        f"| dorian recall | {_fmt(m['dorian_recall'], m['dorian_recall_ci'])} |",
        f"| FP reduction | {_fmt(m['fp_reduction'], m['fp_reduction_ci'])} |",
        "",
        f"Scored over {m['pairs']} (artifact, commit) pair(s); "
        f"{m['excluded']} pair(s) excluded by owner review.",
        "",
        "## Benchmark composition",
        "",
        f"{comp['repo_windows']} repo window(s), {comp['replay_commits']} replay commit(s), "
        f"{comp['artifacts']} artifact(s), {comp['claims']} claim(s), "
        f"{comp['pairs']} (artifact, commit) pair(s).",
        "",
        f"Repos: {', '.join(pub['repos'])}.",
        "",
        "## Ground-truth provenance",
        "",
        f"Ground truth: blind 3-judge model panel, {panel['pairs_judged']} pairs, "
        f"{panel['unanimous']} unanimous; owner spot-check of {spot['reviewed_pairs']} pairs, "
        f"recommendation {spot['recommendation']}.",
        "",
        "## Caveat",
        "",
        _CAVEAT,
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.public_summary", description=__doc__)
    ap.add_argument("--summary", default=f"{RESULTS_DIR}/owner_checked_summary.json")
    ap.add_argument("--results", default=f"{RESULTS_DIR}/results.json")
    ap.add_argument(
        "--allow-repo",
        action="append",
        default=[],
        metavar="NAME",
        help="repo name allowed to appear verbatim (repeatable; default: none)",
    )
    ap.add_argument("--out", default=f"{RESULTS_DIR}/public_summary.md")
    ap.add_argument("--json-out", default=f"{RESULTS_DIR}/public_summary.json")
    args = ap.parse_args(argv)

    try:
        summary = _read_json(args.summary)
        results = _read_json(args.results)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"public-summary: cannot read input: {exc}", file=sys.stderr)
        return 2
    try:
        pub = compose(summary, results, set(args.allow_repo))
    except (KeyError, TypeError) as exc:
        print(f"public-summary: malformed input: {exc}", file=sys.stderr)
        return 2

    _write_text(args.out, render_markdown(pub))
    _write_text(args.json_out, json.dumps(pub, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(
        f"public summary: cleared={str(pub['cleared']).lower()} "
        f"recommendation={pub['spot_check']['recommendation']} -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
