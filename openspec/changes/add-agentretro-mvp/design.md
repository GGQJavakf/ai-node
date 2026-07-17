## Context

The repository currently ships `ai-todo`, a local Todo and WorkItem assistant. Its existing Codex integration can resume work and ingest generated task reports, but it does not parse completed local sessions into evidence-backed knowledge. AgentRetro is a sibling product, not an extension of the existing Todo domain.

The user also maintains an Obsidian vault with project pages, an index, a log, and explicit rules for source attribution, conflict handling, and progressive loading. AgentRetro must use that structure without treating user-authored notes as an unbounded writable document store.

The main constraints are:

- preserve every existing `ai-todo` behavior and data contract;
- support Python 3.10 and Windows consoles;
- add no ORM, vector database, web service, or background process;
- never copy complete session transcripts or persist credentials;
- keep Obsidian and global Codex writes explicit, bounded, auditable, and reversible.

## Goals / Non-Goals

**Goals:**

- Add an independent `retro` CLI with explicit completed-session capture.
- Produce traceable `RULE`, `LESSON`, and `TASK_STATE` knowledge.
- Allow conservative high-confidence automatic acceptance with deterministic gates.
- Maintain SQLite review state and a readable Obsidian projection.
- Generate bounded task context for later Codex work.
- Provide deterministic recovery for database, vault, merge, and global-guidance writes.

**Non-Goals:**

- Other agent sources, hooks, watchers, Web/GUI/MCP surfaces, embeddings, clustering, or vector search.
- Legacy Todo/WorkItem migration or shared business tables.
- Automatic deep editing, deletion, rename, or movement of user-authored notes.
- Replacing or editing Codex native memory state.

## Decisions

### Independent package and entry point

Add `retro = agent_retro.presentation.cli:main` and keep `ai-todo` unchanged. `agent_retro` owns separate domain, application, infrastructure, and presentation modules.

The only cross-product seam is a read-only model adapter that retrieves the existing model configuration and delegates to the existing LLM client. It exposes only the fields needed for model calls and never serializes the API key.

**Alternative rejected:** adding `/retro` commands to the existing interactive CLI. That would increase an already broad command surface, couple two domains, and make failures in the new persistence path capable of breaking the original product.

### SQLite authority with an Obsidian projection

Use `<user-home>/.agentretro/retro.db` as the authority for session hashes, evidence, review state, accepted knowledge, conflicts, audit history, and sync state. Project knowledge is projected into three Obsidian files for reading and linking.

`retro brief` reads SQLite so a temporary vault sync failure cannot feed stale task state to Codex. Manual edits to managed vault content are detected by hash and require explicit reconciliation.

**Alternatives rejected:** Markdown-only storage cannot safely represent review and rollback state; database-only storage does not meet the human-readable Obsidian requirement; silent bidirectional sync risks data loss.

### Explicit completed-session capture

Support only `retro capture --last` and `retro capture --session <id>`. Discover sessions from the real local Codex home, reject active sessions, and identify the project from Git root, normalized remote, and explicit local mappings.

The parser stores a source locator, content hash, and minimal redacted excerpt rather than a full transcript. Session ID, event locator, and content hash make capture idempotent.

**Alternative rejected:** hooks and background watchers introduce hidden resource use, partial-session races, and implicit data processing before the MVP has proven value.

### Two-stage review plus deterministic gates

The extraction pass proposes typed candidates and evidence. A separate review pass returns verdict, confidence, reason, normalized text, duplicate assessment, and conflict assessment. Deterministic gates run after the review result.

Automatic acceptance thresholds are `RULE >= 0.97`, `LESSON >= 0.93`, and `TASK_STATE >= 0.90`. Secrets, inadequate evidence, unknown projects, duplicates, conflicts, speculation, unauthoritative rules, or unverified lessons block automatic acceptance regardless of confidence.

**Alternatives rejected:** a single model call lets the producer judge itself; rules-only review cannot reliably normalize semantic lessons; fully automatic acceptance lacks the required safety boundary.

### Type-specific lifecycle

