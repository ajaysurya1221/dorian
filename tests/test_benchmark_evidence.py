"""Benchmark-evidence hygiene (WP1/WP9): historical vs current, honestly labeled.

The repo's published numbers must not silently imply that older results describe the
current implementation. These pin: historical result docs carry a HISTORICAL banner; the
current-version results doc is version- and commit-stamped and carries a what-it-does-NOT-
prove block; the README labels the older numbers historical and points to the current doc;
and the V1-scope doc states the boundary. Wording tests, no network.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_historical_benchmark_docs_are_labeled_historical() -> None:
    # the binding-lifecycle doc is NOT byte-matched to its generator, so it carries an
    # explicit HISTORICAL banner pointing to the current-version doc.
    bl = _read("docs/BENCHMARK_BINDING_LIFECYCLE.md")
    assert "HISTORICAL" in bl, "binding-lifecycle doc must be labeled HISTORICAL"
    assert "BENCHMARK_CURRENT.md" in bl
    # the large-mutation doc IS byte-matched to its generator (test_large_mutation), so it
    # cannot carry a hand banner; its historical status is its version-stamped title plus
    # the current-results doc naming it as the historical source.
    v07 = _read("docs/BENCHMARK_v0.7.0.md")
    assert "(v0.7.0)" in v07, "the large-mutation doc title must carry its version stamp"
    cur = _read("docs/BENCHMARK_CURRENT.md")
    assert "BENCHMARK_v0.7.0.md" in cur and "historical" in cur.lower()


def test_current_benchmark_doc_is_version_and_commit_stamped() -> None:
    doc = _read("docs/BENCHMARK_CURRENT.md")
    assert "0.11.0" in doc  # dorian version stamp
    assert "measured commit" in doc.lower()
    assert "Python" in doc  # environment summary
    assert "reproduce" in doc.lower()
    # the mandatory non-overclaim block
    low = doc.lower()
    assert "not supported" in low or "do not" in low
    assert "synthetic" in low
    assert "binding proves" in low or "binding" in low  # trigger-vs-truth caveat present


def test_current_doc_does_not_claim_real_world_validation() -> None:
    doc = _read("docs/BENCHMARK_CURRENT.md").lower()
    # the doc may NEGATE these phrases, but must never assert them
    assert "works on real repos in general" not in doc.replace(
        '"works on real repos in general"', ""
    )


def test_readme_labels_benchmarks_historical_and_links_current() -> None:
    readme = _read("README.md")
    assert "historical" in readme.lower()
    assert "docs/BENCHMARK_CURRENT.md" in readme


def test_v1_scope_doc_states_the_boundary() -> None:
    doc = _read("docs/V1_SCOPE.md")
    low = doc.lower()
    assert "not universal semantic correctness" in low
    assert "not a sandbox" in low
    assert "gutted body" in low or "gutted-body" in low  # the ceiling is named
    assert "yaml" in low  # the config-binding boundary is stated
