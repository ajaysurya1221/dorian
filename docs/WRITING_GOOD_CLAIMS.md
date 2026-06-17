# Writing good claims

`dorian` does not understand your prose. When sources change it re-checks **only
the properties you explicitly bind** — and it re-checks them with the checker you
chose, nothing more. So the quality of a warrant is the quality of its checkers.

> **A claim is only as strong as its checker.** The natural-language `text` is for
> humans; the `checkers` list is the contract dorian enforces. A perfectly worded
> claim bound to a weak checker is a weak claim.

This page is about *choosing the right checker for what you actually mean*. For the
full grammar of every checker program string, see
[`../spec/checkers.md`](../spec/checkers.md); for the `claims.json` schema and the
authoring workflow, see [`AGENT_CLAIMS.md`](AGENT_CLAIMS.md).

The truth-strength ladder dorian uses to score a checker (low → high) is:

```
existence < raw_text < semantic_text < snapshot < data < structural < behavioral
```

`symbol:`/`path:` are `existence`; `string:`/`regex:` are `raw_text`; `code:` is
`semantic_text`; `py-signature:`/`py-const:`/`config-value:` are `structural`;
typed C5 is `data`; `pytest:` is `behavioral`. Pick the highest rung your claim
actually warrants.

---

## Three good / bad claim pairs

Each pair shows the weak version (unbound, ambiguous, or under-checked) and the
good version (bound to the checker that actually falsifies the claim). Every
program string below is real dorian grammar, verified by running `dorian verify`
and `dorian revalidate`.

### Pair 1 — "the timeout is 30 seconds" (a *quantity* claim)

**Bad** — bound to a bare substring `30`. A two-character literal near-matches half
the file; it also passes if `30` survives only in a comment or an unrelated line.
dorian seals it, but the binding is weak (it flags `short-literal`).

```json
{"id": "timeout-30", "text": "the request timeout is 30 seconds",
 "kind": "quantity", "load_bearing": true,
 "checkers": [{"type": "C3", "program": "string:src/auth.py::30"}]}
```

**Good** — bound to the *value* of the named constant. `py-const:` parses the AST
and compares the literal value (`30` matches `0x1E`, tolerant of formatting), so it
FAILs the instant the number changes and cannot be satisfied by a stray `30`
elsewhere.

```json
{"id": "timeout-30", "text": "the request timeout (TIMEOUT) is 30 seconds",
 "kind": "quantity", "load_bearing": true,
 "checkers": [{"type": "C3", "program": "py-const:src/auth.py::TIMEOUT::30"}]}
```

```
py-const:<file>::<qualname>::<literal>     # structural (Python AST)
```

On a real run, editing `TIMEOUT = 30` to `25` flips this to
`BROKEN  C3: const_mismatch`; the value is genuinely bound. (If the constant is not
a Python module/class assignment — e.g. it lives in TOML — use `config-value:`; if
the fact must survive whitespace reformatting in raw text, an anchored
`regex:src/auth.py::TIMEOUT\s*=\s*30` is the `raw_text` middle ground.)

### Pair 2 — "verify_token takes (token, algo)" (a signature *fact*)

**Bad** — bound to `symbol:`, which only proves a `def verify_token` *exists*. It
passes even after every parameter is renamed or reordered, so it does not actually
hold the signature.

```json
{"id": "sig", "text": "verify_token takes (token, algo)",
 "kind": "behavior", "load_bearing": true,
 "checkers": [{"type": "C3", "program": "symbol:src/auth.py::verify_token"}]}
```

**Good** — bound to `py-signature:`, which parses the AST and compares parameter
names, order, and kind. Adding a parameter flips it to
`BROKEN  C3: signature_mismatch: verify_token: param count 3 != expected 2`.

```json
{"id": "sig", "text": "verify_token takes (token, algo)",
 "kind": "behavior", "load_bearing": true,
 "checkers": [{"type": "C3", "program": "py-signature:src/auth.py::verify_token::token, algo"}]}
```

```
py-signature:<file>::<qualname>::<sigspec>   # names/order/kind always compared;
                                             # annotations/defaults/return/async
                                             # compared ONLY when you state them
```

State exactly as much as you mean: `token, algo` checks names and order;
`token: str, algo: str = "RS256" -> bool` additionally pins the annotations,
default, and return type. (Note: `py-signature:` still does **not** prove the
function *behaves* correctly — see the gutted-body ceiling below.)

### Pair 3 — "requires-python is >=3.9" (a config *quantity* claim)

**Bad** — a bare `regex:` over `pyproject.toml`. It matches the literal text but
treats the value as a string blob, and a regex on a structured file is brittle to
quoting and key relocation.

```json
{"id": "pyfloor", "text": "requires-python is >=3.9",
 "kind": "quantity", "load_bearing": true,
 "checkers": [{"type": "C3", "program": "regex:pyproject.toml::requires-python\\s*=\\s*\">=3.9\""}]}
```

**Good** — bound to `config-value:`, which parses the TOML and compares the value at
the dotted key path **by value and type**. A real upstream PR that bumped this floor
flipped it to `BROKEN  C3: config_value_mismatch: project.requires-python` (see
[`REAL_CATCH_LOG.md`](REAL_CATCH_LOG.md)).

```json
{"id": "pyfloor", "text": "requires-python is >=3.9",
 "kind": "quantity", "load_bearing": true,
 "checkers": [{"type": "C3", "program": "config-value:pyproject.toml:project.requires-python:\">=3.9\""}]}
```

