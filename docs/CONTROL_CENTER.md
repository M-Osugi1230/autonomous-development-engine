# ADE Control Center

## Product direction

ADE Control Center is the operator-facing product surface for Autonomous Development Engine.

The ADE core remains the trusted execution engine. Control Center must not duplicate planner, execution, merge, recovery, runtime-verification, release, or acceptance authority. It presents trusted read models first, then adds narrowly scoped control actions only through explicit trusted controller boundaries.

## Product principles

1. **Human attention first** — the first screen must answer: Is ADE healthy? What is it doing? Do I need to act?
2. **Read-only before control** — new views ship read-only before any mutation path is introduced.
3. **Trusted state only** — UI data comes from controller-owned snapshots and durable `.autodev/` evidence.
4. **No hidden authority** — rendering logic never gains execution, merge, release, or acceptance authority.
5. **Mobile-first operations** — the primary operational surface must remain usable from a phone.
6. **Progressive disclosure** — current task, progress, human action, and activity are prominent; low-frequency orchestration detail is secondary.
7. **Multi-project by design** — the final product must aggregate multiple ADE-managed projects without collapsing their individual trust boundaries.

## Architecture

```text
ADE-managed repositories
        |
        v
Trusted Mission Control read models
        |
        v
Control Center aggregation layer
        |
        v
Read-only dashboard
        |
        +--> future trusted action API
                 |
                 v
           ADE trusted controller
```

The browser must never receive provider credentials, deployment credentials, provider session identifiers, raw decision context, tracebacks, or unbounded telemetry.

## v0.1 — Project dashboard

Status: implementation started.

Scope:

- rename the operator experience from a diagnostic page into **ADE Control Center** while retaining the Mission Control compatibility surface;
- show lifecycle state prominently;
- show goal/campaign progress;
- show current task, queue depth, completed tasks, and failed tasks;
- make **Human action** a first-class status card;
- make **Next system action** and resume timing visible without opening raw state;
- show recent activity as an operational timeline;
- retain warnings, decisions, checkpoint, planner, release, zero-touch, and Continuous Improvement data;
- keep the artifact static, mobile-first, JavaScript-free, and external-resource-free;
- preserve the validated preview URL as the only allowed external link surface.

Non-goals:

- no Goal submission;
- no pause/resume buttons;
- no approval/rejection buttons;
- no multi-project aggregation;
- no change to ADE execution authority.

## v0.2 — Multi-project overview

Target scope:

- define a versioned `ControlCenterProjectSnapshot` derived from each Mission Control snapshot;
- aggregate J-Quants, Chu-kei Insight, Jichi Insight, and future ADE-managed projects;
- show project lifecycle, progress, current task, human-action state, recovery state, and last update on one screen;
- sort attention-required projects first;
- provide project drill-down into the existing project dashboard;
- fail closed when a project snapshot is stale, malformed, or unavailable;
- do not require provider credentials in the aggregation layer.

Expected operator view:

```text
J-Quants      RUNNING      67%   Human action: none
Chu-kei       RECOVERING   42%   Human action: none
Jichi         HUMAN_WAIT   81%   Human action: required
```

## v0.3 — Trusted controls

Only after v0.2 is stable:

- submit a high-level Goal;
- pause a campaign at a safe boundary;
- resume an eligible paused campaign;
- approve or reject an existing Human Decision Queue item;
- acknowledge terminal failures and request a bounded replan.

Every action must become a controller-owned, auditable request with idempotency, authorization, provenance, and deterministic validation. The UI never mutates `.autodev/` state directly.

## v1.0 — ADE operating console

Graduation target:

A user can open one dashboard and manage the full ADE portfolio by exception:

- understand the state of every active project;
- identify blockers immediately;
- see what ADE will do next;
- review outputs and production verification;
- act only when ADE reaches a trusted human boundary;
- submit new Goals without manually writing task prompts;
- leave the system unattended while safe work continues.

The product-level success condition is that the dashboard becomes the normal interface to ADE, while direct repository inspection remains an advanced diagnostic path rather than the primary operating workflow.
