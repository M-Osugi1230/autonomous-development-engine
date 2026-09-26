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

ADE now also has a durable human-decision queue, a read-only Mission Control surface, dependency-aware DAG scheduling, and deterministic multi-provider routing. Provider sessions are sticky after creation, while new work can route around quota-paused providers before a session exists.

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

Phase 11: Production Project Pilot. The immediate goal is to freeze a machine-readable pilot contract and safety envelope before ADE is allowed to modify a real target repository.
