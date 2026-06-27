# Demo — "Receipts for what your AI coding agent claimed it changed"

> A copy-paste demo, **under 3 minutes**, from a clean `pip install`. It seals the *checkable* claims
> from an AI agent's change summary into a git `.warrant`, then shows a later, unrelated change flip the
> warrant to **REVOKED** — naming the exact stale claim. **Zero LLM calls at check time.** Every command
> below was run first-hand on 2026-06-27 against `python-dotenv` at the pinned SHA.

## 0. Install (clean, zero runtime deps)

```bash
pip install dorian-vwp        # -> dorian 1.2.0 ; core has zero runtime dependencies
dorian --version
```

## 1. A real repo + a realistic agent change-note

```bash
git clone --depth 1 https://github.com/theskumar/python-dotenv.git && cd python-dotenv
git rev-parse HEAD   # 751f8c148222e58aa173c83c4e5e6cfccb2cc124 at time of writing

cat > AGENT_CHANGE_NOTE.md <<'MD'
## Summary (from the coding agent)
- `load_dotenv()` keeps its public signature, including `override=False` by default. [checkable]
- The package still targets Python `>=3.10`. [checkable]
- `dotenv_values()` remains the canonical parser entry point. [checkable]
- I made the code "cleaner and more maintainable". [NOT checkable — prose, left out]
MD
```

## 2. The agent emits receipts — a `claims.json` for the *checkable* subset only

```bash
cat > claims.json <<'JSON'
{"claims": [
  {"id": "load-dotenv-default-override-false",
   "text": "load_dotenv keeps override=False by default in its public signature.",
   "kind": "reference", "load_bearing": true,
   "checkers": [{"type": "C3", "program": "py-signature:src/dotenv/main.py::load_dotenv::dotenv_path=None, stream=None, verbose=False, override=False, interpolate=True, encoding=\"utf-8\""}]},
  {"id": "requires-python-3-10",
   "text": "The package targets Python >=3.10.",
   "kind": "quantity", "load_bearing": true,
   "checkers": [{"type": "C3", "program": "config-value:pyproject.toml:project.requires-python:\">=3.10\""}]},
  {"id": "dotenv-values-exists",
   "text": "dotenv_values() is the canonical parser entry point.",
   "kind": "reference", "load_bearing": true,
   "checkers": [{"type": "C3", "program": "symbol:src/dotenv/main.py::dotenv_values"}]}
]}
JSON
```

## 3. Seal — born-verifiable (refuses to seal anything false right now)

```bash
dorian verify AGENT_CHANGE_NOTE.md --claims claims.json --strength-gate=fail --binding-gate=warn
#   verified 3/3 claim(s) -> AGENT_CHANGE_NOTE.md.warrant   (exit 0, WARRANTED)
```

What you see: `--strength-gate=fail` confirms each load-bearing claim's checker can actually falsify it
(0 high-risk). `--binding-gate=warn` honestly notes `load_dotenv` is *also* mentioned in CHANGELOG/README
— a trigger-coverage hint, **not** a claim being false. The `.warrant` is a deterministic git sidecar.

## 4. Drift — a later change flips the default the summary claimed

```bash
# simulate a future, unrelated edit that changes behavior the summary asserted
sed -i.bak 's/    override: bool = False,/    override: bool = True,/' src/dotenv/main.py
git add -A && git commit -m "change override default"
```

`AGENT_CHANGE_NOTE.md` never changed and still reads perfectly. The repo's own tests/CI don't know the
*summary* made a promise about `override`.

## 5. Revalidate — the stale receipt REVOKES, by name

```bash
dorian revalidate --since HEAD~1
#   BROKEN  load-dotenv-default-override-false  C3: signature_mismatch: load_dotenv: default of 'override': 'True' != expected 'False'
#   VERIFIED dotenv-values-exists
#   fold    WARRANTED -> REVOKED                (exit 4)
```

`exit 4` is the gate. The default `dorian` GitHub Action (`fail_on: revoked`) turns this into a blocked
PR — so a summary claim that silently stopped being true cannot ship unnoticed. **No tokens were spent
to re-check** — it is a `git show` + an `ast` parse.

## The one-screen point

| | Without Dorian | With Dorian |
|---|---|---|
| The agent's summary | prose nobody re-checks | the checkable subset becomes git receipts |
| A later refactor breaks a claim | summary silently rots; tests stay green | warrant flips **REVOKED**, names the claim |
| Re-check cost | a human re-reads, or an LLM re-judges (tokens) | deterministic, token-free, milliseconds |

## Notes / honest limits

- `py-signature` caught a **default-value** change that a `symbol:` existence check would miss — pick the
  checker strength that matches the claim (that is the *truth axis*; `--strength-gate` audits it).
- A **C4 `pytest:`** behavior claim is even stronger, but it needs the target's test env to be runnable
  (missing test deps → `ERRORED_AT_SEAL`, fail-closed — never a false pass). Structural C3 claims
  (`py-signature`/`config-value`/`symbol`) need no deps and are the low-friction default.
- Dorian verifies **specific, checkable** claims in **trusted** repos. It is not a sandbox, not an LLM
  judge, and not a replacement for tests/review. See [`SECURITY_BOUNDARY.md`](SECURITY_BOUNDARY.md).
