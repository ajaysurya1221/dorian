# Real catch log

A running, honest record of times dorian caught (or missed) something on **real
work** — the evidence that matters more than any synthetic benchmark. One real
claim-break caught on a real change outweighs P=0.93 on invented fixtures.

This file is a template + ledger. No entries are fabricated; an empty ledger is
the correct state until a real catch happens. Each entry is one row of facts a
skeptic could check.

## How to log a catch

Copy the block below, fill every field, append it under "Entries". If a field
does not apply, write `n/a` — do not delete it. "Outcome" must be one of:
**true-catch** (a real break dorian flipped to BROKEN/REVOKED that you would have
shipped), **false-alarm** (dorian said broken; the claim was actually fine),
**miss** (a real break dorian did not catch), **partial** (triggered but the
checker could not confirm — trigger-vs-truth gap), or **weak-binding-warning**
(a binding diagnostic, not a verdict).

```md
### <date> — <one-line summary>

- **Claim:** "<the natural-language claim>"
- **Checker:** `<type:program>`  (e.g. `C3 regex:src/config.py::TIMEOUT\s*=\s*30`)
- **Repo / project:** <name> (public-safe? yes/no)
- **Source commit that sealed it:** <sha>
- **Change that triggered revalidation:** <sha or description>
- **Outcome:** <true-catch | false-alarm | miss | partial | weak-binding-warning>
- **Verdict dorian gave:** <PASS | BROKEN | ERRORED | recalled | n/a>
- **Would you have shipped the break otherwise?** <yes/no — be honest>
- **User time spent (setup + review):** <minutes>
- **Reviewer notes:** <what actually happened, including any false-positive cause>
```

## What counts (and what doesn't)

- A **true-catch** requires that the break was real *and* that you would
  plausibly have shipped it without dorian. "Caught a break I introduced on
  purpose to test dorian" is not a catch — log it under the benchmark docs.
- A **false-alarm** is as important to log as a catch. Hiding false positives is
  how a verification tool loses the right to be trusted.
