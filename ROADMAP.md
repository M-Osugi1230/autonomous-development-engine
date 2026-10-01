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

## ADE v1.5 — Development Memory ✅
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
Quota cross-watch hardening: v1.5 no longer depends on a single GitHub schedule delivery. The independent Development Memory Successor watchdog reuses the exact trusted `jules_resume.decide_checkpoint_action` policy; when proof001/proof002 is PAUSED_QUOTA and due, it dispatches `ade_resume_watch` rather than starting Jules itself. Resume Watch remains the only component that reclaims the execution lease, preserves the target repository, and starts/monitors the provider session. Before the due boundary the successor watchdog is a strict NOOP.
Runtime phase carry-forward hardening: the post-merge Remote PR Monitor now treats Runtime Verification as a graduated platform capability rather than a v1.4-only experiment. The allowlist explicitly includes `v1.4-runtime-deployment-verification` and `v1.5-development-memory`; older and unknown phases remain fail-closed. This is required for both v1.5 real proofs to produce exact-merge-SHA runtime evidence and durable memory feedback.

Proof001 bootstrap complete: request `v1.5-development-memory-proof-001` reused two trusted v1.4 memory records as advisory-only planning data, automatically executed task `v15mem1-001`, produced external PR #18 with only `tests/test_models.py`, passed target CI run `36706648785`, and merged through trusted gate at exact target SHA `098ad46eacba0da82bf8c9551df48f7401bf54c6`. Runtime Verification run `36706778575` reached durable `VERIFIED` with both required probes PASS on attempt 1. The verified outcome was appended to `.autodev/development-memory.json` as `mem-3d6660d55ad11cf3941ee9fb` with record fingerprint `72a5c70e6eed1f6af559c3182a2f8ccffea6c340eeb5163aba549cde38456e99`. Trusted successor run `36706821914` froze bootstrap-only evidence and armed proof002; proof001 alone remains explicitly ineligible for v1.5 graduation.

Proof002 graduation complete: request `v1.5-development-memory-proof-002` reused durable record `mem-3d6660d55ad11cf3941ee9fb` with immutable fingerprint `72a5c70e6eed1f6af559c3182a2f8ccffea6c340eeb5163aba549cde38456e99` directly from `.autodev/development-memory.json` as advisory-only planning data. Zero-Touch preserved the one-task tests-only AcceptedPlan, Resume Watch run `36746488623` resumed the quota-paused task through Jules session `8394616774902109947`, external PR #19 changed only `tests/test_models.py`, target CI run `36751301574` passed, trusted gate run `36751376308` merged exact SHA `4357dc7b6dfb1b882d9ea7f65aae44e302e73a6b`, Remote PR Monitor run `36751316780` dispatched Runtime Verification, and run `36751438279` reached single-dispatch `VERIFIED` with both required probes PASS on attempt 1. The resulting `VERIFIED_OUTCOME` record `mem-786d667480ca61ad8f1a9f0f` was appended to the durable store, trusted finalizer run `36751520177` reconstructed the full provenance chain and froze `.autodev/campaign-evidence/v1.5-development-memory-proof-002.json` only after the dedicated graduation audit passed. v1.5 is graduated only after that audit is also mandatory and green in repository CI.

## ADE v1.6 — Autonomous Backlog ✅
Turn trusted evidence into a bounded queue of possible next Goals without giving backlog data any execution authority. Autonomous Backlog is an advisory candidate layer only: candidates cannot dispatch work, expand scope, bypass human boundaries, or replace Autonomous Planner / AcceptedPlan validation.

Build order:
1. immutable evidence-bound BacklogCandidate schema + deterministic bounded ledger
2. trusted candidate extraction from verified Acceptance gaps, runtime/recovery outcomes, Development Memory, and Repository Intelligence
3. deterministic deduplication, supersession, staleness, and controller-owned priority
4. repository/source-SHA-bound eligibility with human-only exclusion
5. single-candidate Goal handoff into the existing Autonomous Planner boundary
6. verified completion feedback and candidate retirement
7. real external-repository proof and v1.6 graduation audit

