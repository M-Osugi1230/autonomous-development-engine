# ADE v0 Specification

## Architecture

ADE is an event-driven control plane. It does not require a continuously running local machine.

Core components:

- **State Store** — repository-backed durable state under `.autodev/`.
- **Provider Interface** — stable abstraction for coding-agent providers.
- **Jules Provider** — first provider implementation using the Jules REST API.
- **Validator** — GitHub Actions and repository tests.
- **Trusted Controller** — privileged code under `.github/trusted/` that may use repository write credentials or provider secrets.
- **Continuous Controller** — advances bounded tasks after validated merges.
- **Checkpoint / Resume Layer** — persists provider-session state and resumes eligible work after process interruption or quota pauses.
- **Human Interrupt Queue** — persists high-value human decisions and blocks only work that crosses configured autonomy boundaries.
- **Mission Control** — Phase 8 read-only operational surface, followed later by tightly scoped control actions.

## Design rules

- Provider-specific details must not leak into the core state model.
- Secrets must never be written to repository files or logs.
- Code editable by the coding agent must not receive `JULES_API_KEY` or a write-capable GitHub token.
- AI self-reports do not define completion; deterministic acceptance checks do.
- Quota exhaustion is a resumable state, not a fatal error.
- Destructive or irreversible operations require explicit human approval.
- Credential/secret access and externally consequential side effects require HUMAN_WAIT.
- Routine reversible work should not interrupt the human unnecessarily.
- Human responses are persisted and retrieved explicitly; a resolved response is never interpreted as automatic approval by the queue itself.
- Pull requests may auto-merge only through the trusted PR gate after green CI, Jules provenance validation, and change-scope validation.
- Jules-generated pull requests may not modify trusted control paths, workflows, canonical ADE state, frozen goal/spec/acceptance documents, or other forbidden paths enforced by the gate.

## Jules integration

Base URL:

`https://jules.googleapis.com/v1alpha`

Authentication header:

`x-goog-api-key: <JULES_API_KEY>`

The adapter supports the provider operations needed by the current vertical slice, including source discovery, session creation, session monitoring, and pull-request automation.

Operational Jules calls that use `JULES_API_KEY` run only from the trusted boundary.

## Persistence

`.autodev/state.json` is the canonical machine-readable project state.

Additional repository-backed ledgers include:

- `.autodev/task-queue.json`
- `.autodev/cycle-task.json`
- `.autodev/runtime/checkpoint.json`
- `.autodev/decisions.json`
- `.autodev/failures.json`
- `.autodev/metrics.json`

All state files are intentionally human-readable JSON.

## Pause / resume contract

A running provider session is checkpointed with its provider session id before monitoring continues. If the process disappears, ADE can resume monitoring the same session instead of creating a duplicate. Quota-paused work records a future resume time and is revisited by a cloud-scheduled trusted runner.

## Human-decision contract

A deterministic interrupt policy classifies work into PROCEED or HUMAN_WAIT. High-risk categories are fixed to HUMAN_WAIT. Open decisions are atomically persisted, repeated requests are idempotent, conflicting reuse of a decision id is rejected, and only an explicit human response can resolve an open decision.

## Current milestone

Phase 8 begins with a read-only Mission Control snapshot. It must expose only repository-derived operational facts first; mutation controls are deferred until the read model, security boundaries, and auditability are proven.
