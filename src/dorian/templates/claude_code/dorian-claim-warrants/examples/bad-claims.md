# Bad claims — do NOT warrant these

Dorian warrants *specific, checkable, falsifiable* facts. These do not qualify;
leave them as prose in the change note. A claim earns a warrant only when a
deterministic checker can prove it false later.

| Don't warrant | Why | What to do instead |
|---|---|---|
| "The code is cleaner / more maintainable." | Opinion. No checker can falsify it. | Leave as prose. |
| "This is ~2x faster." | Performance claim with no falsifying check in the claim. | Leave as prose, or back a *specific* asserted behavior with a `C4 pytest:` test you trust. |
| "More secure now." | No deterministic check; security is not a `symbol:` exists. | Leave as prose; rely on SAST/review. |
| "Refactored the auth module." | Vague; nothing to falsify. | Warrant the *specific* surviving facts: a `py-signature:` or `py-const:`. |
| "Updated the docs." | No anchor. | If a doc must contain a specific string, anchor it: `string:`/`regex:` on that file. |
| "All callers were updated." | Quantity over an open set; existence can't prove "all". | Only warrant if a deterministic check covers it (often it can't) — otherwise prose. |
| A **behavior** claim backed only by `symbol:` (exists). | Existence ≠ behavior. `--strength-gate=fail` refuses it. | Use `C4 pytest:` for behavior, or downgrade the claim's `kind` to `reference`. |
| A **quantity** claim ("value is N") backed only by `path:`/`symbol:`. | Existence can't pin a value. | Use `py-const:` / `config-value:` / anchored `regex:`. |
| `string:` on a short (<6 char) or reformat-fragile literal. | Brittle; whitespace/format churn breaks it spuriously. | Anchor both key and value with `regex:`, or use `config-value:`/`py-const:`. |
| `pytest:` pointing at a test that does not exist yet, or one you haven't run. | The checker ERRORs (fail-closed); never fabricate a node. | Only cite a real, safe, known-passing test node. |

The honest move is to **exclude** the un-checkable statements explicitly in the
change note ("Non-checkable claims intentionally excluded"). Dorian verifies only
what someone wrote down; it cannot catch a lie of omission, and it never claims to
verify the whole summary.