Slice 001 complete: `BacklogCandidate` is repository/source-SHA/evidence bound and uses a fixed candidate-kind enum, bounded printable statement, normalized trusted `.autodev/` evidence paths, SHA-256 evidence fingerprints, bounded tags, and an explicit human-only marker. Candidate IDs can be deterministically derived from trusted metadata. `AutonomousBacklog` is immutable, order-deterministic, duplicate-ID fail-closed, capped at 500 candidates, and independently fingerprinted. Serialized candidate/backlog data explicitly carries `execution_authority=false`, `auto_dispatch=false`, and `may_expand_scope=false`; attempts to deserialize authority escalation are rejected. Slice 001 has no workflow activation and does not interact with the active v1.5 proof002 Campaign.

v1.6 Slice 002 complete: trusted extraction creates candidates only from strict controller-owned RecoveryRecord and RuntimeVerification contract/receipt evidence. Recovery candidates are derived from fixed RecoveryFailure/RecoveryAction enums and fixed controller templates; unknown or free-form fields are rejected. Runtime-gap candidates require exact verification identity, repository, source-SHA, and contract-fingerprint binding, accept only FAILED/HUMAN_WAIT receipts, and are always `human_only=true`. Provider prose is never copied into candidate statements, and extraction still grants no execution, dispatch, or scope-expansion authority.

v1.6 Slice 003 complete: backlog resolution is deterministic and controller-owned. Every repository must have an exact trusted current-source SHA; mismatched candidates become STALE. Explicit evidence-bound supersession is same-repository only, rejects unknown candidates, multiple-successor ambiguity, and cycles. Active semantic duplicates are deterministically collapsed while contradictory candidates for the same subject fail closed to CONFLICTED. Priority is not an AI score: it is a fixed `controller-kind-policy-v1` rank derived only from BacklogCandidateKind. Resolution remains advisory and carries `execution_authority=false`.

v1.6 Slice 004 complete: eligibility selection is bound to the exact repository and current source SHA already frozen in backlog resolution. Only CURRENT and non-human-only candidates are eligible; STALE, SUPERSEDED, CONFLICTED, cross-repository, cross-SHA, and human-only candidates are excluded. Selection is deterministic by the controller-owned priority rank and candidate ID and returns at most one candidate. The selection object explicitly carries `execution_authority=false`, `planning_goal_authority=false`, and `auto_dispatch=false`.

