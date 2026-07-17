## Why

Completed Codex sessions currently disappear into history instead of becoming durable, evidence-backed knowledge. AgentRetro adds a safe retrospective path that reduces repeated context gathering while preserving the existing `ai-todo` product and giving users a human-readable Obsidian view of accepted knowledge.

## What Changes

- Add an independent `retro` CLI and `agent_retro` package alongside the existing `ai-todo` entry point.
- Capture one completed local Codex session on explicit request, normalize it, redact secrets, and retain minimal traceable evidence.
- Extract and independently review `RULE`, `LESSON`, and `TASK_STATE` candidates, with conservative automatic-acceptance thresholds and deterministic safety gates.
- Store review state, accepted knowledge, conflicts, audit history, and synchronization state in a user-level SQLite database.
- Synchronize accepted project knowledge into three managed Obsidian aggregate files and bounded summary blocks with transactional backup, verification, and rollback.
- Generate a task-scoped `retro brief` for later Codex work and provide an explicit preview/apply/remove integration for global Codex guidance.
- Preserve all existing Todo, WorkItem, command, configuration, and database semantics; no legacy data migration is introduced.

## Capabilities

### New Capabilities

- `codex-session-retrospective`: Explicit, idempotent capture and normalization of completed local Codex sessions with project routing, evidence references, and redaction.
- `retrospective-knowledge-review`: Candidate extraction, independent review, deterministic auto-acceptance gates, lifecycle management, conflicts, expiry, and auditability.
- `obsidian-knowledge-sync`: Three-file project projection, managed summary boundaries, synchronization journaling, external-edit detection, controlled deep merge, and rollback.
- `retrospective-briefing`: Accepted-knowledge selection, token-bounded task briefs, health diagnostics, and previewed Codex guidance integration.

### Modified Capabilities

None. Existing capability requirements remain unchanged.

## Impact

- Adds a new package under `src/agent_retro/`, a new `retro` console script, and dedicated tests.
- Adds user-local state under `<user-home>/.agentretro/` and optional writes under a user-configured Obsidian vault.
- Reuses the existing model configuration and LLM client through one read-only adapter; no model credentials are copied into AgentRetro storage.
- May include a narrowly scoped Windows console-encoding compatibility fix, with no Todo or WorkItem behavior change.
- Adds no ORM, vector database, background service, web UI, or legacy database migration.
