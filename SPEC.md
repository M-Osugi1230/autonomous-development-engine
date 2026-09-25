# ADE v0 Specification

## Architecture

ADE is an event-driven control plane. It does not require a continuously running local machine.

Core components:

- **State Store** — repository-backed durable state under `.autodev/`.
- **Provider Interface** — stable abstraction for coding-agent providers.
- **Jules Provider** — first provider implementation using the Jules REST API.
- **Validator** — GitHub Actions and repository tests.
- **Controller** — later phase component that chooses the next bounded task.
- **Human Interrupt Queue** — later phase component for high-value decisions.

## Design rules

- Provider-specific details must not leak into the core state model.
- Secrets must never be written to repository files or logs.
- AI self-reports do not define completion; deterministic acceptance checks do.
- Quota exhaustion is a resumable state, not a fatal error.
- Destructive or irreversible operations require explicit human approval.
- v0 does not auto-merge pull requests.

## Jules integration

Base URL:

`https://jules.googleapis.com/v1alpha`

Authentication header:

`x-goog-api-key: <JULES_API_KEY>`

The initial adapter supports:

- list sources
- locate a GitHub source
- create session
- get session
- list activities
- send message
- approve plan

`AUTO_CREATE_PR` is supported when explicitly requested by the caller.

## Persistence

`.autodev/state.json` is the canonical machine-readable project state. Additional ledgers store decisions, failures, and metrics.

All state files are intentionally human-readable JSON.
