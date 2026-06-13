.PHONY: install lint test bench bench-mutation bench-large-mutation demo

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