v1.6 Slice 005 complete: an eligible candidate can be transformed only into a high-level `PlanningGoalRequest`, never directly into executable tasks. Repository, base branch, allowed path prefixes, and task-count bounds come from a separate trusted `BacklogPlanningPolicy`; candidate data cannot expand them. Protected controller/state/secret roots are rejected. The deterministic handoff binds candidate, selection, resolution, and policy fingerprints and explicitly targets `AutonomousPlanner` with `execution_authority=false`, `accepted_plan_authority=false`, and `auto_dispatch=false`. Existing Autonomous Planner validation and AcceptedPlan construction remain the sole task/scope authority.
v1.6 Slice 006 complete: completion feedback is represented as an immutable `BacklogRetirementRecord`, not candidate deletion. A retirement can be built only when the exact selected candidate/handoff fingerprint is preserved, the handoff Campaign is COMPLETED with every task complete, ProjectState is READY/current-task-null/failed=0, the final RemoteExecution receipt is MERGED and belongs to the Campaign, and exact-source Runtime Verification is single-dispatch `VERIFIED` with a report that re-evaluates identically under the trusted contract. Retirement records bind aligned trusted `.autodev/` evidence paths and SHA-256 fingerprints, carry no execution/dispatch authority, are included in the backlog-resolution fingerprint, and force the candidate to `RETIRED / VERIFIED_COMPLETION` so it cannot be selected again. Failed runtime, partial Campaigns, dirty ProjectState, PR-created-only receipts, task drift, evidence drift, and candidate-fingerprint drift all fail closed.
v1.6 real-proof source hardening: the graduation proof candidate can be extracted from a durable Development Memory store only when the selected record is a strict `VERIFIED_OUTCOME` carrying controller-owned `feedback/runtime/verified` tags. The candidate binds both the entire store fingerprint and the exact immutable memory-record fingerprint, uses a controller-owned fixed follow-up statement rather than copying Memory prose, remains non-human-only and non-executable, and cannot be generated from FAILURE/DECISION/REMEDIATION records, missing trusted tags, or a tampered store fingerprint. This prepares a clean evidence -> candidate entrypoint for the v1.6 real external-repository proof without activating v1.6 while v1.5 proof002 remains quota-paused.
v1.6 Graduation audit prebuild: the dedicated audit now reconstructs the entire proof chain instead of trusting final self-reported flags. It revalidates the frozen source Development Memory snapshot, re-extracts the exact verified-memory candidate, recomputes initial resolution and deterministic selection, rebuilds the trusted tests-only PlanningGoal handoff, binds raw Planner evidence and the one-task AcceptedPlan, checks terminal Campaign/Project state and merged external execution, re-evaluates exact-SHA Runtime Verification, rebuilds the immutable retirement record, then recomputes post-retirement resolution/selection and requires the retired candidate to be ineligible for reselection. Candidate tampering, Memory fingerprint drift, scope expansion, runtime failure, retirement drift, reselection, manual progression, or missing mandatory CI proofs all block graduation. The audit is unit-proven in advance but remains intentionally non-mandatory until the real v1.6 external proof exists and v1.5 has graduated.
v1.6 activation gate hardening: the real Autonomous Backlog proof cannot arm from backlog data alone. A dedicated trusted successor first requires the completed v1.5 Graduation audit on the current repository plus `ProjectState.metadata.v1_5_graduated=true`, READY/current-task-null/failed=0 state, and exactly one proof002 `VERIFIED_OUTCOME` record for task `v15mem2-001` in the durable Development Memory store. It snapshots that store immutably, derives exactly one source-SHA-bound candidate, recomputes resolution/selection under a fixed tests-only one-task policy, freezes candidate/resolution/selection/policy/handoff artifacts, then hands only the resulting high-level PlanningGoal to Autonomous Planner. It never creates executable tasks, and any immutable artifact drift fails closed. The successor proof is mandatory in CI and in the v1.6 Graduation audit.
v1.6 Runtime Verification carry-forward: post-merge Runtime Verification is now explicitly enabled for the `v1.6-autonomous-backlog` phase in the same fail-closed phase allowlist used by v1.4/v1.5. The existing trusted Remote PR Monitor still binds the exact trusted merge SHA, PR head SHA, PR number, monitor run, probe registry and policy before dispatch; older/unknown phases remain excluded. The mandatory post-merge trigger proof now exercises v1.6 as well as v1.5.
v1.6 proof finalization hardening: Runtime Verification now persists proof provenance independently from advisory Development Memory feedback and dispatches a dedicated backlog finalizer only for a VERIFIED receipt while the active phase is `v1.6-autonomous-backlog`. The finalizer reconstructs the frozen source-memory candidate chain, requires the live high-level Goal and one-task tests-only AcceptedPlan, binds the Zero-Touch receipt, merged target PR, target CI, Remote PR Gate, Remote PR Monitor, implementation workflow and Runtime Verification to the exact PR head/merge SHAs, rejects any recovery record for the proof task, rebuilds the immutable retirement and post-retirement no-reselection state, and runs the v1.6 Graduation audit before writing any final proof artifact. PlanningGoal, AcceptedPlan, Campaign, ProjectState, RemoteExecution and workflow provenance are copied into a proof-specific immutable snapshot so future phases cannot invalidate the v1.6 graduation audit by overwriting live runtime state. Scheduled/workflow-run wakeups are NOOP until all Runtime evidence exists, preventing race-induced false failures. The dedicated finalizer proof is mandatory in CI and in the v1.6 audit.

