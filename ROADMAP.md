# ADE Roadmap

## Phase 0 — Foundation ✅
Durable state model, safety policy, repository contract, deterministic tests.

## Phase 1 — Jules Provider ✅
REST adapter, source discovery, authentication and quota error handling, smoke test.

## Phase 2 — GitHub Validation ✅
CI, result normalization, PR validation contract.

## Phase 3 — One Autonomous Cycle ✅
Goal/task input -> Jules session -> PR -> CI -> persisted result.

## Phase 4 — Continuous Goal Loop ✅
Automatically select the next bounded task after a successful cycle.

Evidence: ADE completed and merged multiple bounded Jules tasks through the cloud loop without requiring a human "next" command between autonomous tasks.

## Phase 5 — Repair Loop ✅
Classify failures, choose bounded retry/replan/pause/human-wait dispositions, integrate repair into runtime execution, and prove a deterministic fail -> retry -> success path.

Evidence: the bounded repair runtime, operational Jules integration, import-regression guard, and deterministic repair probe are merged and CI-validated.

## Phase 6 — Pause / Resume ✅
Quota-aware and crash-safe continuation.

Current build order:
1. validated checkpoint model
2. atomic checkpoint persistence
3. deterministic resume policy
4. resumable provider-session primitives
5. checkpoint lifecycle transitions
6. checkpoint-aware runtime continuation
7. cloud-only quota-resume proof

Evidence: checkpoint persistence, existing-session continuation, deterministic crash/restart CI proof, and a cloud-only due-quota resume proof all pass without local compute.

## Phase 7 — Human Decision Queue ✅
Ask only for decisions that exceed configured autonomy thresholds.

Evidence: immutable decision lifecycle models, atomic persistence, a fixed safety boundary for high-risk actions, idempotent HUMAN_WAIT handling, explicit human resolution, and an end-to-end offline lifecycle probe all pass under CI.

## Phase 8 — Mission Control ✅
Mobile-first project health, decisions, preview, and activity feed.

Evidence: safe repository-backed snapshot aggregation, mobile-first static HTML, deterministic artifact build, read-only GitHub Actions delivery, durable activity ledger, allowlisted latest-preview metadata, trusted PR observability updates, and end-to-end leakage/security checks all pass under CI.

## Phase 9 — Task DAG ✅
Continue independent work while another task waits for human input.

Build order: immutable DAG model -> atomic store + pure runnable scheduler -> validated transitions -> HUMAN_WAIT branch-bypass proof -> trusted controller integration behind FIFO fallback -> trusted dispatch proof.\n\nEvidence: graph invariants, atomic persistence, dependency-safe scheduling, HUMAN_WAIT isolation, trusted-controller integration, FIFO fallback, and the real trusted dispatch path are all CI-proven.

## Phase 10 — Multi-provider Routing ✅
Add additional hosted/local providers behind the same interface.

## Phase 11 — Production Project Pilot ✅
Run ADE against a real project with explicit acceptance criteria.

Build order: immutable pilot contract -> atomic contract store -> read-only preflight -> contract-bound human activation -> pure dry-run enforcement -> one bounded production PR -> final evidence record.

Evidence: the original pilot was truthfully recorded as baseline-blocked, the target baseline was repaired independently, and successor pilot `one-minute-cli-command-guard-002` produced reviewable target PR #3 from the newly frozen baseline. Its two-file scope, base SHA, target CI, deterministic compile acceptance, provider identity, and rollback boundary are recorded in `.autodev/pilot/final-evidence.json`. The target production PR remains intentionally unmerged.


## Phase 12 — Production Hardening ✅
Make autonomous execution safe under duplicate dispatches, transient infrastructure failures, stale state, and interrupted controllers.

Build order: execution lease/idempotency boundary -> stale-lease recovery -> transient GitHub/provider retry classification -> duplicate-dispatch proof -> interruption/timeout fault-injection proof -> production hardening evidence.

Completed: trusted execution now has a provider-agnostic persisted lease, duplicate-dispatch suppression before provider session creation, deterministic stale-lease recovery, bounded transient GitHub retry, and CI fault-injection proofs for interruption, timeout, stale checkpoint isolation, and delayed-controller overlap.


