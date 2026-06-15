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

_None yet. This file ships empty on purpose: dorian has not yet accumulated real
external catches, and inventing them would violate [VALIDATION_HONESTY.md](VALIDATION_HONESTY.md).
The first honest entry here is worth more than any number in the benchmark docs._
