"""Extraction-churn measurement: fixed-params LLM extraction re-runs on one doc.

Usage:
    python -m bench.churn --doc path/to/doc.md \\
        --out bench/real/results/churn_compliant.json

Calls extract_claims N times on the same LF-normalized doc with use_cache=False
(every run is a fresh SDK call; nothing is read from or written to the cache)
and temperature=0.0, then scores how much the extracted claim TEXTS move between
runs. --mode selects the extraction strategy under measurement (restate or
anchor-first; see dorian.extract) and is recorded in the result. Texts are
normalized (lowercase; backticks/asterisks/double+single quotes stripped;
whitespace collapsed; stripped; trailing '.' dropped) and compared pairwise
over normalized sets:

- exact distance: 1 - |A intersect B| / |A union B|
- fuzzy distance: greedy best-match with difflib.SequenceMatcher ratio >= --thr;
  1 - matches / (|A| + |B| - matches)

The output JSON records the doc BASENAME only (never the full path) and the
full sha256 of the selected mode's extraction protocol (prompt + tool schema),
so a churn result is tied to the exact protocol that produced it; no
timestamps. Gate (advisory): exact_mean < 0.20.

Exit codes: 0 PASS · 2 input/infra error (missing doc, extractor unavailable) ·
3 measured FAIL (above the gate — advisory failure, not infra).
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

from dorian import extract
from dorian.model import lf_normalize, sha256_hex

GATE = 0.20


def normalize(text: str) -> str:
    """Lowercase, strip `*\"' chars, collapse whitespace, strip, rstrip '.'."""
    text = text.lower().translate(str.maketrans("", "", "`*\"'"))
    return " ".join(text.split()).rstrip(".")


def exact_distance(a: set[str], b: set[str]) -> float:
    """Jaccard distance 1 - |A intersect B| / |A union B|; two empty sets are identical."""
    if not a and not b:
        return 0.0
    return 1.0 - len(a & b) / len(a | b)


def fuzzy_distance(a: set[str], b: set[str], thr: float) -> float:
    """Greedy best-match Jaccard distance: each A item consumes its best-ratio
    unmatched B item when SequenceMatcher ratio >= thr; 1 - m / (|A|+|B|-m)."""
    if not a and not b:
        return 0.0
    remaining = sorted(b)
    matches = 0
    for item in sorted(a):
        best_ratio, best_idx = 0.0, -1
        for idx, candidate in enumerate(remaining):
            ratio = difflib.SequenceMatcher(None, item, candidate).ratio()
            if ratio > best_ratio:
                best_ratio, best_idx = ratio, idx
        if best_idx >= 0 and best_ratio >= thr:
            matches += 1
            del remaining[best_idx]
    return 1.0 - matches / (len(a) + len(b) - matches)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.churn", description=__doc__)
    ap.add_argument("--doc", required=True, help="artifact document to extract from")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument(
        "--mode",
        choices=["restate", "anchor"],
        default="restate",
        help="extraction strategy under measurement (see dorian.extract)",
    )
    ap.add_argument("--model", default="claude-fable-5")
    ap.add_argument("--thr", type=float, default=0.75, help="fuzzy match ratio threshold")
    ap.add_argument("--out", default="bench/real/results/churn_compliant.json")
    ap.add_argument("--cache-dir", default=".claims_cache")  # passed through; bypassed per run
    args = ap.parse_args(argv)

    if args.runs < 2:
        print("churn: --runs must be >= 2 (a single run measures nothing)", file=sys.stderr)
        return 2

    doc = Path(args.doc)
    try:
        raw = lf_normalize(doc.read_bytes())
    except OSError as exc:
        print(f"churn: cannot read --doc: {exc}", file=sys.stderr)
        return 2
    text = raw.decode("utf-8", errors="replace")

    per_run_texts: list[list[str]] = []
    try:
        for _ in range(args.runs):
            claims = extract.extract_claims(
                text,
                model=args.model,
                cache_dir=Path(args.cache_dir),
                artifact_hash=sha256_hex(raw),
                use_cache=False,
                temperature=0.0,
                mode=args.mode,
            )
            per_run_texts.append([c.text for c in claims])
    except Exception as exc:  # extractor unavailable / SDK failure: infra, not FAIL
        print(f"churn: extraction failed: {exc}", file=sys.stderr)
        return 2

    norm_sets = [{normalize(t) for t in texts} for texts in per_run_texts]
    exact_distances: list[float] = []
    fuzzy_distances: list[float] = []
    for i in range(len(norm_sets)):
        for j in range(i + 1, len(norm_sets)):
            exact_distances.append(exact_distance(norm_sets[i], norm_sets[j]))
            fuzzy_distances.append(fuzzy_distance(norm_sets[i], norm_sets[j], args.thr))
    exact_mean = sum(exact_distances) / len(exact_distances) if exact_distances else 0.0
    fuzzy_mean = sum(fuzzy_distances) / len(fuzzy_distances) if fuzzy_distances else 0.0
    passed = exact_mean < GATE

    # honest fixed-params record: models that deprecate the temperature
    # parameter (extract retries without it) are recorded as temperature null;
    # models that reject forced tool_choice are recorded as tool_choice auto
    temp_deprecated = extract.temperature_unsupported(args.model)
    forced_rejected = extract.forced_tools_unsupported(args.model)
    result = {
        "schema": "dorian-churn-v1",
        "doc": doc.name,  # basename only — never the full path
        "model": args.model,
        "mode": args.mode,
        "temperature": None if temp_deprecated else 0.0,
        "temperature_deprecated_by_model": temp_deprecated,
        "tool_choice": "auto" if forced_rejected else "forced",
        "prompt_hash": extract.prompt_hash(args.mode),
        "runs": args.runs,
        "per_run_claim_counts": [len(texts) for texts in per_run_texts],
        "exact_jaccard_distances": exact_distances,
        "fuzzy_jaccard_distances": fuzzy_distances,
        "exact_mean": exact_mean,
        "fuzzy_mean": fuzzy_mean,
        "threshold": args.thr,
        "gate": GATE,
        "pass": passed,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"churn: exact={exact_mean:.3f} fuzzy={fuzzy_mean:.3f} gate={GATE:.2f} "
        f"-> {'PASS' if passed else 'FAIL'}"
    )
    return 0 if passed else 3


if __name__ == "__main__":
    sys.exit(main())
