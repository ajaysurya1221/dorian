# VWP checker grammars

The user-facing reference for the `program` grammar of every checker type a
claim's `checkers` list may carry (`src/dorian/model.py` `CheckerSpec`; JSON
shape in `warrant.schema.json`). Checkers are read-only and deterministic.

**Verdict discipline (load-bearing):** FAIL means *the sources no longer
support the claim*; ERROR means *the checker could not run* (bad program,
missing engine, timeout, broken test infrastructure). ERROR never folds a
warrant toward DEGRADED/REVOKED and never reads as staleness. At seal time
both FAIL and ERROR refuse the seal — a warrant is born verifiable.

**Watch derivation:** a checker sealed without an explicit `watch` list gets
one derived from its program (the rules per type below). `dorian revalidate`
re-checks a claim only when a changed path matches a watch path/glob or a
supports-bound read-set uri, so the watch is the claim's binding.

## C1 — span anchor

```
<read-set-entry-id>            e.g. rs-0
```

The program is the id of a read-set entry the claim also lists in `supports`.
PASS when the entry's (span of the) LF-normalized content is hash-identical at
its rename-resolved location, or found verbatim elsewhere in the file
(`anchor_moved`, a relocation, not an alarm); `--enable-c2lite` adds a fuzzy
(>= 0.90) relocation match. Derived watch: the support entry's uri.

## C3 — referential

```
path:<repo-relative>           PASS iff the file or directory exists
symbol:<file>::<name>          PASS iff \b(def|class)\s+<name>\b matches the file
string:<file>::<literal>       PASS iff the literal substring is present
regex:<file>::<pattern>        PASS iff re.search(pattern, text, re.MULTILINE)
                               hits the LF-normalized file text
```

The operand of `string:`/`regex:` may itself contain `:`; only the prefix and
file are split off. `regex:` is the shape-tolerant form — prefer it over
`string:` for facts that must survive reformatting (`TIMEOUT\s*=\s*30` matches
both `TIMEOUT = 30` and `TIMEOUT=30`). When a `string:` check FAILs but a line
nearly matches, the detail carries a near-miss hint (line number and
similarity ratio only, never file content) pointing at `regex:`.

Regex DoS: `regex:` patterns are length-bounded (500 chars) and compile-guarded,
AND the match runs in a spawned worker process killed at the checker's
`timeout_s` (default 30s). A pathological nested-quantifier pattern that triggers
catastrophic backtracking (e.g. `(a+)+$`) is terminated when the timeout elapses
and reported as ERROR(`regex_timeout`) — never a silent stall and never a
PASS/FAIL. The process
boundary is what makes the timeout enforceable (a thread or in-process signal
cannot interrupt a C-level `re.search()`). Prefer literal anchors with bounded
flexible gaps anyway; the timeout is a backstop, not a license, and it adds a
per-check process spawn (~50-150ms, scaling with the number of `regex:` checks)
to `regex:` checks only. Derived watch: the referenced file (the `path:` operand,
or `<file>`).

## C4 — test binding

```
pytest:<nodeid>                e.g. pytest:tests/test_auth.py::test_rs256
```

Runs `python -m pytest <nodeid>` (PATH interpreter, stripped env, repo cwd,
`timeout_s`). Exit mapping: 0 PASS; 1 FAIL `test_failing`; 5 FAIL `test_gone`;
4 FAIL `test_gone` only on the nodeid-gone stderr signatures ("ERROR: file or
directory not found" / "ERROR: not found:") — any other exit 4 (broken
conftest, bad ini/plugin, unimportable target file) is ERROR, as are exits
2/3, timeouts, spawn failures, and a PATH python lacking pytest. Derived
watch: the nodeid's file part. The file part resolves through the rename log,
so a renamed test file is not "gone".

## C5 — data reconciliation

```
rowcount:<path>::<op><int>              schema:<path>::col1,col2,...
nullrate:<path>::<col>::<op><float>     domain:<path>::<col>::{v1,v2,...}
freshness:<path>::<col>::>= <ISO-date>  snapshot:<path>
reconcile:<sideA>~~<sideB>              shell:<command>
```

Typed forms read `.csv` (stdlib) and `.parquet` (optional duckdb extra);
`reconcile` sides are `csv:<path>` (row count) or `sqlite:<db>::<SELECT ...>`
(read-only authorizer; the two sides must agree). `<op>` is one of
`== != >= <= > <`. nullrate/domain/freshness FAIL with `no_rows` on a zero-row
dataset (an empty dataset cannot support a data claim). `snapshot:<path>`
hashes the whole file against the supports-bound read-set entry for that path;
seal auto-binds the entry when the read-set has a whole-file entry for it.
`shell:` is an opaque command judged by `expect` (`exit:0` | `regex:<re>` |
`eq:<literal>`) and is the one checker that REQUIRES an explicit `watch` (the
command is opaque, so the data dependency cannot be derived). Derived watch
for the typed forms: the program's data path(s).

`dorian suggest-data-checks <path>` emits born-verifiable C5 suggestions in
exactly these grammars, for human review and pasting into claims.json.