```
config-value:<path>:<dotted.key.path>:<json-literal>   # structural (TOML/JSON),
                                                       # single ':' separators,
                                                       # value AND type compared
```

`config-value:` uses single-`:` separators (unlike the `::` C3 forms) and is
TOML/JSON only — no YAML in v1.

---

## The gutted-body ceiling (trigger ≠ truth)

This is the single most important limitation to internalize, and the one that most
often disappoints. **A structural existence checker re-checks that a name/signature
still exists — it does not re-check what the code does.** If a function's *body* is
gutted while its name and signature stay the same, a `symbol:` or `py-signature:`
claim stays GREEN.

Worked example, reproduced end-to-end. We seal a `symbol:` claim, then replace the
function body with `return True` (name and signature untouched):

```python
# before
def verify_token(token, algo="RS256"):
    return token.algo == algo

# after — GUTTED: name and signature identical, behavior destroyed
def verify_token(token, algo="RS256"):
    return True
```

```json
{"id": "verify-exists", "text": "verify_token exists",
 "kind": "behavior", "load_bearing": true,
 "checkers": [{"type": "C3", "program": "symbol:src/auth.py::verify_token"}]}
```

`dorian revalidate` on the gutted commit — the binding *fires the re-check*, but the
existence checker still passes, so the warrant does **not** flip:

```
checked 1 candidate claim(s)
VERIFIED  sha256:dc07f6acd661d841 verify-exists
fold      sha256:dc07f6acd661d841 WARRANTED -> TRUSTED
# exit 0  — the body was gutted and dorian stayed green
```

The *only* thing that catches this is a checker that observes behavior. With a
**C4 `pytest:`** test bound to the same claim, the same gutted commit flips:

```json
{"id": "verify-behavior", "text": "verify_token returns False on an algorithm mismatch",
 "kind": "behavior", "load_bearing": true,
 "checkers": [{"type": "C4", "program": "pytest:tests/test_auth.py::test_rs256"}]}
```

```
checked 1 candidate claim(s)
BROKEN    sha256:b4f5a06cac89ab6e verify-behavior  C4: test_failing
fold      sha256:b4f5a06cac89ab6e WARRANTED -> REVOKED
# exit 4  — the behavior checker caught the gutted body
```

This is honest and by design: **structural checkers re-check existence and shape,
not behavior.** `py-signature:` is blind to a body-only change for exactly the same
reason (the signature is unchanged, so it PASSes). A **C4 `pytest:`** test, or a
**C5** data checker for a data fact, is the only thing that can falsify a behavior
or value-of-output claim. If your claim is about what the code *does*, an existence
checker is not enough — it only tells you the symbol is still there.

---

## Authoring checklist

Run through this for every claim before you seal it:

- [ ] **Is the claim explicit?** The `text` names the specific symbol, file, key, or
      value — not "we improved auth." A vague claim cannot be bound to a precise
      checker.
- [ ] **Is it load-bearing?** Set `load_bearing: true` only when a downstream
      decision depends on it (a load-bearing break folds the warrant to REVOKED; a
      non-load-bearing one only to DEGRADED). Don't inflate everything.
- [ ] **Is the checker structural, behavioral, or data-backed — and does that match
      the claim?** Match the rung to the meaning:
  - existence of a name/file → `symbol:` / `path:`
  - presence of a literal → `string:` (short) / `regex:` (reformat-tolerant)
  - a signature / a constant value / a config value → `py-signature:` /
    `py-const:` / `config-value:` (structural)
  - what the code **does** → `pytest:` (C4, behavioral)
  - a data property (rows, schema, nullrate, snapshot) → typed **C5**
- [ ] **What edit SHOULD revoke this claim?** Name it. Then convince yourself the
      checker actually FAILs on that edit. If you can't, the checker is too weak.
- [ ] **What edit should NOT revoke it?** A whitespace reformat, a rename of an
      unrelated symbol, a comment edit. Prefer `regex:`/`py-const:`/`py-signature:`
      over `string:` so benign churn doesn't false-alarm.
- [ ] **For every behavior claim: is there a C4/C5 check — not just a `symbol:`
      existence check?** If `kind` is `behavior` and the only checker is `symbol:`/
      `py-signature:`, you have a gutted-body blind spot. Bind a `pytest:` test.

---

## Let the strength advisory find your weak claims

You don't have to eyeball this. `dorian bindings <artifact>` reports each claim's
**trigger** flags (when it gets re-checked) *and* its **truth strength** and risk
(whether the checker can actually falsify it). It never runs a checker, never
changes a verdict — it is purely advisory.

On the two weak claims from the pairs above (a `behavior` claim backed only by
`symbol:`, and a `quantity` claim backed only by a short string literal), the real
output is:

```
$ dorian bindings note.md
verify-exists  flags: single-file
  strength: existence  risk: high (adequacy_mismatch)
  adequacy_mismatch: 'behavior' claim backed only by existence — only a C4 pytest checker proves behavior
timeout-30  flags: single-file, short-literal
  strength: raw_text  risk: medium (binding:short-literal)
2 claim(s), 2 flagged
```

`adequacy_mismatch` is the advisory telling you the checker is too weak for the
claim's `kind`; `short-literal` warns that a tiny literal near-matches too much.
Treat a `high` risk on a load-bearing claim as a prompt to upgrade the checker
before you ship the warrant.

---

See [`../README.md`](../README.md) for how `verify` / `revalidate` fit together, and
[`REAL_CATCH_LOG.md`](REAL_CATCH_LOG.md) for the running ledger of what dorian has
actually caught (and missed) on real changes — including the trigger-vs-truth
ceiling described above, on a real repo.
