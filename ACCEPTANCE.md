# ADE Core Acceptance Criteria

## Foundation / Jules integration

- [x] Python source compiles successfully.
- [x] Unit tests pass.
- [x] State can be loaded and atomically saved.
- [x] Invalid state is rejected instead of silently accepted.
- [x] Provider interface exists independently of Jules.
- [x] Jules provider reads the API key only from environment/configuration.
- [x] Jules provider maps authentication and quota errors to explicit exception types.
- [x] A GitHub Actions CI workflow validates the repository on pull requests.
- [x] A manual Jules smoke workflow can authenticate and list Jules sources.
- [x] The smoke check confirms `M-Osugi1230/autonomous-development-engine` is visible to Jules.
- [x] No secret value is committed to the repository.

## Closed-loop vertical slice

- [x] ADE can start a bounded Jules coding task from repository state.
- [x] Jules can create a pull request automatically.
- [x] Deterministic CI gates the pull request.
- [x] A trusted controller can merge an allowed Jules pull request.
- [x] Repository state advances to the next queued task.
- [x] The next task is dispatched without a human "next" command.
- [x] At least two consecutive autonomous development cycles completed successfully.
- [x] Multiple autonomous vertical-slice tasks have completed and been merged.

## Phase 5 — Repair loop

- [x] Failures are classified into deterministic failure kinds.
- [x] Retry/replan/pause/human-wait/terminal-fail decisions are bounded by policy.
- [x] Repair policy is wired into the operational Jules runtime.
- [x] A deterministic fail -> retry -> success repair path is proven under CI.
- [x] Operational-script import regressions are covered by CI.

## Phase 6 — Pause / Resume

- [x] A validated provider-agnostic task checkpoint model exists.
- [x] Checkpoints can be atomically persisted and loaded.
- [x] Resume decisions are deterministic for quota pause, human wait, running recovery, replan, failure, and completion.
- [x] An existing provider session can be monitored after process restart without creating a duplicate session.
- [x] Runtime lifecycle transitions persist RUNNING and terminal/resumable checkpoint states.
- [x] A crash/restart continuation path is proven end-to-end under CI.
- [x] A due quota-paused checkpoint can trigger a later cloud resume without a local machine.


## Phase 7 — Human Decision Queue

- [x] Human decision requests and responses have strict immutable lifecycle models.
- [x] Decision records are atomically persisted in a human-readable repository ledger.
- [x] Destructive/irreversible, credential/secret, and external-side-effect decisions always require HUMAN_WAIT.
- [x] Routine reversible work can proceed without creating a human decision.
- [x] Specification ambiguity and user preference handling are deterministic and explicitly configurable.
- [x] Repeated HUMAN_WAIT requests are idempotent and cannot create duplicate open decisions.
- [x] An existing OPEN decision cannot be bypassed by changing policy.
- [x] Human responses must be explicitly resolved and retrieved; they are never treated as automatic approval.
- [x] The full PROCEED -> HUMAN_WAIT -> resolve -> reload -> retrieve lifecycle is proven under CI.


## Phase 8 — Mission Control

- [x] A safe read-only Mission Control snapshot aggregates canonical project state, checkpoint, queue, failures, telemetry, and OPEN human decisions.
- [x] Provider session identifiers, decision context, tracebacks, and secret-like values are excluded or redacted from display output.
- [x] A mobile-first static HTML renderer works without JavaScript or external resources.
- [x] A deterministic build CLI writes `index.html` and `snapshot.json` atomically.
- [x] A read-only GitHub Actions workflow builds and uploads Mission Control with no repository write permission, provider secrets, or deployment credentials.
- [x] The real cloud workflow successfully produced the `ade-mission-control` artifact.
- [x] An end-to-end offline probe proves snapshot -> HTML -> artifact -> reload without leaking sensitive fixture data.
- [x] Mission Control includes a durable project activity feed.
- [x] Mission Control includes safe latest-output / preview metadata for human review.
- [x] Phase 8 activity + preview behavior is proven end to end under CI.
