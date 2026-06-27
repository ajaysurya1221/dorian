# `--strength-gate` demo

A self-contained, copy-paste run on a throwaway repo showing the truth-axis gate across all four
states. It leaves nothing behind but a temp directory. The behaviour shown here is pinned by
`tests/test_adequacy_gate.py`, so it is executable and kept working, not just illustrative.

`--strength-gate` is the **truth-axis** companion to `--binding-gate`: binding gates *when* a claim
re-checks; strength gates *whether* its checker can actually falsify it. It is **opt-in (default
`off`)**, never marks a claim false, and maps a refusal to the existing seal-refused exit code (4) —
it changes no trust state and adds no code-execution path. See
[`VALIDATION_HONESTY.md`](VALIDATION_HONESTY.md) for the two-layer contract.

## Setup

```bash
tmp=$(mktemp -d) && cd "$tmp" && git init -q
# a real behavior: login rejects expired tokens
printf 'def login(user, token):\n    """Authenticate; rejects expired tokens."""\n    return bool(token) and not token.endswith("EXPIRED")\n' > auth.py
printf '# change note\n\nlogin() now rejects expired tokens.\n' > note.md
git add -A && git commit -q -m "auth + note"

# a LOAD-BEARING *behavior* claim, but backed only by an existence check (symbol:) —
# the checker can prove login() still EXISTS, but can never prove it rejects expired tokens.
cat > claims.json <<'JSON'
{"claims": [
  {"id": "login-behavior", "text": "login() rejects expired tokens.",
   "kind": "behavior", "load_bearing": true,
   "checkers": [{"type": "C3", "program": "symbol:auth.py::login"}]}
]}
JSON
```

## 1. Default (`off`) — green-but-weak seals silently (today's behavior, unchanged)

```bash
dorian verify note.md --claims claims.json
# -> verified 1/1 claim(s) against current sources -> note.md.warrant   (exit 0)
rm -f note.md.warrant
```

The claim seals TRUSTED even though its checker cannot catch the behavior going false. This is the
green-but-weak false confidence the gate exists to surface.

## 2. `--strength-gate=warn` — seals, but surfaces the truth-axis smell (exit 0)

```bash
dorian verify note.md --claims claims.json --strength-gate warn
# stderr:
#   login-behavior: adequacy_mismatch: 'behavior' claim backed only by existence
#                   — only a C4 pytest checker proves behavior
#   --strength-gate=warn: claim-risk: 1 high, 0 medium, 0 low; 1 load-bearing high-risk ...
# -> verified 1/1 claim(s)   (exit 0)   # warn NEVER blocks
rm -f note.md.warrant
```

## 3. `--strength-gate=fail` — refuses the seal (exit 4), writes nothing

```bash
dorian verify note.md --claims claims.json --strength-gate fail
# stderr:
#   weak checker: claim 'login-behavior' (kind=behavior, backed only by existence) — adequacy_mismatch: ...
#   --strength-gate=fail refused seal: 1 load-bearing claim(s) whose checker is too weak ...; no sidecar written
echo "exit=$?"                       # -> exit=4
test -f note.md.warrant && echo "sidecar written (BUG)" || echo "no sidecar (atomic no-write)"
```

The refusal runs **after** every checker passes and **before** any write, so nothing is sealed or
indexed. A claim whose checker is *false* would already have been refused earlier (`FAILED_AT_SEAL`),
so the gate never masks a false claim and never marks one BROKEN.

## 4. Fix the evidence — an adequate checker seals under `fail`

Replace the existence checker with one that actually constrains the behaviour. A **structural**
`py-signature:` (stdlib `ast`, no subprocess) is enough to clear the gate:

```bash
cat > claims.json <<'JSON'
{"claims": [
  {"id": "login-behavior", "text": "login() takes user and token.",
   "kind": "behavior", "load_bearing": true,
   "checkers": [{"type": "C3", "program": "py-signature:auth.py::login::user, token"}]}
]}
JSON

dorian verify note.md --claims claims.json --strength-gate fail
# -> verified 1/1 claim(s)   (exit 0)   # structural backing is adequate; the gate allows it
```

For a claim that genuinely needs *behavioral* proof (not just a signature), back it with a **C4
`pytest:` test** instead — only a passing test proves the body still rejects expired tokens:

```jsonc
{"type": "C4", "program": "pytest:test_auth.py::test_rejects_expired"}
```

A C4-backed behavior claim also seals under `--strength-gate=fail` (its strength is `behavioral`,
the strongest tier). This is the intended authoring path: *let the gate push load-bearing behavior
claims toward tests.*

## What the gate does and does not refuse

| Load-bearing claim | strongest checker | `--strength-gate=fail` |
|---|---|---|
| `behavior` ← `symbol:` / `path:` (existence) | existence | **refuse** |
| `behavior` ← `string:` / `regex:` (raw text) | raw_text | **refuse** |
| `behavior` ← `shell:` (opaque) | shell_executable | **refuse** |
| `behavior` ← `code:` (semantic) | semantic_text | allow (warn-level `medium`) |
| `behavior` ← `py-signature:` / `py-const:` (structural) | structural | **allow** |
| `behavior` ← `pytest:` (behavioral) | behavioral | **allow** |
| `quantity` ← existence / opaque | existence / shell | **refuse** |
| `fact` / `reference` / `decision` ← existence | existence | **allow** (existence is adequate for a fact) |
| any of the above, **not** load-bearing | — | **allow** (a soft claim is the author's call) |
| unbacked, load-bearing | unbacked | **refuse** |
