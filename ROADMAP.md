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
