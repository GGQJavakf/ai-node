## Why

Completed Codex sessions currently disappear into history instead of becoming durable, evidence-backed knowledge. AgentRetro adds a safe retrospective path that reduces repeated context gathering while preserving the existing `ai-todo` product and giving users a human-readable Obsidian view of accepted knowledge.

## What Changes

- Add an independent `retro` CLI and `agent_retro` package alongside the existing `ai-todo` entry point.
- Capture one completed local Codex session on explicit request, normalize it, redact secrets, and retain minimal traceable evidence.
- Extract and independently review `RULE`, `LESSON`, and `TASK_STATE` candidates, with conservative automatic-acceptance thresholds and deterministic safety gates.
- Store review state, accepted knowledge, conflicts, audit history, and synchronization state in a user-level SQLite database.
- Commit accepted knowledge to SQLite and then attempt one same-command, preflight-gated synchronization into three managed Obsidian aggregate files and bounded summary blocks, retaining `sync_pending` when the vault is unavailable or unsafe.
- Provide audited project mapping and reclassification commands so unknown or ambiguous sessions have a recoverable user path.
- Provide idempotent model-review retry and an explicitly confirmed sensitive purge that covers every verifiable AgentRetro-owned copy, including affected backups.
- Generate a deterministic, token-bounded task-scoped `retro brief` for later Codex work and provide an explicit preview/apply/remove integration for canonical global Codex guidance.
- Preserve all existing Todo, WorkItem, command, configuration, and database semantics; no legacy data migration is introduced.

## Capabilities

### New Capabilities

- `codex-session-retrospective`: Explicit, idempotent, bounded capture and normalization of completed local Codex sessions with managed project mappings, evidence references, and redaction.
- `retrospective-knowledge-review`: Candidate extraction, independent review and retry, deterministic auto-acceptance gates, lifecycle management, conflicts, expiry, sensitive purge, and auditability.
- `obsidian-knowledge-sync`: Same-command three-file project projection, managed summary boundaries, synchronization journaling, external-edit detection, controlled deep merge, and rollback.
- `retrospective-briefing`: Deterministic accepted-knowledge selection, token-bounded task briefs, health diagnostics, and previewed canonical global AGENTS integration.

### Modified Capabilities

None. Existing capability requirements remain unchanged.

## Impact

- Adds a new package under `src/agent_retro/`, a new `retro` console script, and dedicated tests.
- Adds user-local state under `<user-home>/.agentretro/` and optional writes under a user-configured Obsidian vault.
- Adds audited project mapping, review-attempt, purge-plan, and scenario-verification state without sharing legacy business tables.
- Reuses the existing model configuration and LLM client through one read-only adapter; no model credentials are copied into AgentRetro storage.
- May include a narrowly scoped Windows console-encoding compatibility fix, with no Todo or WorkItem behavior change.
- Adds no ORM, vector database, background service, web UI, or legacy database migration.
- Enforces configurable discovery, source-size, model-request, and local-render limits with diagnostic failures and no partial state.
