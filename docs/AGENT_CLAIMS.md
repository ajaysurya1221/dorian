# Agent claims contract

When you (an AI coding agent, or a human author) finish a change, emit a `claims.json`
next to the artifact it describes and run:

```bash
dorian verify <artifact> --claims claims.json
```

**Exit 0** means every *backed* claim held against the real, current sources and a
`.warrant` sidecar was sealed. **Exit 4** means a claim is false right now — or its
checker could not run — so the seal is refused and *nothing is written*: fix the claim
or fix the code. This is the supported way to produce warrant claims. The LLM extractor
(`--extract`) is frozen (see the bottom of this page).

This page is the authoring companion to two references it deliberately does **not**
duplicate (a second copy would be exactly the drift dorian exists to catch):

- [`spec/checkers.md`](../spec/checkers.md) — the authoritative checker grammar.
- [`spec/warrant.schema.json`](../spec/warrant.schema.json) — the sealed-sidecar JSON schema
  (every claim serializes `checkers`, even when empty, so its required set is not the
  authoring-input set below).

> ⚠️ **Checker programs are executable.** `dorian verify` *runs* every checker at seal time, on
> the machine you run it on. C3 and typed C5 only inspect files — but **C4 (`pytest:`) and C5
> `shell:` execute code**: pytest collection imports the target module and any `conftest.py`, and
> `shell:` runs its command. Review an agent-emitted `claims.json` exactly as you would review
> agent-emitted code, and never run `verify` on claims from an untrusted source.
> `[tool.dorian.scopes]` restricts the auto-captured read-set — files a claim's checkers name, plus
> the file `verify` binds from a symbol the claim mentions — not what an executed checker may read or
> write; it is not a sandbox. See the Action's
> [security notes](../action/README.md#security-checker-execution-and-untrusted-pull-requests).

## 1. The `claims.json` shape

```json
{
  "claims": [
    {
      "id": "login-ratelimit-added",
      "text": "Rate limiting guards the /login route.",
      "kind": "behavior",
      "load_bearing": true,
      "checkers": [
        { "type": "C3", "program": "symbol:src/api/auth.py::rate_limit" }
      ]
    }
  ]
}
```

Each claim has **four required fields** and three optional ones:

| field | required | meaning |
|---|---|---|
| `id` | yes | stable, kebab/scope-prefixed handle — the store key and the `blast`/`--supersede` handle. Never auto-generated; never renumber. |
| `text` | yes | the human-auditable assertion, in your words. |
| `kind` | yes | one of `fact`, `reference`, `behavior`, `quantity`, `decision`. |
| `load_bearing` | yes | decides REVOKE vs DEGRADE on a future break — see §2. |
| `anchor` | no (`null`) | line span + quote of the artifact (C1 only). |
| `supports` | no (`[]`) | read-set entry ids (C1 only; `verify` auto-derives the rest). |
| `checkers` | no (`[]`) | the deterministic checks (§4–5). A claim with none is **UNBACKED** — see R1. |

`kind` and `load_bearing` are **not** defaulted, on purpose: `load_bearing` changes what
a future break *does*, so you must decide it per claim (§2), and `kind` records intent for
`dorian report`/`bindings`. Omitting any required field is a hard error identifying the offending claim by its position in the list.

## 2. `load_bearing`: loud vs quiet

The single most consequential field.

- `load_bearing: true` → if this claim later breaks, the warrant folds to **REVOKED**
  (`dorian revalidate` exits 4 — the loud, CI-blocking signal).
- `load_bearing: false` → a break only **DEGRADES** it (exit 3 — a soft warning).

Set `false` only for a claim you would *not* want to block a merge. Marking everything
`false` yields a warrant that can never hard-fail (accountability theater); marking sloppy
claims `true` floods CI with exit 4. Decide per claim.

## 3. The three false-confidence rules

A warrant is worth only what its checkers actually catch. Three ways a claim can "verify"
while proving nothing — avoid all three:

- **R1 — back every load-bearing claim.** A claim with no checker is `UNBACKED`: it seals
  green (exit 0) and counts in `verify`'s `N/total`, but it checks nothing. Every
  load-bearing claim needs ≥1 checker.
- **R2 — bind the file that would change.** A checker must watch the file that would change
  *if the claim went false* — not merely a file where the identifier happens to appear.
  `revalidate` re-checks a claim only when a changed path intersects its watch; bind the
  wrong file and the claim stays `VERIFIED` forever while reality drifts.
- **R3 — prefer shape-tolerant checks.** Use `regex:`, `symbol:`, or typed `C5` over
  `string:` for any fact that must survive reformatting.

If you cannot name a deterministic check for an assertion, **do not emit a claim** — put it
in prose.

## 4. Picking a checker from your sentence

| Your claim | Use | Avoid | Why |
|---|---|---|---|
| "function/class `X` exists" | `C3 symbol:<file>::X` | `C3 string:<file>::def X` | `symbol:` survives reformatting, decorators, `async def`; `string:` breaks on `def  X` and false-passes on a mention in a comment. |
| "`TIMEOUT` is 30" / any value | `C3 regex:<file>::TIMEOUT\s*=\s*30\b` | `C3 string:<file>::TIMEOUT = 30` | `regex:` tolerates spacing — but **anchor BOTH key and value**: a bare `TIMEOUT` regex still passes after the value changes (a silent false pass). |
| "config key / identifier present" | `C3 regex:` anchored to the key | `C3 string:` of a short literal | literals < 6 chars near-match everything (flagged `short-literal`); a bare string also survives if it lives only in a comment. |
| "tests for `X` pass" | `C4 pytest:<file>::<test>` | `C3 string:` of an assert line | `C4` actually runs the test and tells `test_gone` (FAIL) from infra (ERROR); a string only proves text exists. |
| "file/path exists" | `C3 path:<repo/path>` | a regex on a sibling file | `path:` is existence, rename-resolved. |
| "table has column / rowcount / domain / freshness" | typed `C5` (`schema:`/`rowcount:`/`domain:`/`freshness:`/`nullrate:`) | `C5 shell:'grep … data.csv'` | typed `C5` parses the data and auto-derives its watch; `nullrate`/`domain`/`freshness` add a no-rows vacuous-truth guard (an empty dataset can't support the claim), while `rowcount`/`schema` do not — bound those deliberately; `shell:` is opaque and needs explicit `watch` + `expect`. |
| "this exact data file is unchanged" | `C5 snapshot:<path>` | a C1 span on data | `snapshot:` is a content hash. |
| "this prose span is unchanged" | `C1` span — **`capture` + `seal`, not `verify`** | `string:` of a paragraph | `C1` hashes the span and follows relocation; `verify` rejects C1 (exit 2). |

Use repo-relative paths only (absolute or `..` are rejected). Prefer literal-anchored regex
with bounded `\s*` gaps — **never** nested quantifiers like `(a+)+`: `C3` runs in-process,
ignores `timeout_s`, and a backtracking pattern can stall `revalidate`.

## 5. Checker grammar (summary)

The authoritative grammar is [`spec/checkers.md`](../spec/checkers.md). In brief:

- **C3** — `path:<p>` · `symbol:<file>::<name>` · `string:<file>::<literal>` · `regex:<file>::<pattern>`
- **C4** — `pytest:<nodeid>` (a nodeid is `file::test`)
- **C5** — `rowcount:<f>::<op><n>` · `schema:<f>::c1,c2` · `nullrate:<f>::<col>::<op><x>` · `domain:<f>::<col>::{a,b}` · `freshness:<f>::<col>::>= <ISO>` · `snapshot:<f>` · `reconcile:<A>~~<B>` · `shell:<cmd>` (needs explicit `watch` + `expect`)
- **C1** — a span anchor; its `program` is a read-set entry id. **Not** auto-capturable by `verify`.

`watch` auto-derives from the program for C3/C4/C5 (except `shell:`), so you do not set it.
`dorian suggest-data-checks <file>` drafts typed C5 programs to review and paste in.

## 6. `id` scheme & granularity

Short, stable, scope-prefixed ids (`login-ratelimit-added`). One claim per verifiable
assertion, emitted at the moment you state it in your summary. One checker per claim unless
a claim genuinely needs two independent checks. Ids are permanent handles — never renumber.

## 7. What not to claim

Anything you cannot bind to a read-only deterministic check: runtime behavior with no test,
subjective quality, future intentions. Those belong in prose, not a warrant.

## 8. Caveats: C1, C5 shell

- **C1 span claims cannot go through `verify`** (`referenced_paths` raises, exit 2) — they
  need explicit `dorian capture` + `dorian seal`. Do not put C1 in a verify-targeted
  `claims.json`.
- **`C5 shell:<cmd>`** cannot be auto-captured by `verify` (it needs an explicit `watch`):
  `verify` rejects it with exit 2. Use `dorian seal` with an explicit `watch`, or prefer typed
  C5 forms, whose `watch` auto-derives.

## 9. Emit-time self-check

After writing `claims.json`:

1. `dorian verify <artifact> --claims claims.json` — require **exit 0**.
2. `dorian bindings <artifact>` — resolve every flag (`unbacked`, `single-file`,
   `short-literal`, `ambiguous-mention`, `trigger-only-symbol`, `unwatched-mention`) before
   considering the claim sealed. Preview what `verify` will auto-bind first with
   `dorian bind-suggest --claims claims.json` (read-only).

`bindings` is your deterministic false-confidence linter — a strong smell-detector, not a
proof. No model runs at check time, ever.

## 10. Worked example

An agent finishing *"added rate-limiting to `/login`, set the timeout to 30s, covered by a
test"* emits:

```json
{
  "claims": [
    { "id": "login-ratelimit-added", "text": "Rate limiting guards the /login route.",
      "kind": "behavior", "load_bearing": true,
      "checkers": [{ "type": "C3", "program": "symbol:src/api/auth.py::rate_limit" }] },
    { "id": "login-timeout-30s", "text": "The login request timeout is 30 seconds.",
      "kind": "quantity", "load_bearing": true,
      "checkers": [{ "type": "C3", "program": "regex:src/api/config.py::LOGIN_TIMEOUT\\s*=\\s*30\\b" }] },
    { "id": "login-ratelimit-tested", "text": "Rate limiting is covered by a test.",
      "kind": "behavior", "load_bearing": false,
      "checkers": [{ "type": "C4", "program": "pytest:tests/test_auth.py::test_login_rate_limited" }] }
  ]
}
```

```text
$ dorian verify docs/changes/login.md --claims claims.json
sha256:…
verified 3/3 claim(s) against current sources -> docs/changes/login.md.warrant
```

If a later refactor removes `rate_limit`, `dorian revalidate` flips `login-ratelimit-added`
to BROKEN and the warrant to REVOKED (exit 4) — the summary stopped being true, and you
find out.

## 11. Exit codes

| exit | meaning |
|---|---|
| `0` | sealed; every backed claim held against current sources |
| `2` | usage — bad JSON, a C1 or C5 `shell:` claim in `verify`, a referenced file missing, artifact outside the repo |
| `4` | a claim is false (`FAILED_AT_SEAL`) or its checker could not run (`ERRORED_AT_SEAL`); **nothing written** |
| `6` | a referenced file matches a `[tool.dorian.scopes]` restricted glob without `--allow-restricted` |

Treat exit 4 as "your claim is wrong — fix it," not "retry."

---

`--extract` (LLM claim drafting) is **frozen**: it still works but is experimental and not
the recommended path. Emit claims directly, as above.