## Phase 13 — Long-running Autonomous Development
Prove that ADE can own a bounded multi-task campaign rather than only one coding cycle at a time.

Build order: durable campaign identity/progress -> campaign-aware DAG advancement -> restart-safe continuation -> bounded multi-task simulation -> real multi-PR campaign proof -> completion evidence.

Completed: durable campaigns, restart-safe continuation, multi-task execution, and real multi-PR evidence are Production Graduated in v1.0.


## Phase 14 — Mission Control / Observability ✅
Campaign lifecycle, recovery, current task, and operator-visible status are reconciled into a safe read model and artifact.

## Phase 15 — Autonomous Recovery ✅
Bounded recovery classifies failures and performs trusted repair/retry/rebase/replan without bypassing scope, provenance, lease, CI, or human-decision gates.

## Phase 16 — Goal → Plan → Execution ✅
High-level goals can be converted from bounded work items into validated DevelopmentPlans, accepted with tamper-evident fingerprints, compiled into Campaign/Task DAG state, and executed through the trusted controller.

## Phase 17 — Production Graduation ✅
The three-task production graduation Campaign completed through PR/CI/trusted merge with no failed tasks, and the final deterministic proof suite is green.

## ADE v1.1 — Zero-Touch Start ✅
Removed the remaining initial GitHub Actions click while preserving the existing trusted controller, lease, recovery, HUMAN_WAIT, and evidence boundaries.

Evidence: real Campaign `v1.1-zero-touch-proof-001` was activated by AcceptedPlan merge, Zero-Touch Start run `36401818363` dispatched Task 1 from a push trigger, PR #116 and PR #117 both passed CI and merged through the trusted gate, Task 2 was automatically dispatched, and terminal structured evidence is persisted under `.autodev/campaign-evidence/v1.1-zero-touch-proof-001.json`.

## ADE v1.2 — Autonomous Planner ✅
Generate bounded DevelopmentPlans from a high-level Goal using repository-aware AI planning, then require deterministic trusted validation before AcceptedPlan/Campaign creation. AI planner output is never directly executable.

Graduated: real proof `v1.2-external-goal-proof-006` completed high-level Goal -> Jules planning-only proposal -> trusted validation -> AcceptedPlan -> repository_dispatch Zero-Touch -> external Task 1 PR #11 / CI / trusted merge -> automatic Task 2 -> PR #12 / CI / trusted merge -> terminal Campaign COMPLETED with failed=0 and no manual Campaign progression. The target baseline and both proof PRs passed runtime source hygiene plus clean production-import smoke. Immutable evidence is stored at `.autodev/campaign-evidence/v1.2-autonomous-planner-proof-006.json`, and the dedicated v1.2 Graduation audit is mandatory in CI.

## ADE v1.3 — Repository Intelligence ✅
Give the Autonomous Planner a trusted, bounded model of the target repository so plans are grounded in real files, architecture, tests, and dependencies rather than path guesses.

Build order:
1. deterministic structure snapshot bound to target repository/base/source SHA
2. bounded planner context using path metadata only
3. trusted evidence + state fingerprints
4. bounded content/symbol summaries
5. dependency and test/source relationship graph
6. deterministic change-impact analysis
7. existing-vs-new-file validation at the planner boundary
8. real external repository proof and v1.3 graduation audit

Slice 001 complete: Git tree metadata is read through the trusted controller, normalized into a deterministic RepositorySnapshot, filtered to trusted writable roots for planner context, and fingerprinted into activation evidence.

Slice 002 complete: trusted bounded UTF-8 reads are limited to deterministic Python candidates; raw source is parsed locally with Python AST and discarded. Planner/evidence receive only module names, top-level class/function names, import-module names, parse status, byte counts, and content/blob fingerprints. String constants, docstrings, imported symbol names, and raw source text are not persisted into Repository Intelligence context.

