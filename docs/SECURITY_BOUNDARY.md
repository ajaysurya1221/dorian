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
- Resolves a C4 test's import dependencies **statically** at seal/rebind time
  (stdlib `ast` over tracked `.py` files only): it parses source to widen the
  re-check watch set — it never imports application modules, executes setup code,
  mutates `sys.path`, inspects installed packages, or reaches the network, and an
  unresolvable/untracked/ambiguous import simply adds nothing (`src/dorian/test_deps.py`).
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
re-seal, so it executes code too). Do not use `pull_request_target` with an
untrusted-head checkout.

```bash
# untrusted context: remove the ability to execute code
dorian verify note.md --claims claims.json --deny-exec
DORIAN_DENY_EXEC=1 dorian revalidate --since origin/main
```

A blocked checker ERRORs, so a blocked load-bearing claim cannot seal and cannot
silently pass revalidation — deny-exec fails closed.

## Public-fork CI: `--checker-source base` (a trust root, not a sandbox)

`dorian revalidate --checker-source base` (Action input `checker_trust: base`)
resolves each claim's checker SPEC from the trusted **base ref**, then runs it
against the PR-head sources. A PR-added or PR-modified executable (C4/C5 `shell:`)
checker is therefore never executed; a rewritten checker cannot self-attest a
verdict (the base spec wins, and the change is surfaced); a missing or tampered
base sidecar **fails closed** (ERRORED, never executed). The
[trusted-base test matrix](TRUSTED_BASE_ACTION_DESIGN.md) proves each case with a
filesystem side effect that must not appear.

This is a **checker-source trust root, not a sandbox.** A base-approved `pytest:`
checker can still import and execute PR-head code, so the honest recommendation for
public forks is `checker_trust: base` **with `deny_exec: true`** (or stronger
external isolation), never "safe for arbitrary fork PRs". The four conditions below
now hold for the *trust-root* threat; sandboxing executed code remains out of scope.

1. ✅ Checker specs are taken from the **trusted base ref** (`--checker-source base`).
2. ✅ deny-exec is available and recommended for fork PRs (`deny_exec: true`).
3. ✅ Tests simulate a fork/head sidecar trying to execute shell/pytest and prove it
   is not run (`tests/test_trusted_base.py`).
4. ✅ No `pull_request_target` in the documented workflow.

The residual, stated plainly: even in base mode a base-approved code-executing
checker runs PR-head code, so **without deny-exec or external sandboxing this is
not safe for fully untrusted code.** For trusted/internal repos, `head` mode
remains correct and unchanged.