v1.6 Graduation complete: durable Development Memory record `mem-786d667480ca61ad8f1a9f0f` produced evidence-bound candidate `backlog-ba0e89dca2644d15388d33be`, which was deterministically resolved and selected, transformed only into a tests-only one-task PlanningGoal, and accepted by Autonomous Planner in workflow run `36751985370`. Zero-Touch run `36752097727` dispatched task `abgproof-777c97294d-001`; Jules implementation run `36752114620` created external PR #20 with only `tests/test_pipeline.py`, target CI run `36752625571` passed, Remote PR Gate run `36752714827` approved the bounded scope, Remote PR Monitor run `36752631935` merged exact SHA `d9b8f0387525bb40dcc1baba8d730b7c4b4cdc30`, and Runtime Verification run `36752806598` produced a single-dispatch `VERIFIED` receipt with both required probes passing. Trusted retirement `retire-f2dd36372c1d1e111588bda5` binds the verified merge evidence, post-retirement resolution marks the candidate `RETIRED / VERIFIED_COMPLETION`, and post-retirement selection has no eligible candidate. Immutable proof is frozen at `.autodev/campaign-evidence/v1.6-autonomous-backlog-proof-001.json`; the finalizer reconstructed the full chain and the dedicated v1.6 Graduation audit passed before evidence was persisted. No human-authored per-task work item or manual Campaign progression was used. The v1.6 audit is mandatory in repository CI.

## ADE v1.7 — Multi-Agent ✅
Add multiple bounded agent roles around one trusted AcceptedPlan without turning agent consensus into authority. Multi-Agent orchestration remains subordinate to the existing controller: AcceptedPlan owns task/scope, execution leases own concurrency, Trusted Gate owns merge eligibility, Runtime Verification owns verified completion, and HUMAN_WAIT remains the boundary for unresolved human decisions.

Build order:
1. immutable AgentRole / AgentAssignment / MultiAgentPlan contracts bound to AcceptedPlan evidence
2. trusted role-plan derivation from AcceptedPlan + provider availability
3. immutable reviewer and diagnostic contribution records
4. deterministic controller reconciliation with explicit conflict/HUMAN_WAIT behavior
5. per-role provider-session lifecycle, affinity, lease and quota recovery
6. bounded implementer -> reviewer -> correction loop without direct reviewer execution authority
7. real external-repository proof and v1.7 graduation audit

Slice 001 complete: `AgentRole` is a fixed enum (`IMPLEMENTER`, `REVIEWER`, `DIAGNOSTIC`). Every `AgentAssignment` is bound to repository, exact source SHA, Campaign, task, AcceptedPlan fingerprint, provider identity and trusted `.autodev/` evidence. `MultiAgentPlan` is immutable, deterministic and fingerprinted, permits at most one assignment per role and at most three assignments total, and requires exactly one IMPLEMENTER. Role identity is intentionally separate from provider identity so one provider may serve multiple logical roles without changing authority. Serialized assignments/plans explicitly carry `execution_authority=false`, `auto_dispatch=false`, `merge_authority=false`, `acceptance_authority=false`, and `may_expand_scope=false`; deserialization rejects any escalation, unknown fields, cross-anchor drift, unsafe evidence, URLs, or secret-like objective text. Slice 001 creates no provider sessions and does not alter the v1.6 graduated proof. Its deterministic trusted probe is mandatory in CI.

Slice 002 complete: the trusted controller can now derive a `MultiAgentPlan` only from an already-`ACCEPTED` AcceptedPlan, an exact task ID, repository/source/Campaign anchors, trusted AcceptedPlan/provider-availability evidence fingerprints, a controller-owned role-routing policy, the registered provider descriptors, and current availability snapshots. Provider routing decides provider identity only; role objectives are fixed controller templates bound to the AcceptedPlan task and contain no new scope. IMPLEMENTER selection fails closed when no eligible provider is available. REVIEWER selection prefers a distinct eligible provider but may deterministically reuse the implementer provider when policy allows and no distinct provider is currently available. Derivation creates no provider sessions, sends no messages, approves no plans, and grants no execution/dispatch/merge/Acceptance/scope-expansion authority. The trusted derivation probe is mandatory in CI.

