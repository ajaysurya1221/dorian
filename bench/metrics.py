"""H2 alarm-quality metrics + H1 table + the gate verdict.

Usage:
    python -m bench.metrics --results bench/results/results.json \\
        --gt bench/results/gt.json --out bench/results

Scoring is per (artifact, commit) pair: TP = alarm on a true-staleness commit,
FP = alarm on a benign commit, FN = missed true-staleness. Precision/recall
with an empty denominator are defined as 1.0 (a system that never alarms on a
window with no true staleness is perfect, not undefined).
fp_reduction = FP_baseline / max(1, FP_dorian).

Bootstrap 95% CIs: 1000 resamples of the pair list with replacement using
random.Random(42); every metric is computed on the same resample sequence, so
the whole report is deterministic given its inputs. The only timestamp is the
'Generated:' header line of report.md; metrics.json carries none.

Gates (v0.0 kill criteria): H1 overall >= 0.40, fp_reduction >= 2.0,
dorian recall >= 0.85. report.md ends with a single VERDICT line.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

GATE_H1 = 0.40
GATE_FP_REDUCTION = 2.0
GATE_RECALL = 0.85

BOOTSTRAP_N = 1000
BOOTSTRAP_SEED = 42


def build_pairs(results: dict, gt: dict) -> list[dict]:
    """Flatten results + ground truth into scored (artifact, commit) pairs."""
    truth = {key: set(shas) for key, shas in gt["truth"].items()}
    pairs: list[dict] = []
    for repo in results["repos"]:
        for rec in repo["records"]:
            key = f"{repo['name']}:{rec['artifact']}"
            pairs.append(
                {
                    "baseline": bool(rec["baseline_alarm"]),
                    "dorian": bool(rec["dorian_alarm"]),
                    "true": rec["commit"] in truth.get(key, set()),
                }
            )
    return pairs


def prf(pairs: list[dict], system: str) -> dict:
    tp = sum(1 for p in pairs if p[system] and p["true"])
    fp = sum(1 for p in pairs if p[system] and not p["true"])
    fn = sum(1 for p in pairs if not p[system] and p["true"])
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": len(pairs) - tp - fp - fn,
        "precision": tp / (tp + fp) if tp + fp else 1.0,
        "recall": tp / (tp + fn) if tp + fn else 1.0,
    }


def fp_reduction(pairs: list[dict]) -> float:
    return prf(pairs, "baseline")["fp"] / max(1, prf(pairs, "dorian")["fp"])


def _ci(samples: list[float]) -> list[float]:
    s = sorted(samples)
    n = len(s)
    return [s[int(0.025 * n)], s[min(n - 1, int(0.975 * n))]]


def bootstrap_cis(
    pairs: list[dict], n: int = BOOTSTRAP_N, seed: int = BOOTSTRAP_SEED
) -> dict[str, list[float]]:
    """95% CIs over `n` resamples (with replacement) of the pair list."""
    rng = random.Random(seed)
    acc: dict[str, list[float]] = {
        "baseline_precision": [],
        "baseline_recall": [],
        "dorian_precision": [],
        "dorian_recall": [],
        "fp_reduction": [],
    }
    for _ in range(n):
        sample = [pairs[rng.randrange(len(pairs))] for _ in range(len(pairs))]
        b, d = prf(sample, "baseline"), prf(sample, "dorian")
        acc["baseline_precision"].append(b["precision"])
        acc["baseline_recall"].append(b["recall"])
        acc["dorian_precision"].append(d["precision"])
        acc["dorian_recall"].append(d["recall"])
        acc["fp_reduction"].append(b["fp"] / max(1, d["fp"]))
    return {name: _ci(samples) for name, samples in acc.items()}


def compute(results: dict, gt: dict) -> dict:
    pairs = build_pairs(results, gt)
    if not pairs:
        raise ValueError("no (artifact, commit) records in results")

    h1_per = {
        f"{repo['name']}:{artifact['uri']}": artifact["backed_claim_ratio"]
        for repo in results["repos"]
        for artifact in repo["artifacts"]
    }
    h1_overall = sum(h1_per.values()) / len(h1_per)

    cis = bootstrap_cis(pairs)
    systems = {}
    for system in ("baseline", "dorian"):
        systems[system] = {
            **prf(pairs, system),
            "precision_ci": cis[f"{system}_precision"],
            "recall_ci": cis[f"{system}_recall"],
        }
    fpr = fp_reduction(pairs)

    gates = {
        "h1": {"value": h1_overall, "threshold": GATE_H1, "pass": h1_overall >= GATE_H1},
        "fp_reduction": {
            "value": fpr,
            "threshold": GATE_FP_REDUCTION,
            "pass": fpr >= GATE_FP_REDUCTION,
        },
        "recall": {
            "value": systems["dorian"]["recall"],
            "threshold": GATE_RECALL,
            "pass": systems["dorian"]["recall"] >= GATE_RECALL,
        },
    }
    return {
        "pairs": len(pairs),
        "h1": {"per_artifact": h1_per, "overall": h1_overall},
        "systems": systems,
        "fp_reduction": fpr,
        "fp_reduction_ci": cis["fp_reduction"],
        "gates": gates,
        "verdict": "PASS" if all(g["pass"] for g in gates.values()) else "FAIL",
    }


def verdict_line(m: dict) -> str:
    g = m["gates"]
    return (
        f"VERDICT: {m['verdict']} — "
        f"h1={g['h1']['value']:.2f} (>={GATE_H1}), "
        f"fp_reduction={g['fp_reduction']['value']:.2f} (>={GATE_FP_REDUCTION}), "
        f"dorian_recall={g['recall']['value']:.2f} (>={GATE_RECALL})"
    )


def render_report(m: dict) -> str:
    lines = [
        "# dorian bench report",
        "",
        f"Generated: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "",
        "## H1 — backed claim ratio",
        "",
        "| artifact | backed_claim_ratio |",
        "| --- | --- |",
    ]
    lines += [f"| {key} | {ratio:.2f} |" for key, ratio in sorted(m["h1"]["per_artifact"].items())]
    lines += [
        "",
        f"Overall H1: {m['h1']['overall']:.2f}",
        "",
        f"## H2 — alarm quality over {m['pairs']} (artifact, commit) pair(s)",
        "",
        "| system | TP | FP | FN | precision (95% CI) | recall (95% CI) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name in ("baseline", "dorian"):
        s = m["systems"][name]
        lines.append(
            f"| {name} | {s['tp']} | {s['fp']} | {s['fn']} "
            f"| {s['precision']:.2f} ({s['precision_ci'][0]:.2f}-{s['precision_ci'][1]:.2f}) "
            f"| {s['recall']:.2f} ({s['recall_ci'][0]:.2f}-{s['recall_ci'][1]:.2f}) |"
        )
    lines += [
        "",
        f"FP reduction (baseline FP / max(1, dorian FP)): {m['fp_reduction']:.2f} "
        f"(95% CI {m['fp_reduction_ci'][0]:.2f}-{m['fp_reduction_ci'][1]:.2f})",
        "",
        verdict_line(m),
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.metrics", description=__doc__)
    ap.add_argument("--results", default="bench/results/results.json")
    ap.add_argument("--gt", default="bench/results/gt.json")
    ap.add_argument("--out", default="bench/results")
    args = ap.parse_args(argv)

    results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    gt = json.loads(Path(args.gt).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    m = compute(results, gt)
    (out / "metrics.json").write_text(
        json.dumps(m, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "report.md").write_text(render_report(m), encoding="utf-8")
    print(verdict_line(m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
