# Autonomous Development Engine (ADE)

ADE is a goal-driven software development control plane designed to keep making progress toward explicit acceptance criteria while using remote coding agents and cloud execution.

The production architecture uses:

- GitHub as the durable source of truth.
- Google Jules as the first coding-agent provider behind a replaceable provider boundary.
- GitHub Actions for deterministic validation and trusted orchestration.
- Repository state under `.autodev/` so work can pause and resume without relying on chat history.

## Proven closed loop

ADE has completed and graduated the full bounded development loop:

```text
high-level Goal
→ repository understanding
→ autonomous plan
→ trusted plan validation
→ task DAG
→ remote implementation
→ independent review where required
→ deterministic CI
→ trusted PR gate
→ merge
→ exact-source runtime verification
→ durable development memory
→ autonomous backlog
→ human-gated release orchestration
→ post-release improvement signal
→ successor PlanningGoal
→ verified successor completion
→ lineage retirement
```

The controller keeps execution authority separate from planner, provider, reviewer, telemetry, memory, backlog, and improvement data. Destructive or externally consequential operations remain behind explicit trusted policy and human-decision boundaries where required.

ADE also includes bounded recovery for retry, replan, quota pause/resume, HUMAN_WAIT, and terminal failure; crash-safe checkpoint continuation; read-only Mission Control; dependency-aware DAG scheduling; deterministic multi-provider routing; sticky provider sessions; and exact-source Runtime Verification.

## Graduated capabilities

- ADE v1.0 — production autonomous development foundation.
- ADE v1.1 — Zero-Touch Start.
- ADE v1.2 — Autonomous Planner.
- ADE v1.3 — Repository Intelligence.
- ADE v1.4 — Runtime / Deployment Verification.
- ADE v1.5 — Development Memory.
- ADE v1.6 — Autonomous Backlog.
- ADE v1.7 — Multi-Agent collaboration with trusted reconciliation.
- ADE v1.8 — Autonomous Release Orchestration with explicit human approval for external promotion.
- ADE v1.9 — Continuous Improvement Loop with verified lineage retirement.

## Current milestone

ADE v1.9 Continuous Improvement Loop is graduated.

The real external proof starts from the verified v1.8 preview release, derives a trusted tests-only improvement signal, routes it through Development Memory and Autonomous Backlog into the existing PlanningGoal authority, executes and merges the successor change, verifies the exact merge SHA at runtime, then retires the originating signal lineage so the same completed improvement cannot immediately re-enter selection.

The frozen proof is recorded at:

```text
.autodev/campaign-evidence/v1.9-continuous-improvement-proof-001.json
```

The dedicated v1.9 Graduation audit is mandatory in CI. `ACCEPTANCE.md` currently has no unchecked acceptance items, and the durable ProjectState is stable `READY` with no current task, no failed task, and no pending system or human action.

## Repository layout

```text
.autodev/              Durable ADE state and trusted evidence
src/ade/               ADE core
scripts/               Operational and Graduation audit entry points
tests/                 Deterministic tests
.github/trusted/       Trusted controller boundaries and proof logic
.github/workflows/     CI and autonomous orchestration
GOAL.md                Product goal
SPEC.md                Frozen v0 architecture
ACCEPTANCE.md          Machine-oriented acceptance criteria
ROADMAP.md             Delivery phases and Graduation record
```

## Security

Never commit provider API keys or credentials. Provider credentials are read from the runtime environment / GitHub Actions secrets and are not part of durable repository evidence.

Untrusted planner, provider, reviewer, telemetry, memory, backlog, and improvement artifacts do not independently grant scope expansion, execution, merge, release, or Acceptance authority. Trusted controller policy remains authoritative.
