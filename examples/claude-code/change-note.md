# Change note — login handler

Added a `login_handler` to `app.py` and set the login request timeout to **30 seconds**.

The checkable claims behind this note are pinned in [`claims.json`](claims.json); running
`dorian verify change-note.md --claims claims.json` seals them into `change-note.md.warrant`,
and `dorian revalidate` re-checks them whenever `app.py` changes.
