## Context

The repository currently ships `ai-todo`, a local Todo and WorkItem assistant. Its existing Codex integration can resume work and ingest generated task reports, but it does not parse completed local sessions into evidence-backed knowledge. AgentRetro is a sibling product, not an extension of the existing Todo domain.

The user also maintains an Obsidian vault with project pages, an index, a log, and explicit rules for source attribution, conflict handling, and progressive loading. AgentRetro must use that structure without treating user-authored notes as an unbounded writable document store.

The main constraints are:

- preserve every existing `ai-todo` behavior and data contract;
- support Python 3.10 and Windows consoles;
- add no ORM, vector database, web service, or background process;
- never copy complete session transcripts or persist credentials;
- keep Obsidian and global Codex writes explicit, bounded, auditable, and reversible;
- make project classification, temporary model failure, and synchronization failure recoverable through explicit CLI actions;
- keep brief selection deterministic and local, with configured performance boundaries.

## Goals / Non-Goals

**Goals:**

- Add an independent `retro` CLI with explicit completed-session capture.
- Produce traceable `RULE`, `LESSON`, and `TASK_STATE` knowledge.
- Allow conservative high-confidence automatic acceptance with deterministic gates.
- Maintain SQLite review state and a readable Obsidian projection.
- Generate bounded task context for later Codex work.
- Provide deterministic recovery for database, vault, merge, and global-guidance writes.
- Provide deterministic recovery for unknown project mappings and failed model reviews.

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

The parser stores a source locator, content hash, and minimal redacted excerpt rather than a full transcript. Session ID, event locator, and content hash make capture idempotent. It streams JSONL and enforces configurable discovery count/deadline and source-size limits; limit failures create no partial state.

**Alternative rejected:** hooks and background watchers introduce hidden resource use, partial-session races, and implicit data processing before the MVP has proven value.

### Audited project mapping lifecycle

Store resolved Git root, normalized remote identity, and Obsidian project target in SQLite. Provide `retro project map/list/remove/reclassify`. Unknown or ambiguous sessions remain awaiting classification; reclassification reuses captured evidence rather than recapturing the source. Removing a mapping stops future routing and projection but does not delete knowledge or vault files.

**Alternatives rejected:** mutable JSON mapping has weak validation and auditability; inference-only routing leaves no recovery path for ambiguous worktrees or remote changes.

### Two-stage review plus deterministic gates

The extraction pass proposes typed candidates and evidence. A separate review pass returns verdict, confidence, reason, normalized text, duplicate assessment, and conflict assessment. Deterministic gates run after the review result.

Automatic acceptance thresholds are `RULE >= 0.97`, `LESSON >= 0.93`, and `TASK_STATE >= 0.90`. Secrets, inadequate evidence, unknown projects, duplicates, conflicts, speculation, unauthoritative rules, or unverified lessons block automatic acceptance regardless of confidence.

When model review fails, `retro review retry` creates a new audited review attempt over the same stored redacted candidate/evidence. Candidate ID plus review-input hash makes retry idempotent; extraction and evidence are never repeated.

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

Every committed transition that changes a project projection—automatic/manual acceptance, edit, reviewed vault adoption, conflict resolution, archive, or completed purge—creates one deterministic event. The initiating command commits SQLite and then attempts one synchronous batched projection. Failed preflight or apply records `sync_pending`; retrying the same event produces identical target bytes and no duplicate log entry.

### Explicit initialization of optional managed boundaries

Keep missing or malformed managed boundaries fail-closed during automatic projection. Provide `retro sync init --project <project>` as a zero-write preview for existing optional project-summary and project-index pages, and require `--apply <plan-id>` to initialize the exact current plan. The deterministic plan ID binds project identity, canonical relative paths, target existence, pre-write hashes, and planned hashes, so a separate CLI invocation can reject stale previews without persisting preview state.

Initialization appends only an empty managed block, preserves all existing bytes, and never creates a missing optional note. Partial, duplicate, nested, mismatched, foreign-project, non-UTF-8, non-regular, traversal, or symlinked targets invalidate the entire plan. Apply backs up all existing targets, uses same-directory replacement and exact readback, restores all changed targets on failure, and exposes `rollback_required` if restoration cannot be verified. It does not alter SQLite knowledge or candidate state; the existing explicit `retro sync retry <event-id>` performs the later projection.

**Alternatives rejected:** silently creating markers during automatic projection would broaden a knowledge transition into an unreviewed user-note edit; manual marker insertion lacks hash fencing, backup, and readback; a SQLite-only workaround leaves the human-readable projection permanently stale.

### Sensitive purge supersedes backup retention

Ordinary removals archive content and ordinary backups remain until explicit cleanup. Sensitive purge first generates an immutable impact plan over SQLite, audit detail, managed vault content, AgentRetro logs/traces, and affected migration/sync/merge backups. Apply requires exact confirmation for every operation and leaves only a content-free, non-reversible tombstone. Any known copy that cannot be removed or verified yields `purge_incomplete`; copies outside AgentRetro provenance are disclosed as residual risk rather than claimed as deleted.