Slice 003 complete: reviewer and diagnostic outputs are now normalized into immutable `AgentContribution` evidence bound to the exact `MultiAgentPlan` fingerprint, assignment ID/fingerprint, repository, source SHA, Campaign, task, AcceptedPlan fingerprint, role and provider. Only REVIEWER or DIAGNOSTIC assignments may emit these contribution objects; IMPLEMENTER output cannot masquerade as review evidence. Contribution verdicts are a fixed controller enum (`CLEAR`, `CHANGES_REQUIRED`, `HUMAN_REVIEW_REQUIRED`) and remain advisory claims only. Even `CLEAR` carries no merge or Acceptance authority. Serialized contributions require `advisory_only=true` and explicitly set execution, code-mutation, Campaign-state, Acceptance, merge, Runtime-Verification, auto-dispatch and scope-expansion authority to false. Unknown fields, authority escalation, plan/assignment drift, unsafe evidence paths, URLs, control text and secret-like summaries fail closed. A mandatory CI probe proves reviewer and diagnostic contributions cannot directly mutate trusted state.

Slice 004 complete: agent contributions are reconciled by a controller-owned fixed policy with no majority voting. Required reviewer evidence must be present before reconciliation is complete. All CLEAR contributions produce a non-authoritative CLEAR disposition; unanimous CHANGES_REQUIRED produces CHANGES_REQUIRED; any explicit HUMAN_REVIEW_REQUIRED produces HUMAN_WAIT; and contradictory CLEAR versus CHANGES_REQUIRED verdicts are treated as a material disagreement and deterministically produce HUMAN_WAIT rather than counting votes. HUMAN_WAIT results receive a deterministic decision ID and are converted into the existing `DecisionRequest` format using only trusted identifiers/fingerprints. The trusted probe passes that request through `HumanInterruptCoordinator` with `DecisionKind.SPECIFICATION_AMBIGUITY` and proves exactly one OPEN human decision is durably queued. Reconciliation results still carry no execution, merge, Acceptance, or Runtime Verification authority.


Slice 005 complete: each Multi-Agent assignment now has a controller-owned RoleSession bound to the exact MultiAgentPlan and assignment fingerprints, repository/source/Campaign/task/AcceptedPlan anchors, logical role, and routed provider identity. Provider affinity cannot change after derivation; only READY sessions may create a provider session; RUNNING/PAUSED_QUOTA sessions suppress duplicate assignment or same-role sessions; PAUSED_QUOTA requires a durable resume_after boundary and cannot resume before it; resume reuses the original provider session rather than creating a replacement. Serialized lifecycle evidence explicitly grants no execution, merge, Acceptance, or scope-expansion authority. This layer is subordinate to the existing task execution lease and does not bypass task-level lease, checkpoint, HUMAN_WAIT, trusted merge, or Runtime Verification gates. The deterministic role-session lifecycle probe is mandatory in CI.

v1.7 live-proof infrastructure: reviewer clearance is now a distinct immutable evidence layer rather than reviewer-granted merge authority. A clearance binds the exact AcceptedPlan/MultiAgentPlan, REVIEWER assignment, completed independent reviewer RoleSession, CLEAR contribution, CLEAR reconciliation, target PR number and reviewed PR head SHA. Every serialized authority field remains false. A dedicated controller workflow can start or resume a separate Jules reviewer session with PR creation disabled, extracts only an exact standalone `ADE_REVIEW_VERDICT=...` marker from provider activity, persists no raw reviewer text, and converts that marker through trusted contribution/reconciliation logic. Missing or conflicting markers fail closed. v1.7 PR creation triggers this reviewer only for phase `v1.7-multi-agent`; scheduled retries cover quota or delivery gaps. The target repository merge gate remains the sole merge authority and will be separately hardened to require an exact CLEAR clearance only for v1.7 tasks.

