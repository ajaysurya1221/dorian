# Contributing to dorian

Small, focused pull requests with tests are welcome. This page covers the development setup, the
checks a pull request must pass, and the rules the codebase keeps.

## Set up

You need Python 3.11+, Git, and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ajaysurya1221/dorian.git
cd dorian
make install    # uv sync: the package plus the dev dependency group
```

## Checks

Run both before you open a pull request; CI runs the same suite on Python 3.11, 3.12, and 3.13.

```bash
make lint       # ruff check and ruff format --check over src, tests, and bench
make test       # the full pytest suite, slow tests included
```

While iterating, `make test-fast` skips the slow tests (benchmark runs, the wheel build, and real
pytest subprocesses), and `make fmt` applies the linter fixes and the formatter.

**The README example is a test.** `tests/test_readme_example.py` runs the README's "Try it" recipe as
a black box and checks that the README still shows those commands. If you change the recipe, change
the test in the same pull request and run it:

```bash
uv run pytest tests/test_readme_example.py
```

Other documentation guard tests pin public wording (for example `tests/test_docs_polish.py` and
`tests/test_benchmark_evidence.py`). If you change pinned text on purpose, update its guard in the
same pull request and say why. What results and docs may claim is set by
[`docs/VALIDATION_HONESTY.md`](docs/VALIDATION_HONESTY.md).

## Rules

- **Zero runtime dependencies.** `[project].dependencies` in `pyproject.toml` stays empty and the
  core imports only the standard library. Optional features belong in an extra (`data`, `extract`);
  development tools belong in the `dev` dependency group, locked in `uv.lock`.
  `make dependency-report` prints the current posture.
- **No model on the verification path.** `tests/test_firewall_import_closure.py` fails if a model SDK
  or network client is imported at module level anywhere in the verdict path's import graph.
- **Benchmark contributions carry aggregate numbers only.**
- **Conventional Commits.** Write commit subjects as `type: summary`, using the types already in the
  history: `feat`, `fix`, `docs`, `test`, `chore`, `ci`, `release`. Explain the why in the body.

## Security

Do not report vulnerabilities in public issues. Follow [SECURITY.md](SECURITY.md): open a
[GitHub security advisory](https://github.com/ajaysurya1221/dorian/security/advisories/new), or a
regular issue without exploit details asking for a private channel.
