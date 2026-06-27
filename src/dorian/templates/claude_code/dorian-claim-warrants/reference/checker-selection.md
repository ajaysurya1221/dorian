# Checker selection — match the checker to the claim

Two axes, never collapsed (see Dorian's `docs/VALIDATION_HONESTY.md`):

- **Trigger / binding** — *when* a claim is re-checked (which watched files fire it).
- **Truth / strength** — *whether* the checker can actually **falsify** the claim.

A green seal says every backed claim held *at seal time*. It does **not** say the
checker is strong enough to catch a future drift. Pick the strongest checker the
claim's kind needs. `--strength-gate=fail` refuses to seal a load-bearing claim
whose checker is too weak to falsify its kind.

## Claim → checker map

| The summary says… | `kind` | checker `program` | strength |
|---|---|---|---|
| package/config value (`requires-python`, a default, a version) | `quantity` / `fact` | `config-value:pyproject.toml:project.requires-python:">=3.11"` | structural |
| a Python signature/defaults | `reference` | `py-signature:m.py::f::a, b=1 -> int` | structural |
| a Python constant's value | `quantity` | `py-const:m.py::TIMEOUT::30` | structural |
| "symbol `X` exists / is referenced" | `reference` | `symbol:m.py::X` | existence |
| "path `p` exists" | `reference` | `path:pkg/p.py` | existence |
| a specific string/route is present | `reference` | `string:r.py::/admin` or anchored `regex:` | raw_text |
| "value is N" anchored in code | `quantity` | `regex:m.py::TIMEOUT\s*=\s*30\b` (anchor BOTH key+value) | raw_text |
| a real behavior holds (safe known test) | `behavior` | `pytest:tests/test_x.py::T` — **this RUNS the test** | behavioral |
| data shape / rowcount / freshness | `quantity` / `fact` | typed `C5` (`schema:`/`rowcount:`/`domain:`/`nullrate:`/`freshness:`/`snapshot:`) | data |

## Truth-strength order (weakest → strongest)

`unbacked` < `shell_executable` (opaque) < `existence` (`path:`/`symbol:`) <
`raw_text` (`string:`/`regex:`) < `semantic_text` (`code:`) < `snapshot`
(`C1`/`C5 snapshot:`) < `data` (typed `C5`) < `structural` (`py-signature:`,
`py-const:`, `config-value:`) < `behavioral` (`C4 pytest:`).

## The two adequacy rules `--strength-gate=fail` enforces

1. A **behavior** claim needs a `C4 pytest:` checker. Backed only by existence/text
   (e.g. `symbol:`), it is an `adequacy_mismatch` and the gate refuses it — *exists*
   is not *behaves*.
2. A **quantity** claim needs a value-pinning checker (`py-const:` / `config-value:`
   / anchored `regex:` / typed `C5`). Backed only by `path:`/`symbol:` (existence)
   or an opaque `shell:`, it cannot prove the value, so the gate refuses it.

For the no-test facts this skill targets — config, signatures, constants,
references — prefer `config-value:`, `py-signature:`, `py-const:` (all structural).
Use `symbol:`/`path:` for genuine existence/reference claims, and reach for
`pytest:` only when a real, safe, known-passing test node exists.

## Picking `load_bearing`

- `true` → breaking it should **block** a merge (the warrant folds to `REVOKED`,
  exit 4). Use for the facts the change actually depends on.
- `false` → a soft signal that only `DEGRADE`s (exit 3). Non-load-bearing claims
  never score high-risk; they are the author's discretionary notes.

Weak binding or weak strength means **low confidence / coverage, not a false
claim** — strengthen the watch or the checker; never read a warning as falsity.
