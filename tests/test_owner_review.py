"""Owner spot-check workflow tests (bench/owner_review.py) on synthetic fixtures.

Fixture universe — 14 (key, commit) pairs over a public repo and a private one:

  pubrepo:docs/a.md          internal-x:docs/internal.md
  aa01 panel-true  B+D       bb01 panel-true  B+D   (private markers)
  aa02 panel-true  B only    bb02 benign      B only
  aa03 dorian FP   B+D       bb03 quiet (panel detail only)
  aa04-aa06 benign B only    bb04 quiet remainder
  aa07-aa10 quiet

Never reads bench/real/ — all inputs are written into tmp_path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # bench/ is a repo-root package, not installed
    sys.path.insert(0, str(REPO_ROOT))

from bench import metrics, owner_review  # noqa: E402

from dorian import cli  # noqa: E402

PUB = "pubrepo"
PRIV = "internal-x"
PUB_KEY = f"{PUB}:docs/a.md"
PRIV_KEY = f"{PRIV}:docs/internal.md"

PUB_COMMITS = [
    ("aa01", "pub: break api claim", ["src/api.py"] + [f"src/f{i}.py" for i in range(1, 10)]),
    ("aa02", "pub: missed breakage", ["src/missed.py"]),
    ("aa03", "pub: false alarm refactor", ["src/refactor.py"]),
    ("aa04", "pub: benign touch 1", ["src/c1.py"]),
    ("aa05", "pub: benign touch 2", ["src/c2.py"]),
    ("aa06", "pub: benign touch 3", ["src/c3.py"]),
    ("aa07", "pub: quiet docs tweak 1", ["README.md"]),
    ("aa08", "pub: quiet docs tweak 2", ["README.md"]),
    ("aa09", "pub: quiet docs tweak 3", ["README.md"]),
    ("aa10", "pub: remainder commit", ["README.md"]),
]
PRIV_COMMITS = [
    ("bb01", "SECRET-SUBJECT alpha", ["secret/dir/file.py"]),
    ("bb02", "SECRET-SUBJECT beta", ["secret/dir/file2.py"]),
    ("bb03", "SECRET-SUBJECT quiet", ["secret/dir/other.py"]),
    ("bb04", "SECRET-SUBJECT remainder", ["secret/dir/more.py"]),
]
# sha -> (baseline_alarm, dorian_alarm); pairs not listed are quiet (no queue row)
ALARMS = {
    "aa01": (True, True),
    "aa02": (True, False),
    "aa03": (True, True),
    "aa04": (True, False),
    "aa05": (True, False),
    "aa06": (True, False),
    "bb01": (True, True),
    "bb02": (True, False),
}
PANEL_TRUE_SHAS = {"aa01", "aa02", "bb01"}

PANEL_TRUE = {(PUB_KEY, "aa01"), (PUB_KEY, "aa02"), (PRIV_KEY, "bb01")}
DORIAN_ALARMED = {(PUB_KEY, "aa01"), (PUB_KEY, "aa03"), (PRIV_KEY, "bb01")}
MANDATORY = PANEL_TRUE | DORIAN_ALARMED
QUEUE_PAIRS = {(PUB_KEY if s.startswith("aa") else PRIV_KEY, s) for s in ALARMS}
UNIVERSE = {(PUB_KEY, s) for s, _, _ in PUB_COMMITS} | {(PRIV_KEY, s) for s, _, _ in PRIV_COMMITS}
NON_QUEUE = UNIVERSE - QUEUE_PAIRS

FORBIDDEN = [
    "dorian_alarm",
    "baseline_alarm",
    "votes_true",
    "votes_total",
    "rationale",
    "heuristic_true",
    "broken_claim",
    "PANEL-RATIONALE-LEAK",
]


def _write_inputs(tmp_path: Path) -> dict[str, Path]:
    repos = [(PUB, "docs/a.md", PUB_COMMITS), (PRIV, "docs/internal.md", PRIV_COMMITS)]
    claim_texts = {
        PUB: [
            {"id": "c1", "text": "PUBLIC-CLAIM the api returns 200"},
            {"id": "c2", "text": "PUBLIC-CLAIM timeout is 30"},
        ],
        PRIV: [{"id": "c1", "text": "SECRET-CLAIM-TEXT internal endpoint"}],
    }

    detail, queue_rows, batches, results_repos = [], [], [], []
    for name, artifact, commits in repos:
        key = f"{name}:{artifact}"
        records = []
        for sha, subject, files in commits:
            label = sha in PANEL_TRUE_SHAS
            baseline, dorian = ALARMS.get(sha, (False, False))
            detail.append(
                {
                    "key": key,
                    "commit": sha,
                    "votes_true": 3 if label else 0,
                    "votes_total": 3,
                    "label": label,
                    "claims": ["c1"] if label else [],
                    "rationales": ["PANEL-RATIONALE-LEAK"],
                }
            )
            if sha in ALARMS:
                queue_rows.append(
                    {
                        "repo": name,
                        "artifact": artifact,
                        "commit": sha,
                        "subject": subject,
                        "changed_files": files,
                        "baseline_alarm": baseline,
                        "dorian_alarm": dorian,
                        "broken_claims": ["c1"],
                        "broken_claim_texts": [claim_texts[name][0]["text"]],
                        "heuristic_true": label,
                    }
                )
            records.append(
                {
                    "artifact": artifact,
                    "commit": sha,
                    "baseline_alarm": baseline,
                    "dorian_alarm": dorian,
                    "broken_claims": [],
                    "relocated": [],
                    "errored": [],
                }
            )
        batches.append(
            {
                "key": key,
                "repo_name": name,
                "clone": str(tmp_path / "ws" / name),
                "t0": f"t0-{name}",
                "artifact": artifact,
                "claims": claim_texts[name],
                "commits": [{"sha": s, "subject": subj} for s, subj, _ in commits],
            }
        )
        results_repos.append(
            {
                "name": name,
                "t0": f"t0-{name}",
                "commits": [
                    {"sha": s, "subject": subj, "changed_files": f} for s, subj, f in commits
                ],
                "artifacts": [
                    {"uri": artifact, "backed_claim_ratio": 1.0, "claims": claim_texts[name]}
                ],
                "records": records,
            }
        )

    panel = {
        "pairs_judged": len(detail),
        "unanimous": len(detail),
        "split_2v1": 0,
        "labeled_true": len(PANEL_TRUE_SHAS),
        "incomplete_batches": {},
        "pairs_with_missing_votes": 0,
        "detail": detail,
    }
    paths = {
        "panel": tmp_path / "panel_summary.json",
        "queue": tmp_path / "labeling_queue.jsonl",
        "batches": tmp_path / "judge_batches.json",
        "results": tmp_path / "results.json",
    }
    paths["panel"].write_text(json.dumps(panel) + "\n")
    paths["queue"].write_text("".join(json.dumps(r) + "\n" for r in queue_rows))
    paths["batches"].write_text(json.dumps(batches) + "\n")
    paths["results"].write_text(
        json.dumps({"spec": "dorian-bench-results-v0", "repos": results_repos}) + "\n"
    )
    return paths


def _make(tmp_path: Path, paths: dict[str, Path], *extra: str, tag: str = "x") -> tuple[Path, Path]:
    md = tmp_path / f"run-{tag}" / "sheet.md"
    jsonl = tmp_path / f"run-{tag}" / "sheet.jsonl"
    rc = owner_review.main(
        [
            "make-owner-review",
            "--panel",
            str(paths["panel"]),
            "--queue",
            str(paths["queue"]),
            "--batches",
            str(paths["batches"]),
            "--results",
            str(paths["results"]),
            "--out",
            str(md),
            "--jsonl-out",
            str(jsonl),
            *extra,
        ]
    )
    assert rc == 0
    return md, jsonl


def _rows(jsonl: Path) -> list[dict]:
    return [json.loads(line) for line in jsonl.read_text().splitlines() if line.strip()]


def _pairs(rows: list[dict]) -> list[tuple[str, str]]:
    return [(f"{r['repo']}:{r['artifact']}", r["commit"]) for r in rows]


# --- 1. determinism ---------------------------------------------------------


def test_same_seed_is_byte_identical(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    md_a, jsonl_a = _make(tmp_path, paths, tag="a")
    md_b, jsonl_b = _make(tmp_path, paths, tag="b")
    assert md_a.read_bytes() == md_b.read_bytes()
    assert jsonl_a.read_bytes() == jsonl_b.read_bytes()


def test_different_seed_reorders_and_reassigns_ids(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    _, jsonl_a = _make(tmp_path, paths, tag="a")  # default ns: all 14 pairs selected
    _, jsonl_b = _make(tmp_path, paths, "--seed", "7", tag="b")
    rows_a, rows_b = _rows(jsonl_a), _rows(jsonl_b)
    assert set(_pairs(rows_a)) == set(_pairs(rows_b)) == UNIVERSE
    assert _pairs(rows_a) != _pairs(rows_b)  # shuffled order differs
    ids_a = {p: r["pair_id"] for p, r in zip(_pairs(rows_a), rows_a, strict=True)}
    ids_b = {p: r["pair_id"] for p, r in zip(_pairs(rows_b), rows_b, strict=True)}
    assert ids_a != ids_b  # P-### ids reassigned
    for rows in (rows_a, rows_b):
        assert [r["pair_id"] for r in rows] == [f"P-{i:03d}" for i in range(1, len(rows) + 1)]


# --- 2. composition ---------------------------------------------------------


def test_composition_mandatory_buckets_and_dedup(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    _, jsonl = _make(tmp_path, paths, "--n-baseline-fp", "2", "--n-quiet", "2", "--n-random", "1")
    pairs = _pairs(_rows(jsonl))
    assert len(pairs) == len(set(pairs))  # no duplicates
    assert set(pairs) >= MANDATORY  # every panel-true + every dorian-alarm pair
    assert len(pairs) == len(MANDATORY) + 2 + 2 + 1


def test_composition_clamps_to_availability(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    _, jsonl = _make(tmp_path, paths)  # defaults 28/18/12 >> availability
    rows = _rows(jsonl)
    assert set(_pairs(rows)) == UNIVERSE  # clamped: everything selected, nothing invented
    assert len(rows) == len(UNIVERSE)
    expected = {"pair_id", "repo", "artifact", "commit", "subject", "owner_label", "owner_note"}
    assert all(set(r.keys()) == expected for r in rows)
    assert all(r["owner_label"] == "" and r["owner_note"] == "" for r in rows)
    # quiet pairs get their subject from results.json commits
    by_pair = dict(zip(_pairs(rows), rows, strict=True))
    assert by_pair[(PUB_KEY, "aa07")]["subject"] == "pub: quiet docs tweak 1"


def test_composition_quiet_controls_only_from_non_queue_pairs(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    _, jsonl = _make(tmp_path, paths, "--n-baseline-fp", "0", "--n-quiet", "6", "--n-random", "0")
    pairs = set(_pairs(_rows(jsonl)))
    extras = pairs - MANDATORY
    assert extras == NON_QUEUE  # all 6 quiet controls, none from the queue
    assert len(pairs) == len(MANDATORY) + 6


# --- 3. blinding ------------------------------------------------------------


def test_blinding_no_forbidden_strings_or_panel_leakage(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    md, jsonl = _make(tmp_path, paths)
    for text in (md.read_text(), jsonl.read_text()):
        for needle in FORBIDDEN:
            assert needle not in text
    assert "panel" not in md.read_text().lower()  # no per-pair (or other) panel verdicts


# --- 4. redaction -----------------------------------------------------------


def test_redact_private_strips_private_content(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    md, jsonl = _make(tmp_path, paths, "--redact-private", "--private-prefixes", "internal")
    md_text, jsonl_text = md.read_text(), jsonl.read_text()
    for leak in ("SECRET-CLAIM-TEXT", "SECRET-SUBJECT", "secret/dir"):
        assert leak not in md_text
        assert leak not in jsonl_text
    # public repo content stays readable in the md
    assert "PUBLIC-CLAIM the api returns 200" in md_text
    assert "pub: break api claim" in md_text
    # private labels + local inspect command keep the real repo dir
    assert "private-x" in md_text
    assert "private-doc-1" in md_text
    assert f"bench/real/workspace/{PRIV} show bb01" in md_text
    # jsonl always carries real identity for the merge; subject is redacted
    priv_rows = [r for r in _rows(jsonl) if r["repo"] == PRIV]
    assert {r["commit"] for r in priv_rows} == {"bb01", "bb02", "bb03", "bb04"}
    assert all(r["artifact"] == "docs/internal.md" for r in priv_rows)
    assert all(r["subject"] == "[redacted]" for r in priv_rows)


def test_no_redaction_by_default(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    md, jsonl = _make(tmp_path, paths)
    md_text = md.read_text()
    assert "SECRET-CLAIM-TEXT" in md_text  # local default: private content visible
    assert "SECRET-SUBJECT" in md_text
    assert "... and 2 more" in md_text  # aa01 has 10 changed files, md caps at 8
    priv_rows = [r for r in _rows(jsonl) if r["repo"] == PRIV]
    assert all(r["subject"].startswith("SECRET-SUBJECT") for r in priv_rows)
    assert all(r["artifact"] == "docs/internal.md" for r in priv_rows)


# --- 5. merge ---------------------------------------------------------------


def _owner_file(tmp_path: Path, rows: list[dict], name: str = "owner.jsonl") -> Path:
    p = tmp_path / name
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def _owner_row(key: str, commit: str, label: str, pair_id: str = "P-000") -> dict:
    repo, artifact = key.split(":", 1)
    return {
        "pair_id": pair_id,
        "repo": repo,
        "artifact": artifact,
        "commit": commit,
        "subject": "s",
        "owner_label": label,
        "owner_note": "",
    }


def _merge(tmp_path: Path, paths: dict[str, Path], owner: Path) -> tuple[int, Path]:
    out = tmp_path / "gt_owner_checked.json"
    rc = owner_review.main(
        [
            "merge-owner-review",
            "--panel",
            str(paths["panel"]),
            "--owner",
            str(owner),
            "--out",
            str(out),
        ]
    )
    return rc, out


def test_merge_applies_each_label(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    owner = _owner_file(
        tmp_path,
        [
            _owner_row(PUB_KEY, "aa01", "true_stale"),  # panel-true confirmed: no override
            _owner_row(PUB_KEY, "aa02", "not_stale"),  # panel-true flipped off: override
            _owner_row(PUB_KEY, "aa03", "true_stale"),  # panel-false flipped on: override
            _owner_row(PUB_KEY, "aa04", "out_of_scope"),  # panel-false: excluded, NOT override
            _owner_row(PUB_KEY, "aa05", "unsure"),  # counted, no change
            _owner_row(PRIV_KEY, "bb01", "already_stale"),  # panel-true flipped off: override
            _owner_row(PUB_KEY, "aa06", ""),  # empty: skipped entirely
        ],
    )
    rc, out = _merge(tmp_path, paths, owner)
    assert rc == 0
    gt = json.loads(out.read_text())
    assert gt["truth"][PUB_KEY] == ["aa01", "aa03"]
    assert gt["truth"][PRIV_KEY] == []  # bb01 removed
    assert gt["excluded"] == [{"key": PUB_KEY, "commit": "aa04"}]
    assert gt["unsure"] == [{"key": PUB_KEY, "commit": "aa05"}]
    assert {(o["key"], o["commit"], o["panel"], o["owner"]) for o in gt["overrides"]} == {
        (PUB_KEY, "aa02", True, "not_stale"),
        (PUB_KEY, "aa03", False, "true_stale"),
        (PRIV_KEY, "bb01", True, "already_stale"),
    }
    # drop-in compatible with bench.metrics --gt (it only reads gt['truth'])
    results = json.loads(paths["results"].read_text())
    pairs = metrics.build_pairs(results, gt)
    assert len(pairs) == 14
    assert sum(1 for p in pairs if p["true"]) == 2  # aa01 + aa03


def test_merge_out_of_scope_on_panel_true_is_override(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    owner = _owner_file(tmp_path, [_owner_row(PRIV_KEY, "bb01", "out_of_scope")])
    rc, out = _merge(tmp_path, paths, owner)
    assert rc == 0
    gt = json.loads(out.read_text())
    assert gt["truth"][PRIV_KEY] == []
    assert gt["excluded"] == [{"key": PRIV_KEY, "commit": "bb01"}]
    assert gt["overrides"] == [
        {"key": PRIV_KEY, "commit": "bb01", "panel": True, "owner": "out_of_scope"}
    ]


def test_merge_unknown_label_exits_2_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _write_inputs(tmp_path)
    owner = _owner_file(tmp_path, [_owner_row(PUB_KEY, "aa01", "maybe_stale", pair_id="P-009")])
    rc, out = _merge(tmp_path, paths, owner)
    assert rc == 2
    assert not out.exists()
    err = capsys.readouterr().err
    assert "P-009" in err and "maybe_stale" in err


# --- 6. owner-metrics -------------------------------------------------------

KEY_A = "repoA:d.md"


def _metrics_results(tmp_path: Path, *, dorian_misses_c5: bool = False) -> Path:
    """repoA, 6 (artifact, commit) pairs; truth = {c1, c5}.

    baseline: tp=2 fp=3 (c2, c3, c6) fn=0; dorian: tp=2 fp=0 fn=0 -> recall 1.0,
    fp_reduction 3/1 = 3.0. With dorian_misses_c5: dorian tp=1 fn=1 -> recall 0.5.
    """
    alarms = {
        "c1": (True, True),
        "c2": (True, False),
        "c3": (True, False),
        "c4": (False, False),
        "c5": (True, not dorian_misses_c5),
        "c6": (True, False),
    }
    repo = {
        "name": "repoA",
        "t0": "t0",
        "commits": [
            {"sha": s, "subject": f"subject {s}", "changed_files": ["x.py"]} for s in alarms
        ],
        "artifacts": [{"uri": "d.md", "backed_claim_ratio": 1.0, "claims": []}],
        "records": [
            {
                "artifact": "d.md",
                "commit": s,
                "baseline_alarm": b,
                "dorian_alarm": d,
                "broken_claims": [],
                "relocated": [],
                "errored": [],
            }
            for s, (b, d) in alarms.items()
        ],
    }
    p = tmp_path / "results_m.json"
    p.write_text(json.dumps({"spec": "dorian-bench-results-v0", "repos": [repo]}) + "\n")
    return p


def _gt_file(tmp_path: Path, excluded: list[dict] | None = None) -> Path:
    gt = {
        "truth": {KEY_A: ["c1", "c5"]},
        "excluded": excluded or [],
        "overrides": [],
        "unsure": [],
    }
    p = tmp_path / "gt_m.json"
    p.write_text(json.dumps(gt) + "\n")
    return p


def _panel_file(tmp_path: Path, true_pairs: list[tuple[str, str]]) -> Path:
    detail = [
        {
            "key": k,
            "commit": c,
            "votes_true": 3,
            "votes_total": 3,
            "label": True,
            "claims": [],
            "rationales": [],
        }
        for k, c in true_pairs
    ]
    p = tmp_path / "panel_m.json"
    p.write_text(
        json.dumps(
            {
                "pairs_judged": len(detail),
                "unanimous": len(detail),
                "labeled_true": len(detail),
                "detail": detail,
            }
        )
        + "\n"
    )
    return p


def _run_owner_metrics(
    tmp_path: Path, results: Path, gt: Path, owner: Path, panel: Path
) -> tuple[int, dict]:
    out = tmp_path / "owner_metrics.json"
    rc = owner_review.main(
        [
            "owner-metrics",
            "--results",
            str(results),
            "--gt",
            str(gt),
            "--owner",
            str(owner),
            "--panel",
            str(panel),
            "--out",
            str(out),
            "--summary-out",  # keep the defaulted artifact out of bench/real/
            str(tmp_path / "owner_checked_summary.json"),
        ]
    )
    return rc, json.loads(out.read_text())


def test_owner_metrics_pass(tmp_path: Path) -> None:
    results = _metrics_results(tmp_path)
    gt = _gt_file(tmp_path)
    panel = _panel_file(tmp_path, [(KEY_A, "c1"), (KEY_A, "c5")])
    owner = _owner_file(
        tmp_path,
        [_owner_row(KEY_A, "c1", "true_stale"), _owner_row(KEY_A, "c5", "true_stale")],
    )
    rc, m = _run_owner_metrics(tmp_path, results, gt, owner, panel)
    assert rc == 0
    assert m["pairs"] == 6 and m["excluded"] == 0
    d, b = m["systems"]["dorian"], m["systems"]["baseline"]
    assert (d["tp"], d["fp"], d["fn"]) == (2, 0, 0)
    assert d["recall"] == 1.0 and d["precision"] == 1.0
    assert (b["tp"], b["fp"], b["fn"]) == (2, 3, 0)
    assert m["fp_reduction"] == pytest.approx(3.0)
    assert m["owner_review"]["reviewed"] == 2
    assert m["owner_review"]["overrides"] == 0
    assert m["owner_review"]["same_direction_pattern"] is False
    assert m["recommendation"] == "PASS"
    assert m["reasons"] == []


def test_owner_metrics_excluded_pairs_shrink_count(tmp_path: Path) -> None:
    results = _metrics_results(tmp_path)
    gt = _gt_file(tmp_path, excluded=[{"key": KEY_A, "commit": "c4"}])
    panel = _panel_file(tmp_path, [(KEY_A, "c1"), (KEY_A, "c5")])
    owner = _owner_file(tmp_path, [_owner_row(KEY_A, "c1", "true_stale")])
    rc, m = _run_owner_metrics(tmp_path, results, gt, owner, panel)
    assert rc == 0
    assert m["pairs"] == 5
    assert m["excluded"] == 1


def test_owner_metrics_expand_on_three_material_disagreements(tmp_path: Path) -> None:
    results = _metrics_results(tmp_path)
    gt = _gt_file(tmp_path)
    # three panel-true pairs in three different repos, all flipped off by the owner:
    # 3 overrides (> 2) but no same-direction pattern inside a single repo window
    true_pairs = [(KEY_A, "c1"), ("repoB:x.md", "z1"), ("repoC:y.md", "z2")]
    panel = _panel_file(tmp_path, true_pairs)
    owner = _owner_file(tmp_path, [_owner_row(k, c, "not_stale") for k, c in true_pairs])
    rc, m = _run_owner_metrics(tmp_path, results, gt, owner, panel)
    assert rc == 0
    assert m["owner_review"]["overrides"] == 3
    assert m["owner_review"]["same_direction_pattern"] is False
    assert m["recommendation"] == "EXPAND_TO_FULL_201"
    assert any("disagreement" in r for r in m["reasons"])


def test_owner_metrics_expand_on_same_direction_pattern(tmp_path: Path) -> None:
    results = _metrics_results(tmp_path)
    gt = _gt_file(tmp_path)
    true_pairs = [("repoB:x.md", "z1"), ("repoB:x.md", "z2")]
    panel = _panel_file(tmp_path, true_pairs)
    owner = _owner_file(tmp_path, [_owner_row(k, c, "not_stale") for k, c in true_pairs])
    rc, m = _run_owner_metrics(tmp_path, results, gt, owner, panel)
    assert rc == 0
    assert m["owner_review"]["overrides"] == 2  # not > 2 ...
    assert m["owner_review"]["same_direction_pattern"] is True  # ... but same repo+direction
    assert m["recommendation"] == "EXPAND_TO_FULL_201"


def test_owner_metrics_hold_on_low_recall(tmp_path: Path) -> None:
    results = _metrics_results(tmp_path, dorian_misses_c5=True)  # recall 0.5 < 0.85
    gt = _gt_file(tmp_path)
    panel = _panel_file(tmp_path, [(KEY_A, "c1")])
    owner = _owner_file(tmp_path, [_owner_row(KEY_A, "c1", "true_stale")])
    rc, m = _run_owner_metrics(tmp_path, results, gt, owner, panel)
    assert rc == 0  # advisory: always exit 0
    assert m["systems"]["dorian"]["recall"] == pytest.approx(0.5)
    assert m["recommendation"] == "HOLD_PUBLIC_CLAIMS"
    assert any("recall" in r for r in m["reasons"])


def test_owner_metrics_hold_on_unsure_ratio(tmp_path: Path) -> None:
    results = _metrics_results(tmp_path)
    gt = _gt_file(tmp_path)
    true_pairs = [(KEY_A, f"c{i}") for i in (1, 5)] + [("repoB:x.md", f"z{i}") for i in (1, 2, 3)]
    panel = _panel_file(tmp_path, true_pairs)
    rows = [_owner_row(k, c, "true_stale") for k, c in true_pairs[:4]]
    rows.append(_owner_row(*true_pairs[4], "unsure"))  # 1 unsure / 5 reviewed = 0.2 > 0.10
    owner = _owner_file(tmp_path, rows)
    rc, m = _run_owner_metrics(tmp_path, results, gt, owner, panel)
    assert rc == 0
    assert m["owner_review"]["reviewed"] == 5 and m["owner_review"]["unsure"] == 1
    assert m["recommendation"] == "HOLD_PUBLIC_CLAIMS"
    assert "labels may require private context not visible in the packet" in m["reasons"]


def test_owner_metrics_hold_wins_over_expand(tmp_path: Path) -> None:
    results = _metrics_results(tmp_path, dorian_misses_c5=True)  # HOLD: recall below gate
    gt = _gt_file(tmp_path)
    true_pairs = [(KEY_A, "c1"), ("repoB:x.md", "z1"), ("repoC:y.md", "z2")]
    panel = _panel_file(tmp_path, true_pairs)
    owner = _owner_file(tmp_path, [_owner_row(k, c, "not_stale") for k, c in true_pairs])
    rc, m = _run_owner_metrics(tmp_path, results, gt, owner, panel)
    assert rc == 0
    assert m["owner_review"]["overrides"] == 3  # EXPAND also triggers ...
    assert m["recommendation"] == "HOLD_PUBLIC_CLAIMS"  # ... but HOLD takes precedence
    assert any("recall" in r for r in m["reasons"])
    assert any("disagreement" in r for r in m["reasons"])  # all triggered reasons listed


# --- 6b. owner-checked summary artifact ---------------------------------------


def _pass_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    results = _metrics_results(tmp_path)
    gt = _gt_file(tmp_path)
    panel = _panel_file(tmp_path, [(KEY_A, "c1"), (KEY_A, "c5")])
    owner = _owner_file(
        tmp_path,
        [_owner_row(KEY_A, "c1", "true_stale"), _owner_row(KEY_A, "c5", "true_stale")],
    )
    return results, gt, owner, panel


def test_summary_artifact_fields_and_values_match_owner_metrics(tmp_path: Path) -> None:
    rc, m = _run_owner_metrics(tmp_path, *_pass_inputs(tmp_path))
    assert rc == 0
    s = json.loads((tmp_path / "owner_checked_summary.json").read_text())
    assert s["schema"] == "dorian-owner-checked-summary-v1"
    assert set(s) == {"schema", "spot_check", "panel", "metrics"}

    spot = s["spot_check"]
    assert set(spot) == {
        "reviewed_pairs",
        "overrides",
        "unsure",
        "out_of_scope",
        "recommendation",
        "reasons",
    }
    assert spot["reviewed_pairs"] == m["owner_review"]["reviewed"] == 2
    assert spot["overrides"] == m["owner_review"]["overrides"] == 0
    assert spot["unsure"] == m["owner_review"]["unsure"] == 0
    assert spot["out_of_scope"] == m["owner_review"]["out_of_scope"] == 0
    assert spot["recommendation"] == m["recommendation"] == "PASS"
    assert spot["reasons"] == m["reasons"] == []

    assert s["panel"] == {"pairs_judged": 2, "unanimous": 2, "labeled_true": 2}

    metrics_block = s["metrics"]
    assert set(metrics_block) == {
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
    }
    assert metrics_block["pairs"] == m["pairs"]
    assert metrics_block["excluded"] == m["excluded"]
    assert metrics_block["fp_reduction"] == m["fp_reduction"]
    assert metrics_block["fp_reduction_ci"] == m["fp_reduction_ci"]
    for system in ("baseline", "dorian"):
        assert metrics_block[f"{system}_precision"] == m["systems"][system]["precision"]
        assert metrics_block[f"{system}_precision_ci"] == m["systems"][system]["precision_ci"]
    assert metrics_block["dorian_recall"] == m["systems"]["dorian"]["recall"]
    assert metrics_block["dorian_recall_ci"] == m["systems"]["dorian"]["recall_ci"]


def test_summary_artifact_carries_hold_recommendation_and_reasons(tmp_path: Path) -> None:
    results = _metrics_results(tmp_path, dorian_misses_c5=True)  # recall 0.5 < gate
    gt = _gt_file(tmp_path)
    panel = _panel_file(tmp_path, [(KEY_A, "c1")])
    owner = _owner_file(tmp_path, [_owner_row(KEY_A, "c1", "true_stale")])
    rc, m = _run_owner_metrics(tmp_path, results, gt, owner, panel)
    assert rc == 0
    s = json.loads((tmp_path / "owner_checked_summary.json").read_text())
    assert s["spot_check"]["recommendation"] == "HOLD_PUBLIC_CLAIMS"
    assert s["spot_check"]["reasons"] == m["reasons"]
    assert any("recall" in r for r in s["spot_check"]["reasons"])


def test_summary_artifact_is_deterministic(tmp_path: Path) -> None:
    inputs = _pass_inputs(tmp_path)
    summary = tmp_path / "owner_checked_summary.json"
    rc, _ = _run_owner_metrics(tmp_path, *inputs)
    assert rc == 0
    first = summary.read_bytes()
    assert first.endswith(b"\n")
    rc, _ = _run_owner_metrics(tmp_path, *inputs)
    assert rc == 0
    assert summary.read_bytes() == first


def test_summary_artifact_does_not_change_owner_metrics_or_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, m = _run_owner_metrics(tmp_path, *_pass_inputs(tmp_path))
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("RECOMMENDATION: PASS")
    assert "summary" not in out  # stdout stays exactly the pre-existing line(s)
    assert set(m) == {
        "pairs",
        "excluded",
        "systems",
        "fp_reduction",
        "fp_reduction_ci",
        "owner_review",
        "recommendation",
        "reasons",
    }


# --- error handling ---------------------------------------------------------


def test_missing_input_file_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    paths = _write_inputs(tmp_path)
    rc = owner_review.main(
        [
            "make-owner-review",
            "--panel",
            str(tmp_path / "nope.json"),
            "--queue",
            str(paths["queue"]),
            "--batches",
            str(paths["batches"]),
            "--results",
            str(paths["results"]),
            "--out",
            str(tmp_path / "o.md"),
            "--jsonl-out",
            str(tmp_path / "o.jsonl"),
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "nope.json" in err
    assert len(err.strip().splitlines()) == 1  # one-line error, no traceback
    rc = owner_review.main(
        [
            "merge-owner-review",
            "--panel",
            str(paths["panel"]),
            "--owner",
            str(tmp_path / "missing.jsonl"),
            "--out",
            str(tmp_path / "gt.json"),
        ]
    )
    assert rc == 2


# --- 7. local-only policy ---------------------------------------------------


def test_local_only_policy(tmp_path: Path) -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text().splitlines()
    assert "bench/real/" in gitignore
    paths = _write_inputs(tmp_path)
    md, _ = _make(tmp_path, paths)
    header = md.read_text().split("### ")[0]
    assert "LOCAL-ONLY" in header
    assert "gitignored" in header


# --- 8. CLI wiring ----------------------------------------------------------


def test_cli_bench_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)
    paths = _write_inputs(tmp_path)
    md = tmp_path / "cli.md"
    jsonl = tmp_path / "cli.jsonl"
    rc = cli.main(
        [
            "bench",
            "make-owner-review",
            "--panel",
            str(paths["panel"]),
            "--queue",
            str(paths["queue"]),
            "--batches",
            str(paths["batches"]),
            "--results",
            str(paths["results"]),
            "--out",
            str(md),
            "--jsonl-out",
            str(jsonl),
        ]
    )
    assert rc == 0
    assert md.exists() and jsonl.exists()


def test_cli_bench_unknown_subcommand_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)
    with pytest.raises(SystemExit) as exc:
        cli.main(["bench", "no-such-subcommand"])
    assert exc.value.code == 2