Slice 003 complete: internal Python import edges are resolved against the bounded content summary, relative imports are normalized against package context, external imports are ignored, and test-to-source relationships are derived from import edges with an unambiguous filename fallback. The bounded relationship graph is fingerprinted and supplied to planner context/evidence without changing write authority.

Slice 004 complete: trusted AcceptedPlan allowed_paths are treated as proposed change roots and analyzed against the repository relationship graph. Reverse imports are traversed with bounded deterministic breadth-first search, likely affected tests are surfaced through test/source links, and the resulting impact analysis is fingerprinted into Repository Intelligence evidence and project state. Impact findings are advisory only and never expand execution scope.

Slice 005 complete: the planner task schema carries explicit `new_paths`; live trusted validation compares every allowed path against the full immutable repository snapshot, rejects unknown paths unless they are explicitly declared new, rejects existing paths falsely declared new, and requires new_paths to remain inside allowed_paths. Legacy deterministic v1.2 validation remains compatible when no repository snapshot is supplied.

Graduated: real proof `v1.3-repository-intelligence-proof-001` completed High-level Goal -> trusted Repository Intelligence snapshot/content/relationship/impact context -> Jules planning-only proposal -> trusted existing-path grounding -> automatic Zero-Touch -> external PR #13 / CI / trusted merge -> automatic Task 2 -> PR #14 / CI / trusted merge -> terminal Campaign COMPLETED with failed=0 and no manual Campaign progression. Immutable evidence is stored at `.autodev/campaign-evidence/v1.3-repository-intelligence-proof-001.json`, and the dedicated v1.3 Graduation audit is mandatory in CI.

## ADE v1.4 — Runtime / Deployment Verification ✅
Verify that merged work actually runs in the intended environment instead of treating CI success as proof of runtime or deployment success.

Build order:
1. immutable source-SHA-bound Runtime Verification Contract
2. trusted probe registry with fixed controller-owned implementations
3. automatic post-merge verification trigger and durable receipt
4. bounded runtime probe execution with timeout/retry policy
5. environment/deployment target adapters and freshness/provenance checks
6. recovery/HUMAN_WAIT integration for runtime failures
7. real external repository proof and v1.4 graduation audit

Slice 001 complete: ADE now has a deterministic RuntimeVerificationContract and RuntimeProbeResult model bound to target repository, exact source SHA, environment, trusted probe IDs, timeout, and retry budgets. The evaluator is fail-closed for unknown/duplicate/stale/over-budget evidence, reports PENDING while required evidence is incomplete, and can report VERIFIED only when every required trusted probe passes. The contract intentionally carries no executable command, URL, header, credential, or secret payload; trusted probe implementation mapping is deferred to Slice 002.

Slice 002 complete: TrustedRuntimeProbeRegistry binds safe probe IDs to controller-owned callable implementations plus stable implementation IDs. Contracts are rejected before execution if any required probe is unregistered; runners cannot choose probe identity, source SHA, or attempt metadata because the registry wraps observations into trusted RuntimeProbeResult evidence. Duplicate registrations, out-of-contract probes, over-budget attempts, invalid observations, and runner exceptions fail closed or normalize to secret-free ERROR evidence.


Slice 003 complete: the trusted Remote PR Monitor now reads the exact target `merge_commit_sha` after a trusted merge, creates a source-SHA-bound RuntimeVerificationContract, persists per-task durable contract/receipt evidence, dispatches the dedicated runtime-verification workflow, and records the ARMED -> DISPATCHED transition before advancing the existing queue. Interrupted ARMED receipts are retryable while DISPATCHED/terminal receipts suppress duplicate dispatch. Pre-v1.4 Campaigns retain their previous behavior.


Slice 004 complete: runtime probes now execute in isolated child processes with contract-bound hard timeouts and bounded ERROR retries. The child environment is reduced to a small safe allowlist, repository-write/credential/network/deployment authority flags are fixed false by the trusted registry, and expired probe processes are terminated. PASS/FAIL/SKIPPED are terminal per attempt sequence while only ERROR is retried. Durable reports and VERIFIED/FAILED receipt transitions are source-SHA and contract-fingerprint bound.