v1.7 real proof001 armed: high-level Goal `v1.7-multi-agent-proof-001` is restricted to one tests-only task in `M-Osugi1230/one-minute-thought-experiments`. The implementation target is a regression test for U+2004 THREE-PER-EM SPACE and U+2006 SIX-PER-EM SPACE normalization. No human-authored task is supplied. The proof must pass Autonomous Planner/AcceptedPlan, Zero-Touch implementer execution, target CI, an independent REVIEWER role/session with exact CLEAR evidence, the v1.7 review-gated target merge, exact-merge-SHA Runtime Verification, terminal Campaign/Project reconciliation, and the dedicated v1.7 Graduation audit before graduation can be claimed.

v1.7 Runtime Verification carry-forward: the trusted Remote PR Monitor now recognizes `v1.7-multi-agent` as an exact post-merge Runtime Verification phase, while older unknown phases remain excluded. Verified v1.7 runs persist the same exact-merge provenance envelope used by graduation reconstruction, without invoking the v1.6 backlog finalizer or granting any new merge authority. The trigger and provenance phase gates are covered by deterministic tests.

v1.7 graduation finalization gate: post-merge Runtime Verification now dispatches a dedicated v1.7 finalizer only from the `v1.7-multi-agent` phase after exact-merge provenance exists. The finalizer snapshots PlanningGoal, AcceptedPlan, Campaign, ProjectState, RemoteExecution, implementer checkpoint, Multi-Agent Plan, independent reviewer RoleSession, reviewer observation, advisory contribution, deterministic reconciliation, review clearance, Planner/Zero-Touch/runtime provenance, and target PR observations into a proof-specific immutable namespace. Before any proof artifact is persisted, the v1.7 audit reconstructs the review chain, requires a completed reviewer provider session distinct from the implementer session, requires exactly one CLEAR verdict marker without persisted raw activity text, rebuilds reconciliation and clearance deterministically, binds the reviewed PR head to the exact merged head and tests-only path, re-evaluates Runtime Verification from the exact merge SHA, and requires the existing trusted CI proof set. The finalizer cannot itself mark v1.7 graduated; graduation remains a separate repository change after immutable evidence is frozen.

v1.7 Graduation complete: high-level Goal `v1.7-multi-agent-proof-001` was accepted as the one-task tests-only task `v17ma1-001`, dispatched through Zero-Touch run `36790422503`, and implemented by Jules run `36790432422`. External PR #22 changed only `tests/test_models.py`; target CI run `36790874136` passed. An independent reviewer RoleSession used a provider session distinct from the implementer session, Multi-Agent Review run `36790892539` emitted exactly one trusted CLEAR verdict, and immutable review clearance `08525ff4cdf0cf062b4ef33afba5c33eae7f5ae77648e8a4c09e4ef3388b680e` bound the exact reviewed head SHA. Trusted target gate run `36804820190` merged exact SHA `726431b60db8b25cdd4bc15bb1493a0060f36327`; Remote PR Monitor run `36809306560` dispatched Runtime Verification run `36809322346`, which completed single-dispatch VERIFIED against that exact merge SHA. Dedicated finalizer run `36809370303` reconstructed the full Planner -> AcceptedPlan -> implementer -> independent reviewer -> CLEAR reconciliation/clearance -> trusted merge -> Runtime Verification chain and froze immutable evidence at `.autodev/campaign-evidence/v1.7-multi-agent-proof-001.json`. The dedicated v1.7 Graduation audit is mandatory in repository CI; reviewer evidence remains advisory and neither reviewer nor finalizer gains execution, Acceptance, merge, or Runtime Verification authority.

## ADE v1.8 — Autonomous Release Orchestration

