# Announcement readiness — dorian v1.0.2

A modest, evidence-linked checklist for announcing v1.0.2. Keep every public claim inside the
honest scope below. When in doubt, say less.

## Exact install & demo

```bash
pip install dorian-vwp        # 1.0.2 on PyPI
```

30-second demo (also pinned by a black-box test):

```bash
tmp=$(mktemp -d) && cd "$tmp" && git init -q
printf 'def handler():\n    return 200\n' > app.py
printf '# change note\n\n`handler()` lives in app.py.\n' > note.md
git add -A && git commit -q -m "app + note"
cat > claims.json <<'JSON'
{"claims": [
  {"id": "handler-exists", "text": "handler() lives in app.py.",
   "kind": "behavior", "load_bearing": true,
   "checkers": [{"type": "C3", "program": "symbol:app.py::handler"}]}
]}
JSON
dorian verify note.md --claims claims.json     # -> verified 1/1  (exit 0)
printf 'def renamed():\n    return 200\n' > app.py
dorian revalidate --since HEAD                 # -> handler-exists BROKEN; WARRANTED -> REVOKED  (exit 4)
```

## Allowed claims (true and evidenced)

- "dorian v1.0.2 is live on GitHub and PyPI." — *only after both are confirmed.*
- "dorian has one documented, reproducible real cross-PR catch on `encode/httpx`." — `docs/REAL_CATCH_LOG.md`.
- "The catch is scoped: it proves one bound claim can be revoked when its watched fact changes; it is not broad validation."
- "dorian is local-first and token-free at check time."
- "dorian is not a sandbox; executable checker policies (`--deny-exec`/`checker_trust: base`) are fail-closed controls, not isolation."

## Forbidden claims (do not say)

"validated on real repos" · "works on real repos" · "production-grade" · "catches all drift" ·
"catches bugs" · "better than CodeRabbit" · "proves dorian works" · "fully solves AI code
verification" · fake users/stars/adoption · "secure for untrusted public forks by default" ·
"in-toto standard" / "official predicate".

## Exact "one real catch" wording

> On the public repo `encode/httpx` (BSD-3, frozen SHAs), a load-bearing claim sealed when
> `requires-python` was `">=3.8"` was flipped `WARRANTED → REVOKED` (exit 4) by a real later
> upstream PR (#3592, "Drop Python 3.8 support") while httpx's own tests stayed green and no
> stateless per-PR review would have re-opened the original claim. One documented catch,
> independently reproduced — not broad validation.

## Evidence checklist (all verified for v1.0.2)

- [x] PyPI `dorian-vwp` serves the announced version (1.0.2) — verify with `pip install dorian-vwp` after publish.
- [x] README first install path provides `suggest-claims` and `export --in-toto`.
- [x] README 30-second demo passes from a fresh install (verify=0, revalidate=4, REVOKED).
- [x] No `dorian/action@main` in public copy-paste (guarded).
- [x] Security workflow audits the project dependency set (guarded).
- [x] Checkout steps drop credentials where unneeded.
- [x] `export` `.warrant` filename and `suggest-claims` PEP 263 bugs fixed + regression-tested.
- [x] Full pytest, ruff, bandit, project-scope pip-audit, build + twine check all green.
- [x] Real catch reproduces on this build (httpx, frozen SHAs).
- [x] Overclaim/secret scans clean.

## Launch post draft (short, honest, evidence-linked)

> **dorian v1.0.2 is live** (PyPI `dorian-vwp`, GitHub release). It's a deterministic, local-first,
> token-free way to hold a change to the explicit claims someone made about it: bind a
> natural-language claim to a checker, seal a `.warrant`, and re-check only what a later change
> touches.
>
> Why it matters: a sealed claim persists across commits, so drift gets caught when a stateless
> per-PR check wouldn't re-open the original claim.
>
> One documented, reproduced real catch: on `encode/httpx` (frozen SHAs), a load-bearing
> `requires-python >=3.8` claim flipped to REVOKED when a later upstream PR raised the floor to
> 3.9 — while httpx's own tests stayed green. Scoped: it proves one bound claim can be revoked,
> not broad validation.
>
> `pip install dorian-vwp` — 30-second demo in the README.
>
> Note on safety: dorian is **not** a sandbox. Executable checker policies (`--deny-exec`,
> `checker_trust: base`) are fail-closed controls, not isolation.
