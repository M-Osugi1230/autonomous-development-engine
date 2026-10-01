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


## Phase 9 — Task DAG

- [x] An immutable task-graph model represents bounded coding tasks and dependency edges.
- [x] Graph validation rejects duplicate IDs, missing dependencies, self-dependencies, and cycles.
- [x] Task graph state is atomically persisted in a human-readable repository ledger.
- [x] Runnable selection is deterministic and selects only tasks whose dependencies are COMPLETED.
- [x] HUMAN_WAIT blocks only dependent descendants; independent branches remain runnable.
- [x] FAILED nodes block their descendants and are never silently bypassed.
- [x] Task state transitions are immutable, explicit, and reject illegal transitions.
- [x] An offline end-to-end probe proves independent progress while another branch waits for a human.
- [x] Trusted controller DAG selection is introduced behind a FIFO fallback and cannot dispatch blocked tasks.
- [x] The trusted DAG dispatch path is proven under CI before FIFO migration is considered complete.


## Phase 10 — Multi-provider Routing

- [x] Provider identity and capabilities are immutable, validated, and provider-agnostic.
- [x] A registry holds configured provider instances without constructing them or reading credentials.
- [x] Routing filters required capabilities and chooses candidates deterministically.
- [x] Quota-paused or temporarily unavailable providers can be skipped before session creation.
- [x] Unauthorized or disabled providers are never selected automatically.
- [x] Provider availability/cooldown state is durable, explicit, and evaluated against injected time.
- [x] Existing provider sessions are sticky across crash/resume and are never silently migrated.
- [x] Routed execution returns explicit no-provider/wait/replan outcomes instead of opaque failure.
- [x] A deterministic two-provider failover/resume probe passes under CI.
- [x] At least one additional concrete provider adapter is available behind the common interface before Phase 10 is closed.


## Phase 11 — Production Project Pilot

- [x] A versioned immutable pilot contract identifies the target repository, base branch, and baseline commit SHA.
- [x] The pilot safety envelope has explicit path allowlists, path denylists, allowed actions, task limits, and failure limits.
- [x] The first production pilot cannot express a direct MERGE action and requires READ, validation, and pull-request creation capabilities.
- [x] Provider policy explicitly permits pre-session fallback while requiring sticky provider identity after a session exists.
- [x] Acceptance checks are deterministic commands with bounded timeouts and unique IDs.
- [x] A pilot contract can be atomically persisted and loaded without normalization drift.
- [x] A read-only preflight proves target repository, base branch, baseline SHA, provider availability, and acceptance-command readiness before any write.
- [x] Human activation is persisted when the contract requires it; absence of activation prevents all target writes.
- [x] A dry-run probe proves path/action enforcement and produces evidence without modifying the target repository.
- [x] One bounded production pilot creates a reviewable pull request against the selected target and passes every declared acceptance check.
- [x] Final pilot evidence records baseline SHA, final head SHA, PR URL, CI evidence, provider identity, and rollback boundary.


## Phase 12 — Production Hardening

- [x] A provider-agnostic execution lease gives each task attempt a unique owner and bounded expiry.
- [x] Duplicate dispatches cannot create a second provider session while a live lease exists.
- [x] An expired lease can be reclaimed deterministically without corrupting task state.
- [x] Lease acquire/renew/release transitions reject stale owners and invalid time movement.
- [x] Transient GitHub/provider failures are distinguished from terminal configuration or safety failures.
- [x] Trusted execution uses bounded retry/backoff for retryable infrastructure failures without duplicating provider sessions.
- [x] A deterministic duplicate-dispatch probe proves at-most-one provider-session creation under CI.
- [x] Fault-injection tests prove safe recovery from controller interruption, API timeout, stale checkpoint, and delayed CI.
- [x] Phase 12 hardening evidence is persisted and all hardening probes pass under CI.


## Phase 13 — Long-running Autonomous Development