### Previewed deep merge and Codex integration

`retro merge plan` and `retro integrate codex` are preview-only by default. Deep merge requires `retro merge apply <plan-id>` with matching source hashes. Global guidance resolves only `<effective-codex-home>/AGENTS.md`; `--apply` writes one managed block and supports managed-block removal. Missing-file creation must appear in preview. Any `AGENTS.override.md`, path/symlink escape, or stale target hash blocks apply and removal. Successful apply preserves encoding/newlines outside the block, reads back, and runs a non-writing discoverability smoke.

Neither path can use force overwrite in the MVP. Any unexpected external edit invalidates the operation.

### Bounded briefing

`retro brief` selects active project rules, explicitly global rules, current task state, and relevant lessons. Lesson relevance is local and deterministic: Unicode normalization, CJK/Latin token overlap, fixed recency and evidence-quality weights, then stable knowledge ID tie-break. It excludes pending, rejected, conflicting, archived, and expired items, includes evidence references and health warnings, and defaults to approximately 6000 tokens estimated conservatively from UTF-8 bytes. Items are never partially truncated; rules that alone exceed the budget cause a diagnostic failure rather than silent omission.

### Standard-library persistence and Windows-safe output

Use `sqlite3` and the current dependency set. Do not add an ORM. Keep Python 3.10 compatibility and ensure the new CLI renders under both Windows GBK and UTF-8 consoles. Any existing CLI encoding fix must remain a separate compatibility patch with no Todo/WorkItem semantic change.

Defaults are configurable: inspect the newest 1000 candidate session files within 10 seconds, reject one source session above 128 MiB, inherit the filtered existing model timeout or use 120 seconds, and stop local brief rendering after 5 seconds. Crossing a limit returns a stable diagnostic and creates no partial capture, review acceptance, or projection state.

## Risks / Trade-offs

- **Model false positives** -> Use independent review, conservative type thresholds, hard evidence gates, manual correction, and audit records.
- **Codex session format drift** -> Isolate parsing behind a source adapter, retain versioned fixtures, ignore unknown optional events, and fail closed on missing identity fields.
- **Legacy configuration coupling** -> Limit coupling to one read-only adapter and keep capture/brief usable when the model client is unavailable.
- **Obsidian external edits** -> Compare managed-block hashes, stop before overwrite, and require reconciliation.
- **Existing Obsidian pages lack markers** -> Preview exact marker initialization, bind apply to current hashes, back up all targets, and retry projection separately.
- **Filesystem transactions are not truly atomic across files** -> Use backups, a SQLite journal, same-directory replace, readback, and all-file restoration.
- **Context bloat** -> Apply project/type/status filtering and a configurable 6000-token default budget.
- **Stale task state** -> Expire `TASK_STATE` after 14 days and surface stale records only through explicit history views.
- **Sensitive session content** -> Redact before model input and persistence, store minimal excerpts, and treat captured text as untrusted data.
- **Incomplete sensitive erasure** -> Plan all known AgentRetro-owned copies, require exact confirmation, verify every location, and report `purge_incomplete` rather than success.
- **Ambiguous project identity** -> Persist audited mappings and expose explicit reclassification without recapture.
- **Non-deterministic context selection** -> Use fixed local scoring, stable tie-breaks, conservative budget estimation, and golden fixtures.
- **Large local history or slow model** -> Stream source data, enforce configurable limits/timeouts, and fail with recovery guidance.

## Migration Plan

1. Add the independent package, console script, user-local configuration, and versioned empty database.
2. Add capture and review without enabling any Obsidian or global Codex write automatically.
3. Configure one audited Obsidian project mapping and verify map/list/remove/reclassify against temporary Git roots and a temporary vault.
4. Enable same-command automatic projection only for accepted or otherwise projection-changing knowledge after doctor checks pass; preserve SQLite and record `sync_pending` on failure.
5. Verify sensitive purge against synthetic copies in every AgentRetro-owned storage class before permitting real use.
6. Keep global Codex guidance unmodified until the user previews the canonical target and explicitly applies the managed block; refuse when an override file exists.

There is no legacy data migration. Uninstalling AgentRetro leaves existing `ai-todo` data untouched. Rollback consists of removing the console package, removing the managed Codex block through the integration command, and restoring vault files from the recorded run backup when necessary. User-local AgentRetro data and vault knowledge are retained unless the user explicitly archives or purges them. Purge is intentionally irreversible for the confirmed AgentRetro-owned copies it removes.

## Open Questions

None. Product scope, review thresholds, storage roles, Obsidian layout, merge authority, Codex integration, and verification strategy were explicitly confirmed before this change was created.
