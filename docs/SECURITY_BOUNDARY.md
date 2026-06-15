# Security boundary

The one thing to internalize: **a `.warrant` sidecar and a `claims.json` are
executable input** whenever they carry C4 (`pytest:`) or C5 (`shell:`) checkers.
This doc states exactly what dorian does and does not protect, in the project's
FACT / LIMITATION / SAFE DEFAULT / UNSAFE / EXAMPLE format.

## Which checkers execute code

| Checker | Form | Executes code? | What it does |
|---|---|---|---|
| C1 | span anchor | No | reads a sealed read-set entry in-process |
| C3 | `path` / `symbol` / `string` / `regex` | No | reads files in-process (regex match runs in a killed-on-timeout worker) |
| C5 typed | `rowcount` / `schema` / `nullrate` / `domain` / `freshness` / `snapshot` / `reconcile` | No | reads CSV/SQLite/parquet read-only |
| **C4** | `pytest:<nodeid>` | **Yes** | spawns `python -m pytest` |
| **C5 shell** | `shell:<command>` | **Yes** | spawns an arbitrary command |

The classification lives in one function, `dorian.policy.executable_kind`, and
the deny-exec gate and these docs both derive from it.

## FACT — what dorian does today

- Runs the checker programs found in the sidecar / claims file on the machine
  that invokes it, with the caller's privileges.
- Strips the environment of executed checkers to a small allowlist
  (`PATH`, `HOME`, `LANG`, `LC_ALL`) so secrets in other env vars do not leak in.
- Confines checker file references to the repo root (path-escape attempts ERROR).
- Bounds C3 `regex:` patterns to 500 chars, compile-guards them, and runs the
  match in a worker process killed at `timeout_s` so catastrophic backtracking
  cannot stall the run (ERROR `regex_timeout`).
- Provides `--deny-exec` / `--deny-shell` (and `DORIAN_DENY_EXEC` /
  `DORIAN_DENY_SHELL`) to refuse the executable families entirely.

## LIMITATION — what dorian does not prove or contain

- **Not a sandbox.** An allowed C4/C5 checker runs real code with your
  privileges; dorian does not jail the filesystem, network, or process.
- Scope-lint (`[tool.dorian.scopes]`) restricts which files a claim may *name*;
  it does not restrict what an executed checker may *read or write*.
- The env strip reduces, but does not eliminate, exposure: `PATH`-resolved tools
  and on-disk secrets are still reachable by an allowed checker.
- deny-exec stops the executable families from running; it does not make a
  with-exec run safe.

## SAFE DEFAULT — trusted/internal repositories

Use dorian where you already trust everyone who can write a `.warrant` or a
`claims.json`: your own repo, an internal repo, a team you trust. Review claims
before sealing exactly as you review code. This is the supported posture.

```bash
# trusted local loop
dorian verify note.md --claims claims.json
dorian revalidate --since HEAD
```

## UNSAFE / NOT YET — untrusted claims and public fork PRs

Do **not** run `verify` / `seal` / `revalidate` / `rebind` on claims from a
source you do not trust without `--deny-exec` (`rebind` re-runs every checker to
re-seal, so it executes code too). Do **not** market or wire up public-fork-PR CI
as safe: the trusted-base design ([docs/TRUSTED_BASE_ACTION_DESIGN.md](TRUSTED_BASE_ACTION_DESIGN.md))
that would make it safe is not implemented or tested yet. Do not use
`pull_request_target` with an untrusted-head checkout.

```bash
# untrusted context: remove the ability to execute code
dorian verify note.md --claims claims.json --deny-exec
DORIAN_DENY_EXEC=1 dorian revalidate --since origin/main
```

A blocked checker ERRORs, so a blocked load-bearing claim cannot seal and cannot
silently pass revalidation — deny-exec fails closed.

## What must be true before public-fork CI can be recommended

1. Checker programs are taken from the **trusted base ref**, never from untrusted
   head, unless explicitly allowlisted.
2. deny-exec (or stronger) is the **default** for fork PRs.
3. There are tests that simulate a fork/head sidecar trying to execute shell and
   prove the Action blocks it.
4. No `pull_request_target` footgun in the documented workflow.

Until all four hold, the honest statement is: **trusted/internal repositories,
or `--deny-exec` everywhere else.**
