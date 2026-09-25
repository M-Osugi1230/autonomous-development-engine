# Autonomous Development Engine (ADE)

ADE is a goal-driven software development control plane designed to keep making progress toward explicit acceptance criteria while using remote coding agents and cloud execution.

The initial vertical slice uses:

- GitHub as the durable source of truth.
- Google Jules as the first coding-agent provider.
- GitHub Actions for deterministic validation.
- Repository state under `.autodev/` so work can pause and resume without relying on chat history.

## Phase 0–1 goals

1. Define durable project/task state.
2. Define safety and pause rules.
3. Provide a provider abstraction that does not couple ADE to Jules.
4. Implement the first Jules REST API adapter.
5. Validate the Jules API key and repository visibility from GitHub Actions.

## Repository layout

```text
.autodev/              Durable ADE state
src/ade/               ADE core
scripts/               Operational entry points
tests/                 Deterministic tests
.github/workflows/     CI and Jules smoke test
GOAL.md                Product goal
SPEC.md                Frozen v0 architecture
ACCEPTANCE.md          Machine-oriented acceptance criteria
ROADMAP.md             Delivery phases
```

## Security

Never commit provider API keys. The Jules key is read only from the `JULES_API_KEY` environment variable and is expected to live in GitHub Actions repository secrets.

## Current milestone

Phase 0 foundation + Phase 1 Jules provider.
