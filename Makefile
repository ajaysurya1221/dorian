.PHONY: install lint test bench demo

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

demo:
	@echo "the example repo is on the roadmap; see the Roadmap section in README.md"
