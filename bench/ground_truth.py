"""Heuristic ground truth + human labeling queue for the replay benchmark.

Usage:
    python -m bench.ground_truth --results bench/results/results.json \\
        --out bench/results

GROUND-TRUTH APPROXIMATION (deliberately crude, documented): when a LATER
commit inside the replay window edits the artifact file itself, we read it as
the author repairing drift, and mark the NEAREST EARLIER support-touching
commit (one whose record carries a baseline alarm) as true-staleness. Known
failure modes: a benign support touch followed by an artifact edit is
mislabeled true, and a breaking commit never followed by an artifact edit is
missed — hence the labeling queue for human adjudication. Scripted repos (the
SELFTEST) record exact `breaking_commits` in results.json, which take
precedence over the heuristic.

Outputs (under --out):
- gt.json: {"truth": {"<repo>:<artifact>": [commit sha, ...]}}
- labeling_queue.jsonl: one row per alarmed (artifact, commit) — commit
  subject, changed files, broken-claim texts — ready for human labeling.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def heuristic_truth(repo: dict, artifact_uri: str) -> list[str]:
    """Approximate true-staleness commits for one artifact (see module doc)."""
    commits = repo["commits"]
    baseline_by_sha = {
        r["commit"]: r.get("baseline_alarm", False)
        for r in repo["records"]
        if r["artifact"] == artifact_uri
    }
    truth: list[str] = []
    for j, commit in enumerate(commits):
        if artifact_uri not in commit.get("changed_files", []):
            continue
        for i in range(j - 1, -1, -1):
            sha = commits[i]["sha"]
            if baseline_by_sha.get(sha):
                if sha not in truth:
                    truth.append(sha)
                break
    return truth


def truth_for(repo: dict, artifact_uri: str) -> list[str]:
    """Scripted breaking commits when known (selftest), else the heuristic."""
    if "breaking_commits" in repo:
        return list(repo["breaking_commits"])
    return heuristic_truth(repo, artifact_uri)


def build_truth(results: dict) -> dict[str, list[str]]:
    return {
        f"{repo['name']}:{artifact['uri']}": truth_for(repo, artifact["uri"])
        for repo in results["repos"]
        for artifact in repo["artifacts"]
    }


def build_labeling_queue(results: dict, truth: dict[str, list[str]]) -> list[dict]:
    rows: list[dict] = []
    for repo in results["repos"]:
        commit_by_sha = {c["sha"]: c for c in repo["commits"]}
        texts = {
            artifact["uri"]: {c["id"]: c["text"] for c in artifact["claims"]}
            for artifact in repo["artifacts"]
        }
        for rec in repo["records"]:
            if not (rec["baseline_alarm"] or rec["dorian_alarm"]):
                continue
            commit = commit_by_sha[rec["commit"]]
            key = f"{repo['name']}:{rec['artifact']}"
            rows.append(
                {
                    "repo": repo["name"],
                    "artifact": rec["artifact"],
                    "commit": rec["commit"],
                    "subject": commit["subject"],
                    "changed_files": commit["changed_files"],
                    "baseline_alarm": rec["baseline_alarm"],
                    "dorian_alarm": rec["dorian_alarm"],
                    "broken_claims": rec["broken_claims"],
                    "broken_claim_texts": [
                        texts[rec["artifact"]].get(cid, "") for cid in rec["broken_claims"]
                    ],
                    "heuristic_true": rec["commit"] in truth.get(key, []),
                }
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.ground_truth", description=__doc__)
    ap.add_argument("--results", default="bench/results/results.json")
    ap.add_argument("--out", default="bench/results")
    args = ap.parse_args(argv)

    results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    truth = build_truth(results)
    (out / "gt.json").write_text(
        json.dumps({"truth": truth}, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    rows = build_labeling_queue(results, truth)
    (out / "labeling_queue.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(
        f"gt.json: {sum(len(v) for v in truth.values())} true commit(s); "
        f"labeling_queue.jsonl: {len(rows)} alarm row(s) -> {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
