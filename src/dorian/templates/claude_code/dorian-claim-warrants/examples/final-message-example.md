# Example final assistant message → claim warrants

This shows how the checkable subset of a normal end-of-turn summary becomes claim
warrants. The skill reads a message like this (plus the real git diff) and drafts
`docs/changes/<slug>.md` + `docs/changes/<slug>.claims.json`.

## The agent's summary (what it actually said)

> I added `verify_token(token, algo="RS256") -> bool` to `src/auth.py`, set
> `LOGIN_TIMEOUT = 30`, bumped `requires-python` to `>=3.11` in `pyproject.toml`,
> and cleaned up the imports. This is a big improvement and should be faster.

## What the skill keeps vs drops

| Statement | Verdict | Checker |
|---|---|---|
| `verify_token` signature/default is `(token, algo="RS256") -> bool` | **warrant** | `py-signature:src/auth.py::verify_token::token, algo="RS256" -> bool` |
| `LOGIN_TIMEOUT = 30` | **warrant** | `py-const:src/auth.py::LOGIN_TIMEOUT::30` |
| `requires-python` is `>=3.11` | **warrant** | `config-value:pyproject.toml:project.requires-python:">=3.11"` |
| "cleaned up the imports" | **drop** (prose) | — |
| "big improvement", "should be faster" | **drop** (opinion/perf) | — |

The three kept facts go into `<slug>.claims.json` (see `good-claims.json`); the two
dropped ones are listed under "Non-checkable claims intentionally excluded" in the
change note. Then:

```bash
dorian verify docs/changes/<slug>.md \
  --claims docs/changes/<slug>.claims.json \
  --strength-gate=fail --binding-gate=warn
```

Only if that exits 0 are the claims sealed into a `.warrant`. Until then they are a
**DRAFT — not verified**.