`RULE` requires an explicit authoritative source. `LESSON` requires failure, correction, and successful verification evidence. `TASK_STATE` expires after 14 days by default. Project scope is default and global promotion is explicit.

Conflicts never overwrite active knowledge. The old item stays active while the new item remains pending with a merge proposal.

### Three-file Obsidian projection

Each mapped project receives `规则.md`, `经验.md`, and `任务状态.md` under its `AgentRetro` directory. Automatic synchronization may update those files, a marked project-summary block, a marked index-link block, and append-only AgentRetro log entries.

Automatic synchronization must preserve all content outside managed markers byte-for-byte. User-authored prose outside those markers is modified only by an explicitly applied, hash-bound merge plan.

**Alternative rejected:** one file per item creates unnecessary vault noise; directly merging every accepted item into existing notes makes review and rollback ambiguous.

### Journaled multi-file synchronization

Before writing, compute pre-write hashes and back up every target under `<user-home>/.agentretro/backups/<run-id>/`. Write same-directory temporary files, replace targets, read them back, and verify hashes and markers. Any failure restores all pre-write files. Restoration failure enters `rollback_required` and blocks later syncs.

SQLite acceptance is not rolled back when Obsidian is unavailable. The knowledge remains accepted with `sync_pending` and can be retried.

### Previewed deep merge and Codex integration

`retro merge plan` and `retro integrate codex` are preview-only by default. Deep merge requires `retro merge apply <plan-id>` with matching source hashes. Global guidance requires `retro integrate codex --apply`, writes one managed block, and supports managed-block removal.

Neither path can use force overwrite in the MVP. Any unexpected external edit invalidates the operation.

### Bounded briefing

`retro brief` selects active project rules, relevant lessons, current task state, and explicitly global knowledge. It excludes pending, rejected, conflicting, archived, and expired items, includes evidence references and health warnings, and defaults to approximately 6000 tokens.

### Standard-library persistence and Windows-safe output

Use `sqlite3` and the current dependency set. Do not add an ORM. Keep Python 3.10 compatibility and ensure the new CLI renders under both Windows GBK and UTF-8 consoles. Any existing CLI encoding fix must remain a separate compatibility patch with no Todo/WorkItem semantic change.

## Risks / Trade-offs

- **Model false positives** -> Use independent review, conservative type thresholds, hard evidence gates, manual correction, and audit records.
- **Codex session format drift** -> Isolate parsing behind a source adapter, retain versioned fixtures, ignore unknown optional events, and fail closed on missing identity fields.
- **Legacy configuration coupling** -> Limit coupling to one read-only adapter and keep capture/brief usable when the model client is unavailable.
- **Obsidian external edits** -> Compare managed-block hashes, stop before overwrite, and require reconciliation.
- **Filesystem transactions are not truly atomic across files** -> Use backups, a SQLite journal, same-directory replace, readback, and all-file restoration.
- **Context bloat** -> Apply project/type/status filtering and a configurable 6000-token default budget.
- **Stale task state** -> Expire `TASK_STATE` after 14 days and surface stale records only through explicit history views.
- **Sensitive session content** -> Redact before model input and persistence, store minimal excerpts, and treat captured text as untrusted data.

## Migration Plan

1. Add the independent package, console script, user-local configuration, and versioned empty database.
2. Add capture and review without enabling any Obsidian or global Codex write automatically.
3. Configure one Obsidian project mapping and verify synchronization against a temporary vault before real-vault use.
4. Enable automatic projection only for accepted knowledge after doctor checks pass.
5. Keep global Codex guidance unmodified until the user previews and explicitly applies the managed block.

There is no legacy data migration. Uninstalling AgentRetro leaves existing `ai-todo` data untouched. Rollback consists of removing the console package, removing the managed Codex block through the integration command, and restoring vault files from the recorded run backup when necessary. User-local AgentRetro data and vault knowledge are retained unless the user explicitly deletes them.

## Open Questions

None. Product scope, review thresholds, storage roles, Obsidian layout, merge authority, Codex integration, and verification strategy were explicitly confirmed before this change was created.
