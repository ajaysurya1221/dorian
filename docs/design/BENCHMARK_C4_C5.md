# Design note — broadening the public benchmark to executed C4 + C5 cases

The shipped public benchmark (`dorian bench public-repos`, subjects `humanize` and
`python-dotenv`) executes **structural C3** claims only and is **byte-deterministic across two
runs** on frozen SHAs — that determinism is the property it exists to demonstrate
([../BENCHMARK_PUBLIC_REAL_REPOS.md](../BENCHMARK_PUBLIC_REAL_REPOS.md)). The plan asks to add
one executed **C4 (`pytest:`)** and one executed **C5 (typed data)** case so the corpus is not
structural-only.

## Why this is deferred (not just unbuilt)

The two checker families differ sharply in how safely they fit a *portable, deterministic*
benchmark:

- **C5 typed data** (`rowcount:`/`schema:`/`reconcile:` over a committed `.csv`/`.db`) is an
  in-process, read-only check — **deterministic and portable**. The only friction is that the
  current public subjects are code libraries with no committed data fixture, so a C5 case needs
  either a new frozen data-bearing subject or a synthetic-but-labeled data fixture (which is what
  the existing controlled-mutation benchmark already covers).
- **C4 `pytest:`** spawns a real `pytest` subprocess against a cloned repo. Its verdict depends
  on the **runner environment** (installed deps, Python version, plugin set). Folding that into a
  benchmark advertised as *byte-deterministic on frozen SHAs* would make the headline determinism
  claim environment-dependent — i.e. it could **weaken the exact honesty property** the benchmark
  is for. A flaky benchmark row is worse than no row.

So adding C4 here is intentionally deferred until it can be done **without** compromising
determinism, and C5 is deferred behind picking a stable data-bearing public subject.

## Intended approach when built

1. **C5 row:** add a frozen public (or vendored, clearly-labeled) data fixture; author 1–2
   typed-data claims; extend the `bench/public` manifest + `public_claims.py` machine-derived
   labelling to cover the C5 verdict; assert byte-determinism ×2, same as today.
2. **C4 row:** pin the subject's full dependency closure to hashes and run inside the benchmark's
   own locked environment so the pytest verdict is reproducible; record the exact toolchain in the
   report; keep the overclaim guard. If reproducibility across machines cannot be guaranteed, keep
   C4 out of the *public* benchmark and demonstrate it only in the controlled-mutation suite
   (which already executes C4 deterministically against synthetic fixtures).

Both extensions preserve the existing honesty framing: reproducibility/determinism on frozen
SHAs, never broad validation; trigger and truth layers reported separately.
