# bench/public — public-repo micro-benchmark (scaffold)

Scaffold for the public-repo micro-benchmark. **No harness and no results live here yet** — this is
the home a future `dorian bench public-repos` subcommand will occupy.

The design is pre-registered in
[`../../docs/PUBLIC_BENCHMARK_PROTOCOL.md`](../../docs/PUBLIC_BENCHMARK_PROTOCOL.md). In brief:

- Two genuinely public repos at frozen SHAs (`encode/httpx`, `pallets/click`).
- The committed public manifest is [`repos.public.json`](repos.public.json), which is evidence
  scaffolding only.
- Manual claims only (no `--extract`).
- Trigger/selection metrics and truth/alarm metrics reported separately.
- Published results must add a reproducibility manifest (repo URL + SHA, artifact, claim ids, exact
  rerun command, tool versions) so results reproduce byte-for-byte.
- Reproducibility evidence on the pinned set — not a real-world performance claim.

The frozen clones used for local development may sit under `bench/real/` (gitignored: clones and
worktrees, never committed, never linted). Private or local clones are excluded from any published
public benchmark — see §2 of the protocol.

When the harness lands, it goes here and is wired into `_BENCH_DISPATCH` in
`src/dorian/commands.py`; results are published in a separate `docs/BENCHMARK_PUBLIC_REPOS.md` that
cites the protocol. No benchmark results are published yet.
