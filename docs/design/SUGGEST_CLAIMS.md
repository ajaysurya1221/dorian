# Design note — `dorian suggest-claims`

`suggest-claims` is the C3 counterpart to `suggest-data-checks`: a deterministic,
zero-model helper that lowers the authoring tax by proposing born-verifiable claims for a
Python file. It is **scaffolding for review**, not auto-application, and never a substitute
for thinking about what is load-bearing.

## Shipped (v1.0.x)

`dorian suggest-claims <file.py> [--out F]` (implemented in `src/dorian/suggestclaims.py`):

- Proposes `symbol:<file>::<name>` for every non-private top-level `def`/`class`. A name
  defined in more than one tracked file is **skipped loudly** (ambiguous binding) and noted
  on stderr.
- Proposes `py-const:<file>::<NAME>::<literal>` for every non-private module-level assignment
  whose RHS is a simple Python literal (int/float/str/bool/None). Containers are skipped
  (conservative).
- **Runs every candidate** against current source via the real C3 checker and emits **only
  the ones that PASS** — so the `{"claims": [...]}` fragment seals unmodified
  (`dorian verify <file> --claims <fragment>` → exit 0). Pinned by
  `tests/test_suggest_claims.py::test_suggest_claims_output_seals_unmodified`.
- `load_bearing` defaults to **false** on every suggestion; the reviewer promotes the ones
  that matter.

## Honest scope / known ceiling

These suggestions check **existence and value, not behavior**. A `symbol:` claim stays green
when a function body is gutted (trigger ≠ truth — see
[../WRITING_GOOD_CLAIMS.md](../WRITING_GOOD_CLAIMS.md)). The command exists to remove
boilerplate, not to certify behavior; pair behavior claims with a C4 `pytest:` or C5 check.

## Deferred (gated on adoption demand, per the launch plan)

The launch analysis (four research packets + red-team) cautions against racing breadth here:
auto-suggestion is a commoditized space, and the durable value is the persisted cross-PR
re-check, not the generator. So the following are **deferred until real users ask**, each a
clean, additive extension of the same run-and-keep-green pattern:

- `--since <ref>` diff mode: propose claims only for symbols/constants that **changed**
  between a base ref and HEAD (uses `gitio` for the changed-file set).
- `py-signature:` suggestions (propose the current signature of changed public functions).
- `config-value:` suggestions for TOML/JSON keys with literal values.
- `path:` suggestions for referenced files.
- A `--load-bearing <ids>` convenience to flag specific suggestions up front.

None of these change the seal/verify contract; each is "add a candidate generator, run it,
keep the green ones." They are intentionally not built yet.