- [x] A durable campaign records one goal, its bounded task set, status, and completed progress.
- [x] DAG advancement persists campaign progress with task completion and next-task selection, with deterministic reconciliation after interrupted multi-file updates.
- [x] Restarting the controller from persisted state resumes the same campaign without replaying completed tasks.
- [x] HUMAN_WAIT, FAILED, and BLOCKED descendants stop only the unsafe path and preserve campaign evidence.
- [x] A deterministic long-run probe completes a dependency graph across at least five task transitions with interruption/restart injection.
- [x] A bounded real campaign produces multiple sequential PR/CI cycles without manual dispatch between safe tasks.
- [x] Final campaign evidence records goal, task sequence, PRs, CI, interruptions/recovery, and terminal status.

## Phase 14 — Mission Control / Observability

- [x] A single safe operational snapshot exposes active campaign progress, current task, latest output, retries/recovery, and human-wait state.
- [x] Durable events use stable IDs so controller retries cannot duplicate operator-visible history.
- [x] Campaign and live canonical state are reconciled into one deterministic read model.
- [x] Mission Control clearly distinguishes RUNNING, RECOVERING, HUMAN_WAIT, FAILED, and COMPLETED without provider-session or secret leakage.
- [x] A deterministic observability probe is required by CI and covers artifact reload and secret leakage.
- [x] The cloud Mission Control workflow produces a current artifact from the Phase 14 read model.

## Phase 15 — Autonomous Recovery

- [x] Recovery classification distinguishes CI failure, merge conflict, provider/infrastructure failure, timeout, and invalid implementation.
- [x] Each recoverable failure maps to a bounded retry, repair, rebase, or replan action with explicit budgets.
- [x] Recovery never bypasses trusted scope, acceptance, provenance, lease, or human-decision gates.
- [x] Repeated identical failures terminate or enter HUMAN_WAIT instead of looping indefinitely.
- [x] Restart during recovery preserves the same bounded recovery progress without duplicate provider sessions or duplicate PR actions.
- [x] Deterministic fault scenarios prove CI repair, transient infrastructure retry, merge-conflict handling, and terminal escalation.
- [x] Real campaign `phase15-recovery-campaign-001` demonstrated managed CI failure → durable REPAIR → autonomous repository_dispatch → repaired CI green → trusted merge on PR #94.

## Phase 16 — Goal → Plan → Execution

- [x] A high-level development goal can be converted into a bounded validated task graph without manually authoring each provider prompt.
- [x] Planner output includes explicit acceptance criteria, dependency edges, allowed paths, and human-only boundaries before execution.
- [x] Invalid, cyclic, over-broad, or destructive plans are rejected before provider dispatch.
- [x] Identical normalized goal + bounded work items produce a stable plan fingerprint and accepted-plan reload rejects drift.
- [x] The trusted controller executes an accepted generated plan through the existing campaign/DAG/recovery gates without weakening them.
- [x] Deterministic planning tests prove validation, cycle rejection, scope rejection, stable fingerprints, and compilation.
- [x] Real campaign `phase16-goal-campaign-001` completed two generated tasks through PR #103 and PR #104 with no manually authored provider prompts and no manual dispatch between tasks.

## Phase 17 — Production Graduation

- [x] A production-graduation campaign ran three dependency-linked tasks through trusted PR/CI advancement.
- [x] Graduation evidence binds the real Phase 15 autonomous recovery path plus mandatory restart/resume and HUMAN_WAIT proof gates.
- [x] Duplicate dispatch/session and stale recovery protections remain green under the final CI suite.
- [x] Mission Control observability remains a mandatory green proof and reads the terminal graduation campaign.
- [x] Durable campaign, DAG, structured graduation evidence, acceptance, and roadmap reconcile to the same terminal outcome.
- [x] The final graduation audit reports no unresolved required safety-proof gap across provider routing, lease, CI/recovery, human boundary, restart, observability, and plan execution.
- [x] ADE v1.0 Production Graduation is declared only when the final CI suite and structured graduation audit are green.


## ADE v1.1 — Zero-Touch Start

