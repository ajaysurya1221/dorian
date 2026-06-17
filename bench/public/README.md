# bench/public — public-repo micro-benchmark

Home of the public-repo micro-benchmark. The `dorian bench public-repos` harness is **implemented**
(`bench/public_repos.py`) and has been **executed**; the results doc is
[`../../docs/BENCHMARK_PUBLIC_REAL_REPOS.md`](../../docs/BENCHMARK_PUBLIC_REAL_REPOS.md).

The design is pre-registered in
[`../../docs/PUBLIC_BENCHMARK_PROTOCOL.md`](../../docs/PUBLIC_BENCHMARK_PROTOCOL.md); the shipped run
diverged from that pre-registration on two points, recorded in its
[§9 Amendment (shipped)](../../docs/PUBLIC_BENCHMARK_PROTOCOL.md#9-amendment-shipped). In brief:

- **Executed repos:** `humanize` (`2ddb5903cdc1`, MIT) and `python-dotenv` (`36004e0e34be`,
  BSD-3-Clause), each with 4 machine-derived claims (8 total). The candidate top-5 starter set is
  pinned in [`manifest.v1.yaml`](manifest.v1.yaml); `tomli`/`bandit`/`jaffle_shop_duckdb` remain
  `NO_CLAIMS` and `sigstore-python` is excluded (unconfirmed `NOASSERTION` license).
- The original two-repo pre-registration (`encode/httpx`, `pallets/click`) stays pinned in
  [`repos.public.json`](repos.public.json) as the frozen pre-registration inputs; those two were not
  executed.
- **Claims are machine-derived**, not hand-authored: `bench/public_claims.py` extracts each operand
  from source (stdlib `ast`/`tomllib`/`json`) and derives the ground-truth label by
  Chain-of-Verification — running the real C3 checker on the mutated copy and recording the observed
  verdict. `--extract` stays frozen and is not used. Because the label is the checker's own verdict,
  this is determinism / reproducibility on these frozen SHAs, not a measure of catch power.
- Trigger/selection metrics and truth/alarm metrics are reported separately; `ERRORED` is its own
  bucket and is never an alarm.
- Results carry a reproducibility manifest (repo URL + SHA, claim ids, exact rerun command, tool
  versions); each subject was run twice and the output compared byte-for-byte.
- Reproducibility evidence on the pinned set — not a real-world performance claim, and it does not
  transfer to other repositories.

The frozen clones used for local development may sit under `bench/real/` (gitignored: clones and
worktrees, never committed, never linted). Private or local clones are excluded from any published
public benchmark — see §2 of the protocol.
