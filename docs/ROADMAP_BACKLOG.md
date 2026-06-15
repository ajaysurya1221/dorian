# Roadmap backlog

Structured backlog for dorian. Status values: **DONE** (shipped, tested),
**PARTIAL** (mechanism shipped, scope remains), **TODO** (designed, not built),
**DEFER/HUMAN-REVIEW** (needs maintainer judgment before building). The theme is
fixed: *credibility before expansion, safety before CI convenience, truthful docs
before marketing, deterministic verification before AI automation.*

---

```yaml
- id: deny-exec-mode
  title: Opt-in deny-exec / deny-shell execution policy
  status: DONE
  problem: C4 pytest and C5 shell execute code; .warrant/claims are executable input.
  evidence: src/dorian/policy.py; gated in checkers/base.run_checker; flags on seal/verify/revalidate.
  expected_value: A user can run dorian without granting code execution; fail-closed.
  acceptance_criteria: Blocked C4/C5-shell ERROR (never PASS/FAIL); blocked load-bearing claim does not seal; revalidate folds to ERRORED.
  tests_or_validation: tests/test_deny_exec_policy.py; tests/test_security.py.
  human_review_required: no
  confidence: high

- id: regex-hardening
  title: C3 regex ReDoS timeout (process-isolated match)
  status: DONE
  problem: Catastrophic backtracking within the 500-char cap could stall revalidate (in-process, ignored timeout_s).
  evidence: src/dorian/_regex_worker.py; c3_ref._search_with_timeout honors spec.timeout_s, kills the worker.
  expected_value: A pathological pattern ERRORs (regex_timeout) within the bound instead of stalling.
  acceptance_criteria: safe patterns PASS/FAIL; catastrophic pattern times out quickly; no new core dependency.
  tests_or_validation: tests/test_c3_regex_timeout.py; tests/test_security.py.
  metric: catastrophic (a+)+$ bounded to spec.timeout_s.
  human_review_required: no
  confidence: high

- id: version-and-docs-drift-guards
  title: Version-sync + CLI/README command-surface guards
  status: DONE
  problem: Audit found version drift and README advertising non-existent commands.
  evidence: tests/test_version_sync.py; tests/test_cli_docs_sync.py.
  expected_value: The drift class cannot silently return.
  acceptance_criteria: pyproject==__init__==CLI; every README code `dorian <cmd>` resolves.
  human_review_required: no
  confidence: high

- id: security-docs
  title: SECURITY.md + SECURITY_BOUNDARY.md + Action posture
  status: DONE
  problem: Executable-input boundary and public-fork limitation were not stated in one authoritative place.
  evidence: SECURITY.md; docs/SECURITY_BOUNDARY.md; action deny_exec/deny_shell inputs; action/README update.
  acceptance_criteria: FACT/LIMITATION/SAFE/UNSAFE structure; "not a sandbox"; no public-fork-safe overclaim.
  tests_or_validation: tests/test_action_security_defaults.py.
  human_review_required: no
  confidence: high

- id: validation-honesty-and-templates
  title: Validation-honesty doc, real-catch log, shadow-pilot, benchmark reproducibility
  status: DONE
  problem: Launch credibility needs honest framing and reusable evidence templates, not marketing.
  evidence: docs/VALIDATION_HONESTY.md, REAL_CATCH_LOG.md, SHADOW_PILOT_TEMPLATE.md, BENCHMARK_REPRODUCIBILITY.md.
  acceptance_criteria: trigger vs truth separated; synthetic labeled; nothing fabricated.
  human_review_required: no
  confidence: high

- id: release-and-dependency-hygiene
  title: Release checklist + dependency report + coverage visibility
  status: DONE
  problem: Drift prevention, auditable zero-core-dep posture, coverage exposure.
  evidence: docs/RELEASE_CHECKLIST.md; docs/DEPENDENCIES.md; `make dependency-report`; `make coverage`.
  human_review_required: no
  confidence: high

- id: issue-templates
  title: Issue templates that channel the exact evidence dorian needs
  status: DONE
  evidence: .github/ISSUE_TEMPLATE/{bug_report,false_pass,false_alarm,checker_request,benchmark_submission}.yml + config.yml.
  acceptance_criteria: collect version, command, checker family, executable-context, trusted/untrusted, expected vs actual.
  human_review_required: no
  confidence: high

- id: pypi-trusted-publishing
  title: PyPI Trusted Publishing workflow (manual, OIDC, no token)
  status: PARTIAL
  problem: Source install works; PyPI install reduces friction and signals maturity.
  evidence: .github/workflows/publish.yml (workflow_dispatch only; environment-gated; OIDC).
  remaining: A maintainer must create the PyPI Trusted Publisher + `pypi` GitHub environment, then trigger manually. Nothing publishes automatically.
  human_review_required: yes  # credentials / PyPI project ownership
  confidence: high

- id: public-microbenchmark-execution
  title: Run the public-repo micro-benchmark (frozen SHAs) and publish numbers
  status: PARTIAL
  problem: Strongest external trust step; only the protocol + manifests exist.
  evidence: docs/PUBLIC_BENCHMARK_PROTOCOL.md; bench/public/repos.public.json; bench/public/manifest.example.json.
  remaining: Author per-case manifests, run the harness, publish BENCHMARK_PUBLIC_REPOS.md citing the protocol.
  acceptance_criteria: byte-reproducible numbers, trigger and truth reported separately, scoped claims only.
  human_review_required: no
  confidence: medium

- id: real-catch-log
  title: Accumulate real catches on real work
  status: PARTIAL  # template ships; ledger is honestly empty
  evidence: docs/REAL_CATCH_LOG.md.
  metric: real catches/week; false-alarm rate; week-2 retention.
  human_review_required: no
  confidence: medium

- id: c6-python-signature-checker
  title: AST-based Python signature/default checker (non-executing)
  status: DEFER/HUMAN-REVIEW
  problem: Symbol existence ≠ behavior; a signature/default change can silently invalidate a claim.
  proposed_scope: parse (never import) a module, verify a function/class exists with given params/order/kinds, defaults rendered from AST, optional return/base; watch the source file; works under deny-exec.
  why_deferred: Adds a new checker family — spec/checkers.md + model registry + docs surface. A grammar addition is out of scope for a security-hardening release (credibility before expansion); it deserves its own reviewed PR.
  acceptance_criteria: passes for expected signature; fails on changed default / removed param; no code execution.
  human_review_required: yes  # checker grammar / spec change
  confidence: medium

- id: c7-json-yaml-path-value-checker
  title: JSON/YAML path-value checker (non-executing)
  status: DEFER/HUMAN-REVIEW
  problem: Config/default/schema drift is a high-fit deterministic use case.
  proposed_scope: stdlib-json path-value (existence/equality/type/length/membership); YAML only via the existing optional dep; no shell; watch the data file; works under deny-exec.
  why_deferred: Same as C6 — a checker-grammar addition; ship after the hardening release, on its own.
  human_review_required: yes
  confidence: medium

- id: trusted-base-action-mode
  title: Trusted-base Action mode for public fork PRs
  status: SHIPPED (V1, 1.0.0rc1)
  problem: deny-exec removes code execution but not the self-attested-verdict problem; a real public-fork story needs base-ref checker definitions.
  evidence: implemented — revalidate --checker-source base (src/dorian/revalidate.py), Action checker_trust input (action/action.yml), tests/test_trusted_base.py (10-case exploit matrix); see docs/TRUSTED_BASE_ACTION_DESIGN.md (STATUS: IMPLEMENTED).
  shipped_scope: executes only checker specs resolved from the trusted base ref; PR-added/modified executable checkers never run; missing/tampered base sidecar fails closed; deny-exec composes. Residual (documented, not a sandbox)- a base-approved pytest checker can still execute PR-head code, so pair with deny-exec for untrusted forks.
  confidence: high

- id: binding-beyond-python-symbols
  title: Bind routes / configs / schemas / non-Python indices
  status: TODO
  problem: The project's own admitted false-confidence ceiling: a claim can miss the file that defines its fact.
  human_review_required: no
  confidence: medium

- id: sbom-on-release
  title: Generate an SBOM (e.g. CycloneDX) on release
  status: TODO
  problem: Zero-core-dep posture is a strength; make it machine-auditable for enterprise compliance.
  human_review_required: no
  confidence: low
```

---

## Do NOT build (explicit non-goals)

These are out of scope by design. Re-opening any of them requires a deliberate
decision, not drift.

- **SaaS dashboard / hosted control plane.** dorian is local-first; no server.
- **LLM judge at check time.** Verdicts stay deterministic and token-free — the
  obsolescence moat. Models may *propose* claims/checkers outside dorian; they
  never *decide* a verdict.
- **Generic AI code-review bot.** dorian verifies stated claims against source,
  not whether code is "good".
- **Default extraction workflow.** `--extract` stays frozen/experimental; agents
  emit claims or humans write them.
- **Generic eval / observability platform.** Different buyer, different shape,
  discards the differentiator.
- **Plugin marketplace.** No plugin system.
- **Automatic merge / auto-publish.** Publishing is manual + OIDC + gated.
- **Broad multi-language semantics before evidence.** Earn one language's
  truth-layer credibility before widening.