Slice 005 complete: TrustedRuntimeTargetRegistry distinguishes repository, preview, staging, and production runtime targets. Repository runtime is bound directly to the exact trusted merge SHA and explicitly carries no deployment identity. Preview/staging/production require explicit source-SHA-bound deployment IDs from controller-owned adapters, enforce freshness/future-skew limits, and fail closed when deployment observation is unavailable, stale, or source-mismatched. CI/workflow status is not part of target evidence and cannot be used as deployment-success proof.

Slice 006 complete: runtime/deployment verification failures are fail-closed into durable recovery evidence and HUMAN_WAIT. A failed runtime receipt is promoted to HUMAN_WAIT, the project current task is restored to the failed verification task, and a previously COMPLETED Campaign is reconciled to HUMAN_WAIT so runtime failure cannot coexist with silent Campaign success. Raw failure detail is represented in state by a bounded SHA-256 fingerprint, and automatic task re-execution is intentionally not granted until a future trusted DAG rollback design exists.

Pre-graduation runtime adapter complete: repository-runtime verification now prepares a temporary workspace from the exact trusted merge SHA, validates a bounded archive, permits only simple PyPI production dependency specifications, installs dependencies into an isolated credential-free venv using binary wheels, and runs real offline CLI and production-import probes. Probe stdout/stderr and raw runtime output are discarded; only bounded status/detail codes and fingerprints are persisted. The entire temporary checkout/venv is deleted after execution, including failure paths.


Proof002 retirement: proof `v1.4-runtime-verification-proof-002` reached external PR #16, trusted merge `2f357413b318105cbb030cf2c6bbe474689b0e46`, and repository runtime verification `VERIFIED` with both trusted probes passing. It is nevertheless excluded from graduation because controller maintenance PR #170's failed CI run `36689393254` was incorrectly attributed by PR Gate run `36689431302` to active external task `v14rv2-001`, which dispatched Jules cycle `36689451958`. The runtime result is preserved as genuine runtime evidence, but the execution provenance is not clean enough for graduation. PR #173 (`e50e558e820964ea1e1882685da46b90ed472265`) fixed CI-recovery provenance by requiring controller-target binding, checkpoint task binding, and exact provider-session binding. Graduation is retargeted to clean proof003; proof002 is not rewritten as success.

Proof002 scheduler hardening: while `v14rv2-001` was safely `PAUSED_QUOTA`, the last pre-due Resume Watch run (run `36674811488`) completed successfully at 2026-09-30 05:44 UTC and correctly reported WAIT for the 06:56 UTC resume boundary. No scheduled Resume Watch run was delivered between that boundary and the 2026-09-30 08:20 UTC observation, so the campaign remained safely paused with failed=0 and no provider session. This is recorded as a scheduler-delivery gap, not as task or runtime-verification success. Resume Watch is hardened to stagger cron delivery away from quarter-hour boundaries and to accept trusted repository-dispatch plus controller-code push wakeups while retaining the same checkpoint, execution-lease, and HUMAN_WAIT gates.

Proof001 retirement: the first real v1.4 proof completed Goal -> Planner -> Zero-Touch -> external PR #15 -> CI/trusted merge, then runtime verification entered fail-closed HUMAN_WAIT before durable target/report evidence was persisted. The failed receipt and recovery fingerprint are preserved and proof001 is excluded from graduation. PR #167 hardened trusted JSON evidence writes so unrelated main-branch movement can be retried while same-path concurrent mutations still fail closed. Graduation is retargeted to proof002; proof001 is not rewritten as success.

Graduated: clean proof `v1.4-runtime-verification-proof-003` completed high-level Goal -> Jules planning-only proposal -> trusted validation -> automatic Zero-Touch -> Jules task `v14rv3-001` -> external PR #17 -> target CI run `36691307632` -> trusted remote gate run `36691380061` -> exact merge SHA `d3073a165a902b58cb2dfee9b16736fc7eaa43d9` -> Runtime Verification run `36691433088`. Both trusted probes (`offline-cli-smoke`, `production-import-smoke`) passed on attempt 1; the durable receipt is `VERIFIED`, Campaign `v1.4-runtime-verification-campaign-003` is COMPLETED, Project state is READY with failed=0, and no recovery/HUMAN_WAIT or unrelated controller-CI recovery occurred during the active proof. Immutable graduation evidence is stored at `.autodev/campaign-evidence/v1.4-runtime-verification-proof-003.json`. The dedicated v1.4 Graduation audit is mandatory in CI. Proof001 and proof002 remain preserved as non-graduation evidence and are not rewritten as successes.

