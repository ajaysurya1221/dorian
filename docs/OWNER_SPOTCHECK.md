# Owner spot-check workflow (v0.0 real-history benchmark)

Benchmark ground truth comes from a blind 3-judge model panel
(`bench/real/results/panel_summary.json`). This workflow is the ~2h human
audit of those labels: a risk-focused sample, a blinded review sheet, a label
merge, and an H2 recompute that ends in a PASS / EXPAND / HOLD recommendation.

All three commands live in `bench/owner_review.py` and run from the repo root,
either directly or through the CLI alias:

```bash
python -m bench.owner_review <subcommand> ...
dorian bench <subcommand> ...        # same thing, from a dorian checkout
```

## Local-only policy

`bench/real/` is gitignored and excluded from lint: it holds private local
benchmark data (including private repository content). Every file this workflow reads
and writes lives under `bench/real/results/`. **Never commit or share review
outputs** — the sheet and jsonl can embed private commit subjects, file paths,
and claim texts. Use `--redact-private` if a copy of the sheet must leave your
machine; the jsonl always keeps real identifiers and stays local regardless.

## The 3 commands

### 1. `make-owner-review` — build the blinded packet

```bash
python -m bench.owner_review make-owner-review --redact-private
```

Draws a risk-focused sample from the panel-detail universe (defaults shown):

- all panel-true pairs, all dorian-alarm pairs, and all known dorian misses
  (panel-true without a dorian alarm);
- `--n-baseline-fp 28` baseline-only alarms the panel called benign;
- `--n-quiet 18` quiet controls (pairs that never alarmed);
- `--n-random 12` random remainder.

Sample sizes clamp to availability; sampling and the final shuffle are
deterministic for a given `--seed` (default 42). Outputs:

- `bench/real/results/owner_spotcheck.md` — the review sheet. It is
  **blinded**: pair order is shuffled and no panel verdict, vote count, judge
  text, or alarm flag appears anywhere in it.
- `bench/real/results/owner_spotcheck.jsonl` — one row per pair with empty
  `owner_label` / `owner_note` fields to fill in.

With `--redact-private` (repo matches a `--private-prefixes` entry; pass your
own private repo-name prefixes), the sheet shows redacted repo/artifact/subject/claims/paths;
the per-pair `inspect:` command keeps the real clone path and sha because the
review itself happens locally:

```bash
git -C bench/real/workspace/<repo> show <sha>
```

### 2. Review, then `merge-owner-review`

For each pair, inspect the commit and set `owner_label` in the jsonl.

Label semantics:

| label | meaning |
| --- | --- |
| `true_stale` | this commit made >=1 sealed claim false |
| `not_stale` | no sealed claim was falsified by this commit |
| `unsure` | cannot decide from available context |
| `already_stale` | the claim was already false before this commit |
| `out_of_scope` | pair should not be in the benchmark (binding error, vendored file, etc.) — excluded from metrics |

Leave `owner_label` empty to skip a pair. Then:

```bash
python -m bench.owner_review merge-owner-review
```

Starts from the panel-true pairs and applies every non-empty owner label:
`true_stale` puts the pair in the truth, `not_stale`/`already_stale` removes
it, `out_of_scope` removes it *and* records it for exclusion, `unsure` changes
nothing (it is counted). An unknown label aborts with exit 2 and writes
nothing. Output `bench/real/results/gt_owner_checked.json` carries `truth`
(drop-in compatible with `python -m bench.metrics --gt`), `excluded`,
`overrides` (owner labels that flipped a pair's truth value vs the panel), and
`unsure`.

### 3. `owner-metrics` — recompute H2 + recommendation

```bash
python -m bench.owner_review owner-metrics
```

Rebuilds the (artifact, commit) pairs from `results.json` against the
owner-checked truth, drops the `excluded` pairs, and reuses `bench.metrics`
(precision/recall, FP reduction, bootstrap CIs, gate thresholds). Writes
`bench/real/results/owner_metrics.json` and prints the recommendation.

Decision rules (precedence HOLD > EXPAND > PASS; all triggered reasons are
listed):

- **HOLD_PUBLIC_CLAIMS** — dorian recall below the recall gate, or FP
  reduction below its gate, or more than 10% of reviewed pairs labeled
  `unsure` (labels may require private context not visible in the packet).
- **EXPAND_TO_FULL_201** — more than 2 material disagreements with the panel
  (overrides), or >=2 same-direction overrides within one repo window.
- **PASS** — otherwise.

The command always exits 0: the recommendation is advisory, not a gate.

## Publishing results

`owner-metrics` also writes the canonical owner-checked summary
(`--summary-out`, default `bench/real/results/owner_checked_summary.json`):
spot-check counts plus recommendation/reasons, the panel counters, and the
headline metrics with CIs — numbers and enumerated strings only.

To produce something shareable from it:

```bash
python -m bench.public_summary --allow-repo <name> ...
```

This reads the owner-checked summary plus `results.json` (aggregate
composition counts ONLY) and writes `bench/real/results/public_summary.md`
and `.json` (`dorian-public-summary-v1`). **Allow-list rule:** only repo
names passed via `--allow-repo` (repeatable; default: none) appear verbatim;
every other repo shows up as "private repository A"/"B"/... in sorted-name
order. The outputs carry only numeric/boolean fields, the enumerated
recommendation/reasons strings, allow-listed repo names, and fixed template
strings — never artifact paths, claim texts, commit shas/subjects,
changed-file lists, or rationales. When the recommendation is
HOLD_PUBLIC_CLAIMS the markdown still generates but leads with a NOT CLEARED
FOR PUBLIC USE banner, and the json carries `"cleared": false` (`true` only
on PASS; EXPAND_TO_FULL_201 is also `false`).
