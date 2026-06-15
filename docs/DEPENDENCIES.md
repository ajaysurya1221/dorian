# Dependencies

dorian's **core runtime dependency list is empty** — `pip install dorian-vwp`
pulls in nothing but the standard library. That is a deliberate product property
(portability, auditability, no supply-chain surface at check time), so this file
makes it visible and auditable rather than something you have to infer from
`pyproject.toml`.

Regenerate the summary at any time:

```bash
make dependency-report   # reads pyproject.toml, prints the tables below
```

## Core runtime — none

```toml
[project]
dependencies = []
```

Everything the checkers need at run time is stdlib: `re`, `multiprocessing` (the
C3 regex timeout worker), `subprocess` (C4/C5 shell), `sqlite3` (the derived
index and C5 reconcile), `csv`, `tomllib`, `json`, `hashlib`. No third-party
package is imported on the core path.

## Optional extras (opt-in, not installed by default)

| Extra | Package | Enables | License |
|---|---|---|---|
| `data` | `duckdb` | parquet-backed C5 data claims (`read_parquet`) | MIT |
| `extract` | `anthropic` | LLM claim *drafting* — frozen/experimental, never on the check path | (vendor) |

CSV and SQLite C5 claims need **no** extra; only `.parquet` pulls in `duckdb`.
The `extract` extra is for drafting claims a human then reviews; it is not used
by `verify`/`seal`/`revalidate` and adds no check-time dependency.

## Build + dev (not shipped to users)

| Group | Packages | Purpose |
|---|---|---|
| build-system | `hatchling` | wheel/sdist build backend |
| dev | `pytest>=8`, `pytest-cov>=5`, `ruff>=0.8`, `pyyaml>=6` | tests, coverage, lint, YAML for config tests |

## License

dorian itself is **Apache-2.0** (`LICENSE`, and `[project].license` in
`pyproject.toml`). The optional extras carry their own licenses (above); they are
only present if you opt into `[data]` / `[extract]`.

## Limitations of this report

- It reflects the **declared constraints** in `pyproject.toml`, not the fully
  resolved pins. For exact pinned versions, see `uv.lock`.
- There is no generated SBOM yet. Producing one (e.g. CycloneDX) on release is a
  backlog item ([ROADMAP_BACKLOG.md](ROADMAP_BACKLOG.md)); until then the
  zero-core-dependency core means an SBOM of a default install is essentially the
  stdlib plus dorian.

## Coverage visibility

Test coverage is generated, not asserted as a badge (no fabricated number):

```bash
make coverage   # pytest --cov=dorian --cov-report=term-missing --cov-report=html
```

The HTML report lands in `htmlcov/`. See [TESTING.md](TESTING.md).
