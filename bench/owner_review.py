"""Owner spot-check workflow for the v0.0 real-history benchmark labels.

Usage:
    python -m bench.owner_review make-owner-review [--seed 42 ...]
    python -m bench.owner_review merge-owner-review [...]
    python -m bench.owner_review owner-metrics [...]
    (or: dorian bench <subcommand> ... from a dorian checkout)

make-owner-review draws a risk-focused sample of (artifact, commit) pairs from
the model-panel universe and writes a BLINDED review sheet (markdown) plus a
fill-in jsonl: no per-pair panel verdicts, vote counts, judge text, or alarm
flags appear in either output. merge-owner-review folds the owner's labels
back into a metrics-compatible ground truth (gt['truth'] is drop-in for
bench.metrics --gt). owner-metrics recomputes H2 on the owner-checked truth,
reusing bench.metrics math and gates, and prints a PASS / EXPAND / HOLD
recommendation (advisory: always exits 0); it also writes the canonical
owner-checked summary (--summary-out) consumed by bench.public_summary.

Outputs are deterministic for a given seed — no timestamps; JSON is dumped
with indent=2 + sort_keys and a trailing newline. Everything lands under
bench/real/ by default, which is gitignored: review outputs may embed private
repo content and must never be committed.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

from bench import metrics

RESULTS_DIR = "bench/real/results"

LABELS = ("true_stale", "not_stale", "unsure", "already_stale", "out_of_scope")

REASON_UNSURE = "labels may require private context not visible in the packet"

Pair = tuple[str, str]  # (key "<repo>:<artifact>", commit sha)


# --- shared io --------------------------------------------------------------


def _read_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_jsonl(path: str) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _write_json(path: str, obj) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _write_text(path: str, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


_INPUT_ERRORS = (OSError, json.JSONDecodeError)


# --- shared label semantics -------------------------------------------------


def _flips_truth(label: str, panel: bool) -> bool:
    """True when a decisive owner label changes the pair's truth value vs panel."""
    if label == "true_stale":
        return not panel
    if label in ("not_stale", "already_stale"):
        return panel
    if label == "out_of_scope":
        return panel  # an override only when the pair was panel-true
    return False


def _panel_labels(panel: dict) -> dict[Pair, bool]:
    return {(d["key"], d["commit"]): bool(d["label"]) for d in panel["detail"]}


def _owner_stats(owner_rows: list[dict], panel_label: dict[Pair, bool]) -> dict:
    reviewed = unsure = out_of_scope = 0
    overrides: list[dict] = []
    for row in owner_rows:
        label = (row.get("owner_label") or "").strip()
        if not label:
            continue
        reviewed += 1
        key = f"{row['repo']}:{row['artifact']}"
        commit = row["commit"]
        if label == "unsure":
            unsure += 1
            continue
        if label == "out_of_scope":
            out_of_scope += 1
        panel = panel_label.get((key, commit), False)
        if _flips_truth(label, panel):
            overrides.append({"key": key, "commit": commit, "panel": panel, "owner": label})
    return {
        "reviewed": reviewed,
        "unsure": unsure,
        "out_of_scope": out_of_scope,
        "overrides": overrides,
    }


def _same_direction_pattern(overrides: list[dict]) -> bool:
    """>=2 overrides in the same direction within one repo window."""
    groups: Counter[tuple[str, str]] = Counter()
    for o in overrides:
        repo = o["key"].split(":", 1)[0]
        direction = "to_true" if o["owner"] == "true_stale" else "to_false"
        groups[(repo, direction)] += 1
    return any(n >= 2 for n in groups.values())


# --- make-owner-review ------------------------------------------------------