- [x] A persisted AcceptedPlan with a valid fingerprint is required before any initial Campaign dispatch.
- [x] AcceptedPlan, Campaign, Task DAG, current cycle task, and project state reconcile to the same bounded work before dispatch.
- [x] Persisting the v1.1 AcceptedPlan on main triggered the initial Campaign automatically from a push event without a human GitHub Actions click.
- [x] A 15-minute cloud watchdog is configured, and deterministic stale-receipt proof permits retry only when no live execution or recovery owns the task.
- [x] HUMAN_WAIT, FAILED/BLOCKED state, and unsafe/recovery-owned paths prevent zero-touch start.
- [x] A live execution lease prevents duplicate provider-session creation; a live lease for another task blocks start.
- [x] A non-terminal checkpoint/recovery state never creates a fresh provider session.
- [x] GitHub event replay and duplicate start attempts are suppressed by a durable campaign/task/fingerprint-bound dispatch receipt plus the execution lease.
- [x] A stale dispatch receipt is retryable only when no live lease or current checkpoint/recovery proves work is active or complete.
- [x] Automatic-start decisions produce structured artifact evidence; successful dispatch persists a secret-free audit receipt.
- [x] Mission Control exposes the latest zero-touch receipt without provider-session identifiers or secrets.
- [x] CI contains deterministic Zero-Touch Start, lease, restart, HUMAN_WAIT, recovery, and Mission Control proofs.
- [x] Real Campaign `v1.1-zero-touch-proof-001` completed AcceptedPlan -> automatic push-triggered initial dispatch -> PR #116 -> CI -> trusted merge -> automatic Task 2 dispatch -> PR #117 -> CI -> trusted merge with no manual initial workflow click and no failed tasks.


## ADE v1.2 — Autonomous Planner

- [x] A human can submit only a high-level Goal; per-task Outcome, allowed_paths, Acceptance, and Dependencies are produced by an untrusted planner rather than manually supplied for each task.
- [x] Planner output uses a strict versioned proposal schema and cannot directly mutate AcceptedPlan, Campaign, Task DAG, project state, workflows, or trusted controller files.
- [x] Trusted deterministic validation requires exact Goal binding and rejects malformed, empty, over-budget, cyclic, forward-dependent, or duplicate proposal tasks.
- [x] Trusted policy bounds task count, paths per task, acceptance checks per task, text sizes, and allowed repository path prefixes.
- [x] Planner-proposed paths remain relative, normalized, inside trusted allowed roots, and outside .github/, .autodev/, secret/config, and other protected control paths.
- [x] Trusted validation assigns executable task IDs and provider prompts; the planner cannot choose executable task IDs or inject raw provider control instructions.
- [x] Mandatory human-only boundaries for destructive/irreversible actions, credentials/secrets, and externally consequential side effects are present before acceptance.
- [x] Unsafe/destructive planner proposals are rejected or converted to HUMAN_WAIT before AcceptedPlan creation; they are never silently accepted.
- [x] Only the trusted acceptance boundary can convert a validated planner proposal into a fingerprinted AcceptedPlan.
- [x] Identical normalized Goal + proposal + trusted policy produce the same DevelopmentPlan and AcceptedPlan fingerprint.
- [x] A validated AcceptedPlan compiles through the existing Campaign/DAG path and can enter v1.1 Zero-Touch Start without bypassing any v1.0/v1.1 gates.
- [x] Deterministic CI proofs cover schema rejection, scope rejection, dependency rejection, budget rejection, human-boundary enforcement, stable fingerprinting, and successful compile.
- [x] A real planning provider produces a plan from a high-level Goal without manually authored per-task work items, and the raw planner proposal is preserved as evidence.
- [x] A real external-repository proof completes High-level Goal -> autonomous proposal -> trusted validation -> AcceptedPlan -> automatic Campaign start -> multiple PR/CI/trusted-merge cycles -> terminal Goal Acceptance.

## ADE v1.3 — Repository Intelligence

