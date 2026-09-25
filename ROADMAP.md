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

Evidence: ADE completed and merged three bounded Jules tasks through the cloud loop without requiring a human "next" command between autonomous tasks.

## Phase 5 — Repair Loop 🚧
Classify failures, choose bounded retry/replan/pause/human-wait dispositions, and wire the policy into execution.

## Phase 6 — Pause / Resume
Quota-aware and crash-safe continuation.

## Phase 7 — Human Decision Queue
Ask only for decisions that exceed configured autonomy thresholds.

## Phase 8 — Mission Control
Mobile-first project health, decisions, preview, and activity feed.

## Phase 9 — Task DAG
Continue independent work while another task waits for human input.

## Phase 10 — Multi-provider Routing
Add additional hosted/local providers behind the same interface.

## Phase 11 — Production Project Pilot
Run ADE against a real project with explicit acceptance criteria.
