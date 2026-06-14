# Example: dorian + Claude Code

A complete, runnable example of the agent-in, checker-out loop. The files here are a tiny
self-contained "repo": treat this directory as the repo root.

| file | role |
|---|---|
| [`app.py`](app.py) | the code the agent changed |
| [`change-note.md`](change-note.md) | the artifact (the agent's account of the change) |
| [`claims.json`](claims.json) | the checkable claims, each bound to a deterministic checker |
| [`settings.example.json`](settings.example.json) | a review-first Claude Code `settings.json` permissions sample |
| [`settings.trusted-local.example.json`](settings.trusted-local.example.json) | optional trusted-local permissions sample |

## Run it (leaves your real repo untouched)

Copy the three core files into a throwaway git repo so the sealed `.warrant` lands there, not in
your working tree:

```bash
tmp=$(mktemp -d) && cp app.py change-note.md claims.json "$tmp" && cd "$tmp" && git init -q
git add -A && git commit -q -m "login handler + note"

dorian verify change-note.md --claims claims.json
# -> verified 2/2 claim(s) against current sources -> change-note.md.warrant   (exit 0)

# now a refactor renames the function and drops the timeout — the note never changes:
printf 'LOGIN_TIMEOUT = 10\n\n\ndef signin(request):\n    return {"ok": True}\n' > app.py
dorian revalidate --since HEAD
# -> login-handler-added BROKEN; login-timeout-30s BROKEN; WARRANTED -> REVOKED   (exit 4)
```

`change-note.md` still reads perfectly and `git`/CI stay quiet — but the warrant flipped to
REVOKED, naming the exact claims that stopped being true.

## The paste-ready agent prompt

See [`../../docs/USE_WITH_CLAUDE_CODE.md`](../../docs/USE_WITH_CLAUDE_CODE.md) for the prompt you
give your agent to produce a `change-note.md` + `claims.json` like these, the checker-choice
guidance, and the safety boundaries.

## The settings sample

`settings.example.json` is a snippet to merge into your project's `.claude/settings.json`. It
pre-allows only inspection-oriented dorian commands (`status`, `bindings`, `bind-suggest`) so the
agent can inspect the repo without executing claim checkers. It deliberately does **not** auto-allow
`dorian verify`, `dorian revalidate`, `dorian seal --extract`, or arbitrary shell — an agent-emitted
`claims.json` is executable input (C4/C5 `shell:` run code), so checker execution stays under normal
review by default.

`settings.trusted-local.example.json` is a separate opt-in for a faster local loop. Use it only when
you trust the repo and review agent-emitted `claims.json` before execution; it may pre-allow
`verify`/`revalidate`, but still does not pre-allow `seal`, `--extract`, or arbitrary shell.