## ADE v1.5 — Development Memory 🚧
Give ADE a durable, trusted memory of verified decisions, failures, remediations, and outcomes so later planning can reuse evidence instead of rediscovering the same lessons. Memory is advisory data only: it never becomes executable authority and never weakens AcceptedPlan validation, path scope, Acceptance, lease, CI, Runtime Verification, or HUMAN_WAIT.

Build order:
1. immutable evidence-bound Development Memory record + deterministic ledger
2. trusted extraction from structured Campaign/recovery/runtime/human-decision evidence
3. conflict, supersession, and staleness handling
4. repository-aware bounded retrieval/ranking
5. planner context integration behind existing deterministic validation
6. outcome feedback from trusted runtime/recovery evidence
7. real cross-task/external-repository proof and v1.5 graduation audit

Slice 001 complete: `DevelopmentMemoryRecord` requires repository/source-SHA binding, trusted `.autodev/` evidence paths, SHA-256 evidence fingerprints, bounded fact text, and fixed memory kinds. `DevelopmentMemoryLedger` is immutable, duplicate-safe, order-deterministic, and fingerprinted. Planner-facing memory context is repository-filtered, bounded by record and character budgets, explicitly marked `advisory-data-only`, and carries no execution/scope/Acceptance authority. Secret-like markers, URLs, unsafe evidence paths, malformed SHAs/IDs, and control characters fail closed. The dedicated Development Memory proof is required in CI.

Slice 002 complete: trusted extraction accepts only structured controller evidence. Campaign memory requires terminal COMPLETED/READY with zero failed tasks and exact merge SHA; Runtime memory additionally requires a VERIFIED receipt/report, exact source binding across contract/receipt/report/workspace, every required probe PASS, and no recovery/HUMAN_WAIT. Recovery memory is generated only from validated RecoveryRecord failure/action enums. Human-decision memory is generated only from a RESOLVED DecisionRecord with an explicit selected_option; free-text-only responses are ineligible. All memory statements use controller-owned fixed templates, so provider prose, raw logs, decision context, questions, and free-form rationale are never promoted into authoritative-looking memory text. Deterministic evidence fingerprints and memory IDs make repeated extraction stable.

Slice 003 complete: Development Memory now has a deterministic fail-closed resolution layer before reuse. VERIFIED_OUTCOME records are CURRENT only when their source SHA matches the trusted current repository SHA; older verified outcomes become STALE and are excluded from the eligible ledger. Trusted supersession links explicitly retire prior memory, reject missing/cross-repository/multi-successor references, and reject cycles. Historical DECISION/FAILURE/REMEDIATION lessons remain distinguishable from current facts. Multiple non-superseded current verified memories with the same repository/kind/tag subject and differing statements are marked CONFLICTED and excluded rather than silently choosing one. Missing current-source bindings also fail closed.

Slice 004 complete: eligible memory is retrieved with deterministic metadata-only ranking. Queries contain no free-text prompt surface: repository, exact current source SHA, trusted tags, optional task/campaign IDs, and a bounded result count are the only selectors. Retrieval refuses a query whose current SHA differs from the resolution snapshot, always prioritizes CURRENT source-bound verified facts, and returns HISTORICAL lessons only when tags/task/campaign provide an explicit relevance signal. Repository mismatches and STALE/SUPERSEDED/CONFLICTED records never enter results. Ranking is stable by numeric score then memory ID, and retrieved planner-format context preserves the advisory-only/no-scope-expansion/no-Acceptance-override boundary.