def select_pairs(
    detail: list[dict],
    queue: dict[Pair, dict],
    *,
    seed: int,
    n_baseline_fp: int,
    n_quiet: int,
    n_random: int,
) -> tuple[list[Pair], dict[str, int]]:
    """Risk-focused sample over the panel-detail universe (see module doc)."""
    universe: set[Pair] = {(d["key"], d["commit"]) for d in detail}
    panel_true = {(d["key"], d["commit"]) for d in detail if d["label"]}
    dorian_alarmed = {p for p, q in queue.items() if q["dorian_alarm"] and p in universe}
    known_fn = panel_true - dorian_alarmed

    rng = random.Random(seed)
    selected: list[Pair] = []
    chosen: set[Pair] = set()

    def take(pairs) -> None:
        for p in sorted(pairs):
            if p not in chosen:
                chosen.add(p)
                selected.append(p)

    def sample(candidates, n: int) -> list[Pair]:
        pool = sorted(p for p in candidates if p not in chosen)
        picked = rng.sample(pool, min(n, len(pool)))
        take(picked)
        return picked

    take(panel_true)  # S1: every panel-true pair
    take(dorian_alarmed)  # S2: every dorian-alarm pair
    take(known_fn)  # S3: known-FN safety net (subset of S1, explicit union)
    s4 = sample(  # S4: baseline-only alarms the panel called benign
        (
            p
            for p, q in queue.items()
            if p in universe
            and q["baseline_alarm"]
            and not q["dorian_alarm"]
            and p not in panel_true
        ),
        n_baseline_fp,
    )
    s5 = sample((p for p in universe if p not in queue), n_quiet)  # S5: quiet controls
    s6 = sample(universe, n_random)  # S6: random remainder

    rng.shuffle(selected)  # position must not reveal the bucket
    counts = {
        "s1_panel_true": len(panel_true),
        "s2_dorian_alarm": len(dorian_alarmed),
        "s3_known_fn": len(known_fn),
        "s4_baseline_fp": len(s4),
        "s5_quiet": len(s5),
        "s6_random": len(s6),
    }
    return selected, counts


def _private_prefix(repo: str, prefixes: list[str]) -> str | None:
    for prefix in prefixes:
        if repo.startswith(prefix):
            return prefix
    return None


def _repo_label(repo: str, prefix: str) -> str:
    suffix = repo[len(prefix) :].strip("-_")
    return f"private-{suffix}" if suffix else "private"


_HEADER = """\
# Owner spot-check — blinded review sheet

> **LOCAL-ONLY.** This file lives under `bench/real/`, which is gitignored.
> Do not commit it, and do not share it unredacted.

Fill in your verdicts in the companion jsonl (`{jsonl_name}`): for each
`pair_id` below, set `owner_label` to one of the five labels and optionally
add an `owner_note`. Leave `owner_label` empty to skip a pair.

Labels:

- `true_stale` — this commit made >=1 sealed claim false.
- `not_stale` — no sealed claim was falsified by this commit.
- `unsure` — cannot decide from available context.
- `already_stale` — the claim was already false before this commit.
- `out_of_scope` — pair should not be in the benchmark (binding error,
  vendored file, etc.); excluded from metrics.

Decision rules (computed by `owner-metrics` after `merge-owner-review`):

- HOLD_PUBLIC_CLAIMS — recall or FP reduction lands below its gate, or more
  than 10% of reviewed pairs are `unsure`.
- EXPAND_TO_FULL_201 — more than 2 material disagreements with the automated
  labels, or >=2 same-direction disagreements inside one repo window.
- PASS — otherwise.

## Pairs
"""


def _render_pair(
    pid: str,
    key: str,
    sha: str,
    subject: str,
    files: list[str],
    claims: list[dict],
    *,
    redact: bool,
    prefixes: list[str],
    doc_index: dict[str, int],
    jsonl_name: str,
) -> list[str]:
    repo, artifact = key.split(":", 1)
    prefix = _private_prefix(repo, prefixes) if redact else None
    lines = [f"### {pid}", ""]
    if prefix is not None:
        lines.append(
            f"- repo: {_repo_label(repo, prefix)} - artifact: private-doc-{doc_index[key]}"
        )
        lines.append(f'- commit: {sha} — "[redacted]"')
        if claims:
            lines.append("- claims under review:")
            lines += [
                f"  - {c['id']}: [redacted: private claim {c['id']} — review locally]"
                for c in claims
            ]
        else:
            lines.append("- claims under review: (none recorded)")
        lines.append(f"- changed files: {len(files)} files changed (paths redacted)")
    else:
        lines.append(f"- repo: {repo} - artifact: {artifact}")
        lines.append(f'- commit: {sha} — "{subject}"')
        if claims:
            lines.append("- claims under review:")
            lines += [f"  - {c['id']}: {c['text']}" for c in claims]
        else:
            lines.append("- claims under review: (none recorded)")
        if files:
            lines.append("- changed files:")
            lines += [f"  - {f}" for f in files[:8]]
            if len(files) > 8:
                lines.append(f"  - ... and {len(files) - 8} more")
        else:
            lines.append("- changed files: (none recorded)")
    lines.append(f"- inspect: git -C bench/real/workspace/{repo} show {sha}")
    lines.append(f"- label -> {jsonl_name} pair {pid}")
    lines.append("")
    return lines


