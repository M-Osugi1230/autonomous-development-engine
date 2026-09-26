# Autonomous Development Engine (ADE)

ADE is a goal-driven software development control plane designed to keep making progress toward explicit acceptance criteria while using remote coding agents and cloud execution.

The initial vertical slice uses:

- GitHub as the durable source of truth.
- Google Jules as the first coding-agent provider.
- GitHub Actions for deterministic validation.
- Repository state under `.autodev/` so work can pause and resume without relying on chat history.

## Proven so far

ADE has completed the core closed loop:

```text
repository task
→ Jules cloud coding session
→ automatic pull request
→ deterministic CI
→ trusted PR gate
→ merge
→ durable state advance
→ next autonomous task
```

It also has a bounded repair layer that classifies failures and can take deterministic retry, replan, quota-pause, human-wait, or terminal-fail dispositions. Crash-safe checkpoint continuation and cloud-only quota resume routing are proven under CI.

Phase 7 adds a durable human-decision queue: routine reversible work can proceed automatically, while destructive/irreversible, credential/secret, and externally consequential actions enter HUMAN_WAIT and require an explicit persisted human response.

## Repository layout

```text
.autodev/              Durable ADE state
src/ade/               ADE core
scripts/               Operational entry points
tests/                 Deterministic tests
.github/workflows/     CI and Jules orchestration
GOAL.md                Product goal
SPEC.md                Frozen v0 architecture
ACCEPTANCE.md          Machine-oriented acceptance criteria
ROADMAP.md             Delivery phases
```

## Security

Never commit provider API keys. The Jules key is read only from the `JULES_API_KEY` environment variable and is expected to live in GitHub Actions repository secrets.

## Current milestone

Phase 8: Mission Control. The next milestone is a mobile-first, read-only operational view of project health, checkpoints, open human decisions, recent activity, and preview links before any remote control actions are added.