Slice 005 complete: the live Autonomous Planner can now receive Development Memory only through a typed `DevelopmentMemoryPlannerContext` whose authority flags must remain advisory-only. The trusted controller derives planner memory from the clean v1.4 graduation evidence, requires the evidence target to match the planning target, resolves it against the exact Repository Intelligence source SHA, and retrieves only eligible current evidence. If the target repository advances, the old verified memories become STALE and the planner receives an empty memory record set rather than stale facts. Memory JSON is appended to the untrusted planner prompt explicitly as data, never between the Goal and trusted writable-root boundary. `validate_planner_proposal`, AcceptedPlan construction, path/new-path validation, human-only boundaries, task budgets, and acceptance validation are unchanged. Planner evidence and ProjectState persist only bounded memory source/resolution/retrieval/context fingerprints and record counts. Deterministic proof confirms that the same proposal produces the same AcceptedPlan fingerprint with or without memory and that protected paths remain rejected even when memory is present.

Slice 006 complete: Development Memory now has a durable `.autodev/development-memory.json` store with strict round-trip validation, ledger fingerprint verification, a 500-record trusted budget, idempotent record merge, and fail-closed same-ID/different-content collision handling. Runtime Verification produces a fixed-template VERIFIED_OUTCOME memory only after the stored report is re-evaluated against the exact trusted contract and every required probe still yields VERIFIED. Runtime HUMAN_WAIT/recovery can persist structured recovery memory from RecoveryRecord enums. Runtime feedback writes are advisory side effects: a memory-store write failure is converted to a bounded error type/fingerprint and cannot rewrite a genuine runtime VERIFIED/HUMAN_WAIT disposition. Replayed runtime verification can retry an omitted memory write, while an already-recorded memory is UNCHANGED and does not duplicate. The live planner prefers the durable store when it contains memory for the target repository and falls back to the clean v1.4 evidence only until the first durable feedback record exists; current-SHA resolution still excludes stale verified facts.
Graduation hardening: v1.5 uses a two-stage real proof. Proof001 is the bootstrap proof: reuse clean v1.4 evidence during planning, complete a real external task, pass exact-SHA Runtime Verification, and append the verified outcome into the durable Development Memory store. Proof002 is the graduation proof: a later Autonomous Planner run must read from `.autodev/development-memory.json` itself, persist the exact reused memory IDs plus immutable record fingerprints, complete another external task without scope expansion, and pass Runtime Verification again. v1.5 is not graduated from bootstrap write-only evidence alone.
Successor handoff hardening: Runtime Verification does not arm proof002 merely because a task merged or a runtime receipt says VERIFIED. A trusted successor boundary reconstructs the expected runtime-feedback memory record from the exact contract/receipt/report, requires that exact record to exist in the durable store, requires Campaign COMPLETED and Project READY with failed=0, freezes proof001 as bootstrap-only evidence, then writes the fixed proof002 high-level Goal. Runtime Verification sends an explicit repository_dispatch after durable feedback; an independent scheduled successor watchdog is the bounded fallback if workflow chaining is unavailable.
Final audit prebuild: the v1.5 Graduation audit is now proof002-oriented. It reconstructs the pre-proof002 durable store by removing only proof002's own feedback record, requires the Planner's stored source fingerprint to match that reconstructed store, validates every reused memory ID against its immutable record fingerprint, requires the proof001 bootstrap feedback record to be among those reused records, and then independently binds proof002's exact merge SHA, Runtime Verification evidence, final feedback record, terminal Campaign/Project state, and mandatory safety proofs. The audit is implemented and unit-proven before the real proof completes, but it is intentionally not added as a mandatory CI graduation step until real proof002 evidence exists.
Memory feedback retry hardening: a runtime receipt reaching VERIFIED is never downgraded because the advisory memory-store write failed. If proof001's exact VERIFIED receipt/report exist but its reconstructed feedback record is absent from the durable store, the trusted successor watchdog re-dispatches the same source-SHA-bound Runtime Verification event. The VERIFIED fast path reuses the stored report and retries only the idempotent memory-feedback write; it does not rerun probes, broaden scope, or create execution authority. Dispatch failure remains recoverable through the successor's scheduled retry loop.