Turn verified development output into evidence-bound release candidates and orchestrate safe environment promotion without treating merge or CI success as deployment authority.

Build order:
1. immutable ReleaseCandidate contract bound to AcceptedPlan, Campaign, exact source SHA, and Runtime Verification evidence
2. trusted release-readiness derivation from terminal verified Campaign evidence
3. release policy and environment transition model for preview / staging / production
4. Human Decision Queue integration for externally consequential promotion
5. trusted deployment adapter boundary with idempotency, provenance, and duplicate suppression
6. post-promotion Runtime Verification and bounded rollback / HUMAN_WAIT containment
7. Mission Control release observability
8. real external-repository release proof and dedicated v1.8 Graduation audit

Slice 001 complete: ADE now has an immutable, deterministic ReleaseCandidate contract. Every candidate is bound to one repository, exact source SHA, Campaign, AcceptedPlan fingerprint, Runtime Verification identity, target environment, and trusted .autodev evidence fingerprints. AcceptedPlan, Campaign, and Runtime Verification evidence are mandatory; duplicate evidence kinds, unsafe evidence paths, schema drift, content/ID mismatch, and serialized authority escalation fail closed. Release candidates explicitly carry no deployment, promotion, auto-promotion, scope-expansion, or Acceptance-mutation authority. Under the current ADE safety contract every environment promotion remains human-approval gated; later slices may orchestrate that approval but cannot infer it from candidate existence.

Slice 002 complete: trusted release-readiness derivation now requires a terminal COMPLETED Campaign whose exact goal/task order matches the AcceptedPlan, every Campaign task completed, and an exact post-merge Runtime Verification identity of rv-<source_sha>. The final completed Campaign task must own a dispatched VERIFIED receipt, and receipt/report repository, source SHA, verification ID, and contract fingerprint must all match the trusted RuntimeVerificationContract. Only then does ADE deterministically derive AcceptedPlan, Campaign, and Runtime Verification evidence fingerprints and emit a human-approval-gated ReleaseCandidate. Failed, pending, stale, arbitrary, or non-final-task verification evidence fails closed.

Slice 003 complete: ReleasePromotionPolicy now fixes the only legal environment order to preview -> staging -> production. The controller derives the next target from the last verified environment; the provider cannot select or reorder environments. Skipping, replaying the same stage, reversing, or attempting promotion after production fails closed. Every ReleaseTransitionPlan is deterministically bound to the exact ReleaseCandidate fingerprint, repository, source SHA, previous verified environment, next environment, and policy fingerprint. Promotion remains human-approval gated and the serialized policy/transition grants no deployment, promotion, or auto-promotion authority.

Slice 004 complete: every release promotion is now routed through the existing Human Decision Queue as a fixed EXTERNAL_SIDE_EFFECT and therefore enters HUMAN_WAIT. The release-specific decision ID and context are derived deterministically from the exact ReleaseTransitionPlan fingerprint, ReleaseCandidate fingerprint, repository, source SHA, previous environment, target environment, and policy fingerprint. Repeated OPEN requests are idempotent. A resolved decision satisfies the gate only when the exact matching request carries an explicit selected option of approve; free text without a selected option is never interpreted as approval, reject remains blocking, and an approval for one transition cannot be reused for another. Approval evidence still grants no deployment, promotion, or auto-promotion authority by itself.

Slice 004 complete: release promotion now uses the existing Human Decision Queue as the explicit external-side-effect boundary. A deterministic DecisionRequest is bound to the exact ReleaseTransitionPlan fingerprint, candidate fingerprint, repository, source SHA, from/to environments, and policy fingerprint. Repeated open requests are idempotent and remain HUMAN_WAIT. Only a resolved response with the exact selected option `approve` satisfies the gate; free text, rejection, cancellation, stale decisions, or a decision from another transition cannot authorize promotion. Approval satisfaction is evidence only and still grants no deployment, promotion, or auto-promotion authority.
