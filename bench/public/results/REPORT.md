# Public real-repo micro-benchmark — results

These are **candidate benchmark subjects** pinned at frozen commit SHAs. Any numbers below are **reproducible on these frozen SHAs** only; they do not transfer to other repositories and are not a real-world performance claim. The **trigger and truth layers reported separately**: trigger = was the affected claim re-checked; truth = was it BROKEN / VERIFIED / ERRORED. ERRORED (a checker that could not run) is never an alarm.

| repo | sha | license | status | trigger re-checked/skipped | truth broken/trusted/errored |
|---|---|---|---|---|---|
| humanize | `2ddb5903cdc1` | MIT | PASS | 4/0 | 3/1/0 |
| python-dotenv | `36004e0e34be` | BSD-3-Clause | PASS | 4/0 | 3/1/0 |
| tomli | `c5f44690c68c` | MIT | NO_CLAIMS | 0/0 | 0/0/0 |
| bandit | `92ae8b82fb42` | Apache-2.0 | NO_CLAIMS | 0/0 | 0/0/0 |
| jaffle_shop_duckdb | `36bde6cba69d` | Apache-2.0 | NO_CLAIMS | 0/0 | 0/0/0 |

_dorian 1.0.0rc1; binding selects WHEN a claim is re-checked, the checker decides WHETHER it is false; `--deny-exec`/`--deny-shell` are fail-closed policies, not sandboxes._
