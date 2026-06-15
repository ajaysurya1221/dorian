# Release checklist

The drift the v0.10 audit found (package version, pyproject, and badge
disagreeing; README advertising commands the parser lacked) is exactly what a
checklist prevents. Run every box before tagging. Most are enforced by a test —
the test name is given so "I checked" means "the suite is green", not "I
remember looking".

## 1. Version is one story

- [ ] `pyproject.toml [project].version` == `src/dorian/__init__.py __version__`
      — `tests/test_version_sync.py::test_pyproject_matches_package_dunder`
- [ ] `python -m dorian --version` prints that version
      — `tests/test_version_sync.py::test_cli_version_reports_the_package_version`
- [ ] README release badge is the dynamic shields endpoint, no hardcoded version
      — `tests/test_version_sync.py::test_readme_release_badge_is_dynamic_not_hardcoded`
- [ ] `uv.lock` is regenerated for the new version (`uv lock`)

## 2. Docs match the CLI

- [ ] Every `dorian <cmd>` in README code resolves to a real subparser / bench
      subcommand — `tests/test_cli_docs_sync.py`
- [ ] Top-level docs (`README.md`, `AGENTS.md`, `CLAUDE.md`) reflect any new flag
      or command added this cycle (per the global "docs current before PR" rule)
- [ ] `CHANGELOG` / release notes drafted (one line per user-visible change)

## 3. Tests and lint

- [ ] `uv run ruff check src tests bench`
- [ ] `uv run ruff format --check src tests bench`
- [ ] `uv run pytest` (full, including `slow`) green locally
- [ ] `uv run pytest -m slow` green explicitly (the packaging-wheel and
      C4/regex-subprocess tests live here — a local `-m 'not slow'` run skips them)
- [ ] CI green on the full Python matrix (3.11 / 3.12 / 3.13) **before** tagging

## 4. Security grep (no silent regressions)

- [ ] deny-exec still gates C4 + C5 shell — `tests/test_deny_exec_policy.py`
- [ ] C3 regex timeout still bounds catastrophic patterns — `tests/test_c3_regex_timeout.py`
- [ ] Action security posture intact — `tests/test_action_security_defaults.py`
- [ ] `rg -niE "safe for public fork|safe for public pr|production-ready|semantic proof|\bproven\b|validated broadly|catches ai lies|guarantee"
      README.md docs action` returns only forbidden-word *lists*, never live claims
      (see [VALIDATION_HONESTY.md](VALIDATION_HONESTY.md) for the full vocabulary)

## 5. Benchmark honesty

- [ ] No new benchmark result claims more than reproducibility on its named inputs
      (see [VALIDATION_HONESTY.md](VALIDATION_HONESTY.md))
- [ ] Synthetic results are labeled synthetic; trigger and truth metrics are separate
- [ ] No fabricated numbers; [REAL_CATCH_LOG.md](REAL_CATCH_LOG.md) is updated only
      with real events

## 6. Package builds

- [ ] `uv build` (or `python -m build`) produces an sdist + wheel
- [ ] `uvx twine check dist/*` passes (metadata sane) — or note it was skipped
- [ ] `tests/test_packaging.py` (slow) installs the wheel and runs a real verify

## 7. Dependency posture

- [ ] Core runtime dependencies still **empty** (`pyproject.toml [project].dependencies`)
- [ ] [DEPENDENCIES.md](DEPENDENCIES.md) reflects any extra/dev change

## 8. Tag and publish

- [ ] Tag `vX.Y.Z` on the release commit, pushed **after** CI is green
- [ ] GitHub release created (pre-release flag if appropriate)
- [ ] PyPI: only via the trusted-publishing workflow (`.github/workflows/publish.yml`),
      triggered manually on the tag — never a hardcoded token, never an arbitrary branch
- [ ] Prior tags untouched

## Pre-flight one-liner

```bash
uv run ruff check src tests bench \
  && uv run ruff format --check src tests bench \
  && uv run pytest \
  && python -m dorian --version
```
