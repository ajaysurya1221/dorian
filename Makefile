.PHONY: install lint fmt test test-fast coverage dependency-report bench bench-mutation bench-large-mutation demo

install:
	uv sync

lint:
	uv run ruff check src tests bench
	uv run ruff format --check src tests bench

fmt:
	uv run ruff check --fix src tests bench
	uv run ruff format src tests bench

test:
	uv run pytest

# fast iteration gate: skips benchmark runs, wheel build, and pytest-subprocess checks
test-fast:
	uv run pytest -m "not slow"

coverage:
	uv run pytest --cov=dorian --cov-report=term-missing --cov-report=html

# auditable dependency posture: reads pyproject.toml, no third-party tooling.
# The point it makes visible: the core runtime dependency list is empty.
dependency-report:
	@uv run python -c "import tomllib,pathlib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text()); p=d['project']; \
print('package :', p['name'], p['version']); \
print('license :', p['license']['text']); \
print('python  :', p['requires-python']); \
print('core runtime deps :', p['dependencies'] or '(none — stdlib only)'); \
[print(f'extra [{k}] :', v) for k,v in d.get('project',{}).get('optional-dependencies',{}).items()]; \
print('dev :', d.get('dependency-groups',{}).get('dev'))"

bench:
	uv run python -m bench.replay --config bench/repos.json
	uv run python -m bench.ground_truth --results bench/results/results.json --out bench/results
	uv run python -m bench.metrics --results bench/results/results.json --gt bench/results/gt.json --out bench/results

bench-mutation:
	uv run python -m bench.controlled_mutation --md-out bench/results/BENCHMARK_v0.6.0.md

bench-large-mutation:
	uv run python -m bench.large_mutation --md-out docs/BENCHMARK_v0.7.0.md

demo:
	@echo "the example repo is on the roadmap; see the Roadmap section in README.md"
