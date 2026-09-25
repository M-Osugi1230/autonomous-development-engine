# ADE Goal

Build a cloud-first autonomous development engine that can continue software development across hours, days, and quota pauses without depending on a user's local compute or on chat-session memory.

The engine must:

1. Read an explicit project goal and acceptance criteria.
2. Select or receive a bounded development task.
3. Delegate coding work through a replaceable AI provider.
4. Validate results with deterministic CI.
5. Persist progress, failures, and decisions in the repository.
6. Pause safely on quota exhaustion, destructive ambiguity, or human-only decisions.
7. Resume from persisted state.
8. Stop only when acceptance criteria are met or a human decision is required.

The v0 proof is successful when ADE can complete at least two sequential development cycles without a human sending a "continue" instruction between them.