def cmd_make_owner_review(args: argparse.Namespace) -> int:
    try:
        panel = _read_json(args.panel)
        queue_rows = _read_jsonl(args.queue)
        batches = _read_json(args.batches)
        results = _read_json(args.results)
    except _INPUT_ERRORS as exc:
        print(f"make-owner-review: cannot read input: {exc}", file=sys.stderr)
        return 2

    queue = {(f"{r['repo']}:{r['artifact']}", r["commit"]): r for r in queue_rows}
    claims_by_key = {b["key"]: b["claims"] for b in batches}
    commit_info = {
        (repo["name"], c["sha"]): c for repo in results["repos"] for c in repo["commits"]
    }

    selected, counts = select_pairs(
        panel["detail"],
        queue,
        seed=args.seed,
        n_baseline_fp=args.n_baseline_fp,
        n_quiet=args.n_quiet,
        n_random=args.n_random,
    )
    prefixes = [p.strip() for p in args.private_prefixes.split(",") if p.strip()]
    doc_index = {
        key: k
        for k, key in enumerate(
            sorted(
                {
                    key
                    for key, _sha in selected
                    if _private_prefix(key.split(":", 1)[0], prefixes) is not None
                }
            ),
            start=1,
        )
    }
    jsonl_name = Path(args.jsonl_out).name

    md_lines = [_HEADER.format(jsonl_name=jsonl_name)]
    rows: list[dict] = []
    for i, (key, sha) in enumerate(selected, start=1):
        pid = f"P-{i:03d}"
        repo, artifact = key.split(":", 1)
        q = queue.get((key, sha))
        if q is not None:
            subject, files = q["subject"], list(q["changed_files"])
        else:
            info = commit_info.get((repo, sha), {})
            subject, files = info.get("subject", ""), list(info.get("changed_files", []))
        md_lines += _render_pair(
            pid,
            key,
            sha,
            subject,
            files,
            claims_by_key.get(key, []),
            redact=args.redact_private,
            prefixes=prefixes,
            doc_index=doc_index,
            jsonl_name=jsonl_name,
        )
        private = _private_prefix(repo, prefixes) is not None
        rows.append(
            {
                "pair_id": pid,
                "repo": repo,
                "artifact": artifact,
                "commit": sha,
                "subject": "[redacted]" if args.redact_private and private else subject,
                "owner_label": "",
                "owner_note": "",
            }
        )

    _write_text(args.out, "\n".join(md_lines).rstrip("\n") + "\n")
    _write_text(
        args.jsonl_out,
        "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows),
    )
    bucket_summary = " ".join(f"{name}={n}" for name, n in counts.items())
    print(f"owner spot-check: {len(selected)} pairs ({bucket_summary}) -> {args.out}")
    return 0


# --- merge-owner-review -----------------------------------------------------


def cmd_merge_owner_review(args: argparse.Namespace) -> int:
    try:
        panel = _read_json(args.panel)
        owner_rows = _read_jsonl(args.owner)
    except _INPUT_ERRORS as exc:
        print(f"merge-owner-review: cannot read input: {exc}", file=sys.stderr)
        return 2

    panel_label = _panel_labels(panel)
    truth: dict[str, set[str]] = {}
    for (key, commit), label in panel_label.items():
        truth.setdefault(key, set())
        if label:
            truth[key].add(commit)

    excluded: list[dict] = []
    overrides: list[dict] = []
    unsure: list[dict] = []
    for row in owner_rows:
        label = (row.get("owner_label") or "").strip()
        if not label:
            continue
        key = f"{row['repo']}:{row['artifact']}"
        commit = row["commit"]
        if label not in LABELS:
            pair_name = row.get("pair_id") or f"{key}@{commit}"
            print(
                f"merge-owner-review: unknown owner_label {label!r} for pair {pair_name}",
                file=sys.stderr,
            )
            return 2
        panel_true = panel_label.get((key, commit), False)
        if label == "unsure":
            unsure.append({"key": key, "commit": commit})
            continue
        if label == "true_stale":
            truth.setdefault(key, set()).add(commit)
        else:  # not_stale | already_stale | out_of_scope: absent from truth
            truth.setdefault(key, set()).discard(commit)
        if label == "out_of_scope":
            excluded.append({"key": key, "commit": commit})
        if _flips_truth(label, panel_true):
            overrides.append({"key": key, "commit": commit, "panel": panel_true, "owner": label})

    out = {
        "truth": {key: sorted(shas) for key, shas in truth.items()},
        "excluded": excluded,
        "overrides": overrides,
        "unsure": unsure,
    }
    _write_json(args.out, out)
    print(
        f"gt_owner_checked: {sum(len(v) for v in out['truth'].values())} true commit(s), "
        f"{len(excluded)} excluded, {len(overrides)} override(s), {len(unsure)} unsure "
        f"-> {args.out}"
    )
    return 0