- [x] Trusted repository reads bind structure discovery to an explicit target repository, base branch, and immutable source SHA.
- [x] Repository paths are normalized, deduplicated, bounded, and unsafe/control-character paths are rejected before planner use.
- [x] A deterministic RepositorySnapshot classifies source roots, test roots, manifests, workflows, and documentation.
- [x] Planner context exposes only bounded file-path metadata within trusted writable roots; file contents and secrets are not included in Slice 001.
- [x] Repository structure is injected into the untrusted planner as data, never as an instruction source, while trusted proposal validation remains authoritative.
- [x] Snapshot and planner-context fingerprints are persisted in repository-intelligence evidence, planner evidence, and project-state metadata.
- [x] CI contains deterministic Repository Intelligence and trusted activation proofs for the structure snapshot path.
- [x] Bounded trusted content summaries identify relevant symbols/modules without exposing secrets or unbounded repository text.
- [x] Repository Intelligence records dependency/import relationships and test-to-source relationships needed for change planning.
- [x] A deterministic impact analysis identifies likely affected files and tests for a proposed change without granting write authority.
- [x] Planner validation can require proposed concrete paths to exist in the trusted repository snapshot unless a task explicitly creates a new file.
- [x] A real external-repository proof demonstrates that repository-aware planning selects grounded implementation/test paths and completes through the existing trusted execution loop.

## ADE v1.4 — Runtime / Deployment Verification

- [x] A versioned RuntimeVerificationContract binds verification to an explicit target repository, exact source SHA, environment, and trusted probe IDs.
- [x] Runtime verification contracts contain no executable command strings, URLs, headers, credentials, or secret-bearing payload surface.
- [x] RuntimeProbeResult evidence is source-SHA-bound, attempt-bounded, and restricted to trusted probe IDs.
- [x] Deterministic evaluation returns PENDING until all required probes report, VERIFIED only when every required probe passes, and FAILED when any required probe fails/errors/skips.
- [x] Unknown probes, duplicate results, stale source SHAs, invalid identifiers, and attempt-budget violations fail closed.
- [x] Contract and report fingerprints are deterministic, and the trusted runtime contract probe is exercised by the mandatory unit-test CI stage.
- [x] A trusted probe registry maps probe IDs to fixed controller-owned implementations; untrusted planner/provider output cannot supply executable probe definitions.
- [x] Post-merge runtime verification automatically binds to the exact trusted merge SHA and persists a durable verification receipt.
- [x] Runtime probes execute with bounded timeouts/retries and cannot expand repository, credential, network, or deployment authority.
- [x] Deployment-aware verification can distinguish repository runtime, preview/staging, and production targets without assuming deployment success from CI success.
- [x] Failed runtime/deployment verification enters bounded recovery or HUMAN_WAIT and never silently marks the Campaign complete.
- [x] A real external-repository proof demonstrates merge -> runtime/deployment verification -> durable VERIFIED evidence through the trusted controller.

## ADE v1.5 — Development Memory

- [x] Development memory records use a strict versioned immutable schema with deterministic fingerprints.
- [x] Every memory record is bound to an explicit repository and source SHA and requires trusted `.autodev/` evidence references plus SHA-256 evidence fingerprints.
- [x] The memory ledger is order-deterministic, duplicate-ID safe, immutable on append, and fingerprinted independently of input ordering.
- [x] Memory statements are bounded single-line facts; control characters, URLs, and common secret/token markers fail closed.
- [x] Planner memory context is repository-filtered and character/record bounded.
- [x] Memory retrieval is deterministic, repository/current-SHA bound, result-bounded, and historical lessons require an explicit trusted relevance signal.
- [x] Memory supplied to planning is explicitly advisory-only and cannot grant execution authority, expand trusted scope, or override Acceptance.
- [x] A deterministic Development Memory proof is mandatory in CI.
- [x] Trusted controller code derives memory records automatically from verified Campaign, recovery, runtime-verification, and human-decision evidence.
- [x] Supersession/conflict handling prevents obsolete or contradicted memory from silently remaining authoritative.
- [x] Autonomous Planner integration consumes bounded memory as data while deterministic trusted proposal validation remains authoritative.
- [x] Runtime Verification feeds verified outcomes and bounded recovery outcomes into an idempotent durable memory store without making memory persistence a runtime-success authority.
- [x] A real external-repository bootstrap proof demonstrates useful memory reuse across later work without scope expansion or manual per-task memory authoring, then persists the verified outcome into the durable memory store.
- [x] A successor real external-repository proof reuses records directly from `.autodev/development-memory.json`, with exact reused record fingerprints persisted before execution and no scope/Acceptance authority gained from memory.
- [x] A dedicated v1.5 Graduation audit proves the trusted memory path end to end, including durable-store reuse rather than bootstrap evidence reuse alone.

