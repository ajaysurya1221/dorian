"""Planted-truth extraction gate runner (pre-registered in docs/EXTRACT_GATE.md).

Two subcommands:

  run        measure ONE generated document (doc.md + manifest.json from
             bench.plant): N draws (single extractions or consensus-of-K),
             planted-truth recall/precision, boundary-insensitive selection
             churn, text churn, and (anchor gate runs) the three metamorphic
             transforms. Writes one per-doc JSON.

  aggregate  merge per-doc JSONs, check instrument calibration, apply the
             pre-registered gates, and emit a verdict report (JSON + markdown).
             Exit codes: 0 promotion gate met, 3 rejection gate met,
             4 insufficient evidence, 2 usage/infra.

Pooled metrics are claim-weighted (total found / total planted across all
documents and draws), not doc-averaged. ValueError from extraction (e.g. "no
valid spans") is recorded as an EMPTY DRAW — a behavioral failure that hurts
recall and churn — never silently retried; transport/SDK errors are infra.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bench import metamorph  # noqa: E402
from bench.churn import exact_distance, normalize  # noqa: E402
from dorian import extract  # noqa: E402
from dorian.model import lf_normalize, sha256_hex  # noqa: E402

GATES = {  # pre-registered thresholds — docs/EXTRACT_GATE.md is normative
    "recall_pooled": 0.80,
    "recall_long_tier": 0.70,
    "precision_pooled": 0.75,
    "selection_churn_tier": 0.10,
    "text_churn_tier": 0.20,
    "invariance_pooled": 0.90,
    "reject_recall_pooled": 0.60,
    "reject_selection_churn_tier": 0.20,
}


def _one_draw(text: str, args: argparse.Namespace) -> tuple[list, str | None]:
    """One extraction draw; ValueError -> empty draw (behavioral failure)."""
    kwargs = {
        "model": args.model,
        "cache_dir": Path(".claims_cache"),
        "artifact_hash": sha256_hex(text.encode("utf-8")),
        "temperature": 0.0,
    }
    try:
        if args.consensus >= 2:
            return extract.extract_claims_consensus(text, k=args.consensus, **kwargs), None
        return extract.extract_claims(text, use_cache=False, mode=args.mode, **kwargs), None
    except ValueError as exc:
        return [], f"empty draw: {exc}"


def _draw_metrics(claims: list, claim_lines: set[int]) -> dict:
    spans = [(c.anchor.line_start, c.anchor.line_end) for c in claims if c.anchor is not None]
    covered = {ln for a, b in spans for ln in range(a, b + 1)}
    covered_claims = covered & claim_lines
    tp_spans = sum(1 for a, b in spans if any(ln in claim_lines for ln in range(a, b + 1)))
    return {
        "n_claims": len(claims),
        "n_spans": len(spans),
        "tp_spans": tp_spans,
        "covered_claim_lines": sorted(covered_claims),
        "found": len(covered_claims),
        "texts": sorted(normalize(c.text) for c in claims),
    }


def cmd_run(args: argparse.Namespace) -> int:
    doc_dir = Path(args.doc_dir)
    text = lf_normalize((doc_dir / "doc.md").read_bytes()).decode("utf-8")
    manifest = json.loads((doc_dir / "manifest.json").read_text(encoding="utf-8"))
    claim_lines = {c["line"] for c in manifest["claims"]}
    planted_norm = {normalize(c["text"]) for c in manifest["claims"]}

    failures: list[str] = []
    draws: list[dict] = []
    for _ in range(args.draws):
        claims, err = _one_draw(text, args)
        if err:
            failures.append(err)
        draws.append(_draw_metrics(claims, claim_lines))

    sel_pairs, text_pairs = [], []
    for i in range(len(draws)):
        for j in range(i + 1, len(draws)):
            sel_pairs.append(
                exact_distance(
                    set(draws[i]["covered_claim_lines"]), set(draws[j]["covered_claim_lines"])
                )
            )
            text_pairs.append(exact_distance(set(draws[i]["texts"]), set(draws[j]["texts"])))

    result: dict = {
        "doc_id": doc_dir.name,
        "tier": manifest["tier"],
        "seed": manifest["seed"],
        "doc_sha256": manifest["doc_sha256"],
        "mode": args.mode,
        "consensus": args.consensus,
        "draws": args.draws,
        "n_planted": len(claim_lines),
        "per_draw": draws,
        "selection_churn_mean": sum(sel_pairs) / len(sel_pairs) if sel_pairs else None,
        "text_churn_mean": sum(text_pairs) / len(text_pairs) if text_pairs else None,
        "failures": failures,
    }

    if args.mode == "anchor" and not args.skip_transforms:
        orig_extracted_planted = set(draws[0]["texts"]) & planted_norm
        transforms: dict = {}
        for name, fn in metamorph.TRANSFORMS.items():
            ttext, _present, absent = fn(text, manifest, seed=manifest["seed"])
            tclaims, terr = _one_draw(ttext, args)
            if terr:
                failures.append(f"{name}: {terr}")
            textracted = {normalize(c.text) for c in tclaims}
            if name == "claim_delete":
                victims_norm = {normalize(t) for t in absent}
                transforms[name] = {
                    "deleted": len(victims_norm),
                    "fabricated": sorted(victims_norm & textracted),
                }
            else:
                denom = len(orig_extracted_planted)
                survived = len(orig_extracted_planted & textracted)
                transforms[name] = {
                    "survived": survived,
                    "denom": denom,
                    "survival": survived / denom if denom else None,
                }
        result["transforms"] = transforms

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    found = sum(d["found"] for d in draws)
    total = len(claim_lines) * len(draws)
    print(
        f"extract-gate run {doc_dir.name} [{args.mode}"
        f"{f'/k{args.consensus}' if args.consensus else ''}]: "
        f"recall {found}/{total}, sel-churn "
        f"{result['selection_churn_mean']:.3f}, text-churn {result['text_churn_mean']:.3f}"
        if sel_pairs
        else f"extract-gate run {doc_dir.name}: done"
    )
    return 0


def _load_dir(path: str | None) -> list[dict]:
    if not path:
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(path).glob("*.json"))]


def _pooled_recall(results: list[dict]) -> float:
    found = sum(d["found"] for r in results for d in r["per_draw"])
    total = sum(r["n_planted"] * r["draws"] for r in results)
    return found / total if total else 0.0


def _pooled_precision(results: list[dict]) -> float:
    tp = sum(d["tp_spans"] for r in results for d in r["per_draw"])
    spans = sum(d["n_spans"] for r in results for d in r["per_draw"])
    return tp / spans if spans else 0.0


def _tier_mean(results: list[dict], key: str) -> dict[int, float]:
    tiers: dict[int, list[float]] = {}
    for r in results:
        if r[key] is not None:
            tiers.setdefault(r["tier"], []).append(r[key])
    return {t: sum(v) / len(v) for t, v in sorted(tiers.items())}


def cmd_aggregate(args: argparse.Namespace) -> int:
    gate = _load_dir(args.gate_dir)
    if not gate:
        print("extract-gate aggregate: no gate results found", file=sys.stderr)
        return 2
    calib_anchor = _load_dir(args.calib_anchor_dir)
    calib_restate = _load_dir(args.calib_restate_dir)

    # instrument calibration (docs/EXTRACT_GATE.md: validity precondition)
    calibration: dict = {"checked": bool(calib_anchor and calib_restate)}
    if calibration["checked"]:
        r_pool = sum(r["text_churn_mean"] for r in calib_restate) / len(calib_restate)
        a_pool = sum(r["text_churn_mean"] for r in calib_anchor) / len(calib_anchor)
        r_tiers = _tier_mean(calib_restate, "text_churn_mean")
        tiers_sorted = sorted(r_tiers)
        calibration.update(
            restate_pooled=r_pool,
            anchor_pooled=a_pool,
            restate_by_tier=r_tiers,
            a_restate_gt_anchor=r_pool > a_pool,
            b_restate_rises=r_tiers[tiers_sorted[-1]] > r_tiers[tiers_sorted[0]],
            c_restate_fails_long=r_tiers[tiers_sorted[-1]] >= 0.20,
        )
        calibration["valid"] = (
            calibration["a_restate_gt_anchor"]
            and calibration["b_restate_rises"]
            and calibration["c_restate_fails_long"]
        )

    recall_pooled = _pooled_recall(gate)
    precision_pooled = _pooled_precision(gate)
    sel_by_tier = _tier_mean(gate, "selection_churn_mean")
    text_by_tier = _tier_mean(gate, "text_churn_mean")
    long_tier = max(sel_by_tier) if sel_by_tier else 0
    recall_long = _pooled_recall([r for r in gate if r["tier"] == long_tier])

    surv = denom = fabricated = 0
    for r in gate:
        for name, t in r.get("transforms", {}).items():
            if name == "claim_delete":
                fabricated += len(t["fabricated"])
            elif t["denom"]:
                surv += t["survived"]
                denom += t["denom"]
    invariance = surv / denom if denom else None

    checks = {
        "recall_pooled >= 0.80": recall_pooled >= GATES["recall_pooled"],
        "recall_long_tier >= 0.70": recall_long >= GATES["recall_long_tier"],
        "precision_pooled >= 0.75": precision_pooled >= GATES["precision_pooled"],
        "selection_churn < 0.10 every tier": all(
            v < GATES["selection_churn_tier"] for v in sel_by_tier.values()
        ),
        "text_churn < 0.20 every tier": all(
            v < GATES["text_churn_tier"] for v in text_by_tier.values()
        ),
        "invariance >= 0.90": invariance is not None and invariance >= GATES["invariance_pooled"],
        "fabrication == 0": fabricated == 0,
        "calibration valid": bool(calibration.get("valid")),
    }
    rejects = {
        "recall_pooled < 0.60": recall_pooled < GATES["reject_recall_pooled"],
        "selection_churn >= 0.20 on a tier": any(
            v >= GATES["reject_selection_churn_tier"] for v in sel_by_tier.values()
        ),
        "fabrication > 0": fabricated > 0,
    }
    if all(checks.values()):
        verdict, code = "PROMOTION", 0
    elif any(rejects.values()):
        verdict, code = "REJECTION", 3
    else:
        verdict, code = "INSUFFICIENT", 4

    report = {
        "verdict": verdict,
        "gates": checks,
        "rejection_triggers": rejects,
        "metrics": {
            "recall_pooled": recall_pooled,
            "recall_long_tier": recall_long,
            "precision_pooled": precision_pooled,
            "selection_churn_by_tier": sel_by_tier,
            "text_churn_by_tier": text_by_tier,
            "invariance_pooled": invariance,
            "fabricated": fabricated,
            "docs": len(gate),
            "failures": sum(len(r["failures"]) for r in gate),
        },
        "calibration": calibration,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2, sort_keys=True))
    print(f"calibration valid: {calibration.get('valid')}")
    print(f"VERDICT: {verdict}")
    return code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.extract_gate", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="measure one generated document")
    run.add_argument("--doc-dir", required=True)
    run.add_argument("--mode", choices=["restate", "anchor"], default="anchor")
    run.add_argument("--consensus", type=int, default=0)
    run.add_argument("--draws", type=int, default=3)
    run.add_argument("--model", default="claude-sonnet-4-6")
    run.add_argument("--skip-transforms", action="store_true")
    run.add_argument("--out", required=True)
    agg = sub.add_parser("aggregate", help="merge results and apply the pre-registered gates")
    agg.add_argument("--gate-dir", required=True)
    agg.add_argument("--calib-anchor-dir")
    agg.add_argument("--calib-restate-dir")
    agg.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "run":
        if args.consensus and args.mode != "anchor":
            print("extract-gate: --consensus requires --mode anchor", file=sys.stderr)
            return 2
        try:
            return cmd_run(args)
        except Exception as exc:  # transport/SDK/file errors are infra, never a verdict
            print(f"extract-gate: infra error: {exc}", file=sys.stderr)
            return 2
    return cmd_aggregate(args)


if __name__ == "__main__":
    sys.exit(main())