- A **partial** (triggered, checker couldn't confirm) documents the
  trigger-vs-truth ceiling on real work — valuable, not a failure to bury.

## Entries

### 2026-06-17 — httpx `requires-python` floor `>=3.8` → `>=3.9` (real upstream PR #3592)

- **Claim:** "httpx declares a minimum supported Python of 3.8 (pyproject project.requires-python is `">=3.8"`)."
- **Checker:** `C3 config-value:pyproject.toml:project.requires-python:">=3.8"`
- **Repo / project:** [`encode/httpx`](https://github.com/encode/httpx) (public-safe? **yes** — BSD-3-Clause, frozen public SHAs)
- **Source commit that sealed it:** `336204f0121a9aefdebac5cacd81f912bafe8057` (commit A)
- **Change that triggered revalidation:** `4fb9528c2f5ac000441c3634d297e77da23067cd` — real upstream **"Drop Python 3.8 support (#3592)"** by Alex Grönholm
- **Outcome:** **true-catch**
- **Verdict dorian gave:** **BROKEN** (`WARRANTED → REVOKED`, exit 4)
- **Would you have shipped the break otherwise?** **yes** — `requires-python` is packaging metadata covered by no test (`grep -rn requires-python tests/` is empty; B's diff touches 8 files, none under `tests/`), so httpx's CI is green at B; and a per-PR review bot is stateless — it has no memory of commit A's claim and PR #3592's own diff is self-consistent, so nothing re-opens the old note.
- **User time spent (setup + review):** ~10 minutes
- **Reviewer notes:** dogfood on a real public repo at frozen SHAs; **independently reproduced** end-to-end. The other three sealed claims (`Client` defined in `_client.py`, `Client` exported, version `0.28.1`) stayed VERIFIED — dorian narrowed revalidation to the **1 candidate** whose source (`pyproject.toml`) actually changed. Full captured output and reproduction below.

#### Captured output

**1. Seal at A — `dorian verify` (exit 0):**

```
$ dorian verify note.md --claims claims.json
sha256:7db02138b329729b4f84b20d37a1154e237c07993783750a3c26e3531334b8a2
verified 4/4 claim(s) against current sources -> note.md.warrant
# exit 0
```

The warrant id is `sha256(canonical_json(body))` over the sealed body — **tamper-evident**
(any later edit to the warrant is detected on load via an id mismatch). The body includes the
seal timestamp, so a *fresh* seal of the same inputs produces a *different* id; the id shown
here is from this run. What reproduces across runs is the **outcome**, not the id: a seal at A
(exit 0, 4/4) and a flip to REVOKED at B (exit 4).

**2. The real upstream drift — `git show 4fb9528 --stat`:**

```
 Drop Python 3.8 support (#3592)
 .github/workflows/publish.yml    | 2 +-
 .github/workflows/test-suite.yml | 2 +-
 CHANGELOG.md                     | 6 ++++++
 README.md                        | 2 +-
 docs/async.md                    | 2 +-
 docs/index.md                    | 2 +-
 pyproject.toml                   | 3 +--
 requirements.txt                 | 3 +--
 8 files changed, 13 insertions(+), 9 deletions(-)

# the pyproject.toml hunk:  -requires-python = ">=3.8"   +requires-python = ">=3.9"
```

**3. The drift is silent to the test suite** — PR #3592 touches no test file, and no test
references the key:

```
$ grep -rn "requires-python" tests/
# (no matches)
```

**4. Re-check at B — `dorian revalidate --since A` (exit 4):**

```
$ dorian revalidate --since 336204f0121a9aefdebac5cacd81f912bafe8057
checked 1 candidate claim(s)
BROKEN    sha256:7db02138b329729b httpx-python-floor-38  C3: config_value_mismatch: project.requires-python
fold      sha256:7db02138b329729b WARRANTED -> REVOKED
# exit 4
```

**5. Resulting state — `dorian status` (exit 4):**

```
$ dorian status note.md
REVOKED   note.md  sha256:7db02138b329729b  BROKEN=1 VERIFIED=3
```

#### The change-note and claims (verbatim, so the run is reproducible)

`note.md`:

```markdown
# Change note: pin our integration to httpx's supported Python floor

We depend on `httpx` and need our CI matrix to track the library's own support
window. As of this change, the facts our integration relies on are:

- httpx's packaging declares a minimum Python of **3.8** (`project.requires-python`
  is `">=3.8"` in `pyproject.toml`), so our service may still run on Python 3.8.
- The public `Client` class is defined in `httpx/_client.py`.
- `Client` is listed in the top-level `httpx` package exports (`httpx/__init__.py`).
- The pinned library version is `0.28.1` (`httpx/__version__.py`).

If httpx raises its supported Python floor, our 3.8 CI lane must be dropped in the
same change — that is the load-bearing fact below.
```

`claims.json`:

```json
{
  "claims": [
    {"id": "httpx-python-floor-38", "text": "httpx declares a minimum supported Python of 3.8 (pyproject project.requires-python is \">=3.8\").",
     "kind": "quantity", "load_bearing": true,
     "checkers": [{"type": "C3", "program": "config-value:pyproject.toml:project.requires-python:\">=3.8\""}]},
    {"id": "httpx-client-defined", "text": "The public Client class is defined in httpx/_client.py.",
     "kind": "behavior", "load_bearing": true,
     "checkers": [{"type": "C3", "program": "symbol:httpx/_client.py::Client"}]},
    {"id": "httpx-client-exported", "text": "Client is listed in the top-level httpx package exports.",
     "kind": "behavior", "load_bearing": false,
     "checkers": [{"type": "C3", "program": "string:httpx/__init__.py::\"Client\""}]},
    {"id": "httpx-version-0281", "text": "The pinned httpx version is 0.28.1.",
     "kind": "quantity", "load_bearing": false,
     "checkers": [{"type": "C3", "program": "py-const:httpx/__version__.py::__version__::\"0.28.1\""}]}
  ]
}
```

#### Reproduce it yourself (public repo, frozen SHAs)

```bash
pip install dorian-vwp
git clone https://github.com/encode/httpx && cd httpx
git checkout -b dorian-catch 336204f0121a9aefdebac5cacd81f912bafe8057   # A
# write note.md and claims.json exactly as above, then:
dorian verify note.md --claims claims.json        # -> verified 4/4, exit 0
git add note.md note.md.warrant claims.json && git commit -m "seal at A"
git cherry-pick 4fb9528c2f5ac000441c3634d297e77da23067cd   # real upstream B: Drop Python 3.8 (#3592)
dorian revalidate --since 336204f0121a9aefdebac5cacd81f912bafe8057
# -> httpx-python-floor-38 BROKEN; WARRANTED -> REVOKED; exit 4
dorian status note.md                             # -> REVOKED  BROKEN=1 VERIFIED=3
```

#### Honest scope — what this does and does **not** show

**Does show:** on a real public repo, a load-bearing claim sealed at A was flipped to REVOKED
by a real, unrelated later commit, deterministically and reproducibly, when no test, no CI
signal, and no stateless per-PR review would have re-opened it.

**Does not show:** that dorian flags drift it was not bound to, that one example "proves" httpx
correct, or that this result extrapolates. It re-checks **only the properties you explicitly
bound** — here, one config value. A claim bound only to a structural existence checker (e.g. `symbol:`) would **not**
flip if a function were gutted while keeping its name (the trigger≠truth / gutted-body
ceiling — see [WRITING_GOOD_CLAIMS.md](WRITING_GOOD_CLAIMS.md)). This is **one documented
catch**, not a benchmark; inventing more would violate [VALIDATION_HONESTY.md](VALIDATION_HONESTY.md).