## ADE v1.6 — Autonomous Backlog

- [x] Backlog candidates use a strict versioned immutable schema with deterministic fingerprints.
- [x] Every candidate is bound to an explicit repository, source SHA, trusted `.autodev/` evidence paths, and SHA-256 evidence fingerprints.
- [x] The backlog ledger is order-deterministic, duplicate-ID safe, bounded, and fingerprinted independently of insertion order.
- [x] Backlog data explicitly grants no execution authority, no automatic dispatch authority, and no scope-expansion authority.
- [x] Candidate text rejects control characters, URLs, and common secret/token markers; untrusted evidence paths fail closed.
- [x] A deterministic Autonomous Backlog schema proof is mandatory in CI.
- [x] Trusted extraction creates candidates only from controller-verified gaps/outcomes; provider prose cannot directly create executable work.
- [x] Candidate supersession, staleness, deduplication, and deterministic priority are controller-owned and fail closed.
- [x] Eligibility selection is repository/source-SHA bound, excludes human-only work, and selects at most one next Goal candidate.
- [x] Selected candidates become high-level PlanningGoal input only; Autonomous Planner + AcceptedPlan remain the sole task/scope authority.
- [x] Completion feedback retires a candidate only after trusted merge/runtime evidence proves the selected Goal outcome.
- [x] A real external-repository proof demonstrates evidence -> backlog candidate -> selected Goal -> AcceptedPlan -> trusted execution -> verified retirement without manual per-task authoring.
- [x] A dedicated v1.6 Graduation audit proves the Autonomous Backlog path end to end.

## ADE v1.7 — Multi-Agent

- [x] Agent roles use a strict finite versioned enum and serialized multi-agent data carries no execution, auto-dispatch, merge, Acceptance, or scope-expansion authority.
- [x] Every agent assignment is bound to one repository, source SHA, Campaign, task, AcceptedPlan fingerprint, and trusted `.autodev/` evidence.
- [x] Multi-agent plans are deterministic, fingerprinted, bounded to at most three roles, duplicate-role safe, and require exactly one IMPLEMENTER.
- [x] Agent role and provider identity are separate concepts; multiple roles may use one provider without gaining additional authority.
- [x] Unknown fields, authority escalation, cross-task/source trust-anchor drift, unsafe evidence paths, URLs, and secret-like objective text fail closed.
- [x] A deterministic Multi-Agent foundation proof is mandatory in CI.
- [x] Trusted controller logic derives role assignments from an AcceptedPlan and provider availability without accepting provider-authored scope or authority.
- [x] Reviewer/diagnostic contributions are immutable evidence objects and cannot directly mutate code, Campaign state, Acceptance, merge state, or Runtime Verification.
- [x] Conflicting agent contributions are reconciled deterministically by controller policy; unresolved material conflicts enter HUMAN_WAIT rather than majority voting.
- [x] Provider-session lifecycle preserves task/provider affinity, lease safety, quota recovery, and duplicate suppression independently for each role.
- [x] Reviewer CHANGES_REQUIRED feedback can trigger only a bounded controller-owned correction request that reuses the frozen AcceptedPlan scope/Acceptance; reviewer data cannot directly dispatch, expand scope, merge, or approve work, and correction-budget exhaustion enters HUMAN_WAIT.
- [x] A real external-repository proof demonstrates bounded implementer + independent reviewer collaboration through the existing trusted merge/runtime gates.
- [x] A dedicated v1.7 Graduation audit reconstructs the multi-agent proof end to end.

