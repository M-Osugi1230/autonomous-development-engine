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

## Active milestone — Phase 6 pause / resume

- [x] A validated provider-agnostic task checkpoint model exists.
- [x] Checkpoints can be atomically persisted and loaded.
- [x] Resume decisions are deterministic for quota pause, human wait, running recovery, replan, failure, and completion.
- [x] An existing provider session can be monitored after process restart without creating a duplicate session.
- [x] Runtime lifecycle transitions persist RUNNING and terminal/resumable checkpoint states.
- [x] A crash/restart continuation path is proven end-to-end under CI.
- [ ] A due quota-paused checkpoint can trigger a later cloud resume without a local machine.
