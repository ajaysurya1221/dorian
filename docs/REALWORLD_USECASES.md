# dorian real-world public-case reproductions

> Hermetic, offline reproductions of PUBLIC problem classes (sources cited, status as of
> 2026-06-14). Each public issue is the design template; the fixture is
> invented and public-safe. A result is scoped to its reproduction of a public problem
> class — **not** a blanket real-world result. The trigger-vs-truth ceiling stands: a
> checker must EXERCISE a fact for a BROKEN to mean semantic failure.

- candidates: 5 · reproduced (hermetic): 3
- solved: 2 · partial: 1 · not_solved: 2 · cannot_test: 0
- dorian `0.9.0` · run_id `1ffdef1671126a5c`

| case | source | status | reproduction | outcome |
| --- | --- | --- | --- | --- |
| api_rename_caught_typedrift_missed | [Effect-TS/effect-smol (Effect v4)](https://github.com/Effect-TS/effect-smol/issues/1378) | open | public_case_reproduction | **partial** |
| config_rename_doc_drift | [Proxyfan/Proxyfan](https://github.com/Proxyfan/Proxyfan/issues/978) | open | public_case_reproduction | **solved** |
| readme_path_already_fixed_external_file | [AndrejOrsula/pymoveit2](https://github.com/AndrejOrsula/pymoveit2/issues/110) | open | qualitative_public_case | **not_solved** |
| tls_insecure_skip_verify | [grafana/grafana](https://github.com/grafana/grafana/issues/110811) | open | public_case_reproduction | **solved** |
| zero_assertion_test_counts_as_pass | [rails/minitest, jest, phpunit (cross-ecosystem class)](https://github.com/rails/rails/issues/26546) | unresolved | qualitative_public_case | **not_solved** |

## Case detail

### api_rename_caught_typedrift_missed — partial

- **source**: Effect-TS/effect-smol (Effect v4) — https://github.com/Effect-TS/effect-smol/issues/1378
- **problem class**: major-version API churn — a rename (caught) PLUS a same-name return-type change (missed)
- **claim**: (a) the example uses exported `reverse`; (b) `find_first` is the safe accessor.
- **checker**: C3 symbol: existence checks on both symbols
- **expected**: one drift commit: rename reverse->flip (existence BROKEN) AND gut find_first's body keeping the name (existence still passes -> NOT broken)
- **actual**: BROKEN=['ex-reverse'] · still-VERIFIED=['find-first'] · re-checked=['ex-reverse', 'find-first']
- **why partial**: dorian catches the pure RENAME (the example's symbol no longer exists -> BROKEN) but a symbol that keeps its name while changing its return type/behavior re-checks and PASSES — the documented trigger-vs-truth ceiling, on a real migration class.
- **limitations**: catching the silent type change needs a checker that EXERCISES behavior (a C4 test or a type-level check), which the doc author did not bind; existence is not behavior. Also: the real project is TypeScript, so only C3 path/symbol/string checks transfer.
- hermetic: True · no private content: True

### config_rename_doc_drift — solved

- **source**: Proxyfan/Proxyfan — https://github.com/Proxyfan/Proxyfan/issues/978
- **problem class**: file/config rename — docs reference the legacy filename after the code renamed it
- **claim**: The config loader reads a file named `config.yaml`.
- **checker**: C3 string: the loader source literally references config.yaml
- **expected**: rename in the loader -> the documented filename string is gone -> BROKEN
- **actual**: BROKEN=['cfg-name'] · still-VERIFIED=[] · re-checked=['cfg-name']
- **why solved**: the documented fact IS a string the checker exercises against the source of truth (the loader), so a rename folds it BROKEN; a migration shim that intentionally keeps the legacy name is NOT in the checker's bound file, so it does not over-fire (precision).
- **limitations**: dorian proves the documented STRING is stale, not that a user workflow breaks; the claim must be scoped to the canonical source file, which a human/agent authors.
- hermetic: True · no private content: True

### readme_path_already_fixed_external_file — not_solved

- **source**: AndrejOrsula/pymoveit2 — https://github.com/AndrejOrsula/pymoveit2/issues/110
- **problem class**: README launch-file rename — but already merged-fixed, and the file is in a sibling package
- **claim**: (README command points at a launch file)
- **checker**: (C3 path) — but the path is outside the repo
- **expected**: n/a — not reproduced
- **why not_solved**: the doc half was already fixed upstream (README updated 2026-02); the still-open part is a runtime joint-config bug dorian cannot warrant, and the referenced launch file lives in an external package, so dorian has no local evidence file to watch (local-first boundary).
- **limitations**: cross-package paths and runtime behavior are outside dorian's in-repo deterministic checks.
- hermetic: False · no private content: True

### tls_insecure_skip_verify — solved

- **source**: grafana/grafana — https://github.com/grafana/grafana/issues/110811
- **problem class**: security config drift — a TLS verification flag flipped to an insecure value
- **claim**: The HTTP client keeps TLS verification ON (InsecureSkipVerify is False).
- **checker**: C3 regex: InsecureSkipVerify is anchored to False
- **expected**: flip InsecureSkipVerify to True -> the anchored regex fails -> BROKEN
- **actual**: BROKEN=['tls-verify'] · still-VERIFIED=[] · re-checked=['tls-verify']
- **why solved**: a security-relevant config value is a deterministic C3 regex fact (key AND value anchored); flipping it to the insecure value folds the claim BROKEN at the next commit.
- **limitations**: dorian proves the source sets InsecureSkipVerify = False, not that TLS is actually verified at runtime; bind both key and value or a bare flip passes.
- hermetic: True · no private content: True

### zero_assertion_test_counts_as_pass — not_solved

- **source**: rails/minitest, jest, phpunit (cross-ecosystem class) — https://github.com/rails/rails/issues/26546, https://github.com/jestjs/jest/issues/2209
- **problem class**: a test body with no executed assertions reports as a PASS — "tests cover X" silently false
- **claim**: "feature X is covered by a test"
- **checker**: C4 pytest: the test is collected and exits 0
- **expected**: n/a — dorian's C4 runs the test and sees a PASS; it cannot tell a gutted, assertion-free test from a real one
- **why not_solved**: this is the test-level gutted-body ceiling: a zero-assertion test exits 0, so dorian's C4 checker (which trusts the runner's verdict) reports VERIFIED. Proving the test actually exercises the behavior is exactly what the runner itself does not enforce.
- **limitations**: needs assertion-count / mutation-testing semantics dorian deliberately does not implement (no model, no behavior synthesis); deterministically reproducible but always a miss.
- hermetic: False · no private content: True

## Reproduce

```bash
dorian bench realworld-usecases
```

_public-case reproductions are not a blanket real-world result; each is scoped to its synthetic reproduction of a public problem class, and the trigger-vs-truth ceiling stands — a checker must EXERCISE a fact for a BROKEN to mean semantic failure._