# --- owner-metrics ----------------------------------------------------------


def cmd_owner_metrics(args: argparse.Namespace) -> int:
    try:
        results = _read_json(args.results)
        gt = _read_json(args.gt)
        owner_rows = _read_jsonl(args.owner)
        panel = _read_json(args.panel)
    except _INPUT_ERRORS as exc:
        print(f"owner-metrics: cannot read input: {exc}", file=sys.stderr)
        return 2

    truth = {key: set(shas) for key, shas in gt["truth"].items()}
    excluded = {(e["key"], e["commit"]) for e in gt.get("excluded", [])}
    pairs: list[dict] = []
    dropped = 0
    for repo in results["repos"]:
        for rec in repo["records"]:
            key = f"{repo['name']}:{rec['artifact']}"
            if (key, rec["commit"]) in excluded:
                dropped += 1
                continue
            pairs.append(
                {
                    "baseline": bool(rec["baseline_alarm"]),
                    "dorian": bool(rec["dorian_alarm"]),
                    "true": rec["commit"] in truth.get(key, set()),
                }
            )
    if not pairs:
        print("owner-metrics: no (artifact, commit) pairs left after exclusions", file=sys.stderr)
        return 2

    cis = metrics.bootstrap_cis(pairs)
    systems = {}
    for system in ("baseline", "dorian"):
        s = metrics.prf(pairs, system)
        systems[system] = {
            "tp": s["tp"],
            "fp": s["fp"],
            "fn": s["fn"],
            "precision": s["precision"],
            "recall": s["recall"],
            "precision_ci": cis[f"{system}_precision"],
            "recall_ci": cis[f"{system}_recall"],
        }
    fpr = metrics.fp_reduction(pairs)

    stats = _owner_stats(owner_rows, _panel_labels(panel))
    overrides = stats["overrides"]
    pattern = _same_direction_pattern(overrides)
    unsure_ratio = stats["unsure"] / stats["reviewed"] if stats["reviewed"] else 0.0

    hold_reasons: list[str] = []
    recall = systems["dorian"]["recall"]
    if recall < metrics.GATE_RECALL:
        hold_reasons.append(f"dorian recall {recall:.2f} < gate {metrics.GATE_RECALL}")
    if fpr < metrics.GATE_FP_REDUCTION:
        hold_reasons.append(f"fp_reduction {fpr:.2f} < gate {metrics.GATE_FP_REDUCTION}")
    if unsure_ratio > 0.10:
        hold_reasons.append(REASON_UNSURE)
    expand_reasons: list[str] = []
    if len(overrides) > 2:
        expand_reasons.append(f"material disagreements {len(overrides)} > 2")
    if pattern:
        expand_reasons.append("same-direction override pattern within one repo window")
    if hold_reasons:
        recommendation = "HOLD_PUBLIC_CLAIMS"
    elif expand_reasons:
        recommendation = "EXPAND_TO_FULL_201"
    else:
        recommendation = "PASS"

    out = {
        "pairs": len(pairs),
        "excluded": dropped,
        "systems": systems,
        "fp_reduction": fpr,
        "fp_reduction_ci": cis["fp_reduction"],
        "owner_review": {
            "reviewed": stats["reviewed"],
            "unsure": stats["unsure"],
            "out_of_scope": stats["out_of_scope"],
            "overrides": len(overrides),
            "override_detail": overrides,
            "same_direction_pattern": pattern,
        },
        "recommendation": recommendation,
        "reasons": hold_reasons + expand_reasons,
    }
    _write_json(args.out, out)
    summary = {
        "schema": "dorian-owner-checked-summary-v1",
        "spot_check": {
            "reviewed_pairs": stats["reviewed"],
            "overrides": len(overrides),
            "unsure": stats["unsure"],
            "out_of_scope": stats["out_of_scope"],
            "recommendation": recommendation,
            "reasons": out["reasons"],
        },
        "panel": {
            name: panel.get(name, 0) for name in ("pairs_judged", "unanimous", "labeled_true")
        },
        "metrics": {
            "pairs": len(pairs),
            "excluded": dropped,
            "fp_reduction": fpr,
            "fp_reduction_ci": cis["fp_reduction"],
            "dorian_recall": systems["dorian"]["recall"],
            "dorian_recall_ci": systems["dorian"]["recall_ci"],
            "dorian_precision": systems["dorian"]["precision"],
            "dorian_precision_ci": systems["dorian"]["precision_ci"],
            "baseline_precision": systems["baseline"]["precision"],
            "baseline_precision_ci": systems["baseline"]["precision_ci"],
        },
    }
    _write_json(args.summary_out, summary)
    print(
        f"RECOMMENDATION: {recommendation} — pairs={len(pairs)} excluded={dropped} "
        f"dorian_recall={recall:.2f} fp_reduction={fpr:.2f} "
        f"overrides={len(overrides)} unsure={stats['unsure']}/{stats['reviewed']}"
    )
    for reason in out["reasons"]:
        print(f"  reason: {reason}")
    return 0


