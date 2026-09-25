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

Three bounded Jules development tasks have already completed through this loop.

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

Phase 5: bounded repair loop. The active autonomous queue is building deterministic failure classification and retry/replan/pause/human-wait policy before wiring repair into the runtime controller.
