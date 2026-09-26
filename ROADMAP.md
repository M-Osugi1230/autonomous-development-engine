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

## Phase 10 — Multi-provider Routing
Add additional hosted/local providers behind the same interface.

## Phase 11 — Production Project Pilot
Run ADE against a real project with explicit acceptance criteria.