# --- argparse ---------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.owner_review", description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    mk = sub.add_parser("make-owner-review", help="write the blinded review sheet + fill-in jsonl")
    mk.add_argument("--panel", default=f"{RESULTS_DIR}/panel_summary.json")
    mk.add_argument("--queue", default=f"{RESULTS_DIR}/labeling_queue.jsonl")
    mk.add_argument("--batches", default=f"{RESULTS_DIR}/judge_batches.json")
    mk.add_argument("--results", default=f"{RESULTS_DIR}/results.json")
    mk.add_argument("--out", default=f"{RESULTS_DIR}/owner_spotcheck.md")
    mk.add_argument("--jsonl-out", default=f"{RESULTS_DIR}/owner_spotcheck.jsonl")
    mk.add_argument("--mode", choices=["risk-focused"], default="risk-focused")
    mk.add_argument("--redact-private", action="store_true")
    mk.add_argument(
        "--private-prefixes", default="", help="comma list of private repo-name prefixes to redact"
    )
    mk.add_argument("--seed", type=int, default=42)
    mk.add_argument("--n-baseline-fp", type=int, default=28)
    mk.add_argument("--n-quiet", type=int, default=18)
    mk.add_argument("--n-random", type=int, default=12)
    mk.set_defaults(func=cmd_make_owner_review)

    mg = sub.add_parser("merge-owner-review", help="fold owner labels into a checked ground truth")
    mg.add_argument("--panel", default=f"{RESULTS_DIR}/panel_summary.json")
    mg.add_argument("--owner", default=f"{RESULTS_DIR}/owner_spotcheck.jsonl")
    mg.add_argument("--out", default=f"{RESULTS_DIR}/gt_owner_checked.json")
    mg.set_defaults(func=cmd_merge_owner_review)

    om = sub.add_parser("owner-metrics", help="recompute H2 + PASS/EXPAND/HOLD recommendation")
    om.add_argument("--results", default=f"{RESULTS_DIR}/results.json")
    om.add_argument("--gt", default=f"{RESULTS_DIR}/gt_owner_checked.json")
    om.add_argument("--owner", default=f"{RESULTS_DIR}/owner_spotcheck.jsonl")
    om.add_argument("--panel", default=f"{RESULTS_DIR}/panel_summary.json")
    om.add_argument("--out", default=f"{RESULTS_DIR}/owner_metrics.json")
    om.add_argument("--summary-out", default=f"{RESULTS_DIR}/owner_checked_summary.json")
    om.set_defaults(func=cmd_owner_metrics)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