## ADE v1.8 — Autonomous Release Orchestration

- [x] Release candidates use a strict versioned immutable schema with deterministic content-bound IDs and fingerprints.
- [x] Every candidate is bound to an explicit repository, exact source SHA, Campaign, AcceptedPlan fingerprint, Runtime Verification identity, target environment, and trusted .autodev evidence.
- [x] AcceptedPlan, Campaign, and Runtime Verification evidence are mandatory; duplicate evidence kinds, unsafe paths, unknown fields, schema drift, and candidate-ID drift fail closed.
- [x] Serialized release-candidate data grants no deployment, promotion, auto-promotion, scope-expansion, or Acceptance-mutation authority.
- [x] Under the current safety contract every preview, staging, and production promotion remains explicitly human-approval gated.
- [x] A deterministic Autonomous Release Candidate foundation proof is mandatory in CI.
- [x] Trusted controller logic derives a release candidate only from a terminal verified Campaign and exact post-merge Runtime Verification evidence.
- [x] Release policy defines legal preview / staging / production transitions without allowing provider-authored environment or authority changes.
- [x] Externally consequential promotion integrates with the Human Decision Queue and cannot proceed without a matching explicit approval.
- [x] Trusted deployment adapters are controller-owned, idempotent, source-SHA-bound, and duplicate-suppressed.
- [x] Every completed promotion is followed by exact-deployment Runtime Verification; failure triggers bounded containment or HUMAN_WAIT instead of silent success.
- [x] Mission Control exposes release-candidate, approval, promotion, verification, and containment state without secrets or deployment credentials.
- [x] A real external-repository proof demonstrates verified Campaign -> release candidate -> approved promotion -> post-promotion Runtime Verification.
- [x] A dedicated v1.8 Graduation audit reconstructs the release proof end to end.

## ADE v1.9 — Continuous Improvement Loop

- [x] Improvement signals use a strict versioned immutable schema with deterministic content-bound IDs and fingerprints.
- [x] Every signal is bound to one repository, exact release source SHA, ReleaseCandidate identity, release environment, and trusted .autodev evidence.
- [x] Release evidence and post-promotion verification evidence are mandatory; duplicate evidence kinds, unsafe paths, unknown fields, and schema drift fail closed.
- [x] Signal statements/tags are bounded and reject control characters, URLs, common secret markers, duplicate tags, and unsafe evidence paths.
- [x] Improvement lineage is explicit and generation-bounded; root/successor parent rules fail closed before later loop orchestration is introduced.
- [x] Serialized signals grant no planning, execution, auto-dispatch, release, scope-expansion, Acceptance-mutation, or human-decision authority, and a deterministic foundation proof is mandatory in CI.
- [x] Trusted feedback extraction creates signals only from controller-verified release/runtime/recovery/telemetry evidence; a successful release alone cannot fabricate an actionable development gap.
- [x] Signal resolution, deduplication, supersession, cooldown, and lineage-cycle limits are controller-owned and deterministic.
- [x] Actionable signals can feed Development Memory and Autonomous Backlog without bypassing existing Backlog resolution/selection authority.
- [ ] At most one eligible successor PlanningGoal is handed off per loop cycle, with bounded cycle budgets and no automatic execution authority gained from signal existence.
- [ ] Verified successor outcomes retire or supersede their originating signal lineage so identical improvements cannot recur forever.
- [ ] Mission Control exposes safe Continuous Improvement state without raw telemetry, provider sessions, credentials, or hidden control payloads.
- [ ] A real external-repository proof demonstrates verified release -> trusted improvement signal -> backlog/PlanningGoal -> trusted execution -> verified outcome without manual per-task authoring.
- [ ] A dedicated v1.9 Graduation audit reconstructs the Continuous Improvement proof end to end.
