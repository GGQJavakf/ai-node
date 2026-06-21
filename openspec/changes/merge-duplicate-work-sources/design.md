## Context

The workflow assistant currently stores a WorkItem with a single `source` and `source_ref`. Import paths use exact `(source, source_ref)` lookup, so the same work can become several active WorkItems when:

- Codex reports mention a Redmine issue id in `title`, `source_ref`, or `next_action` while Redmine import stores `source=redmine` and `source_ref=<id>`.
- Codex reports track an OpenSpec change by thread id while project sync also sees the OpenSpec change name.
- A GitLab MR id or Codex thread id appears in a title or next action before a dedicated source record exists.

The new behavior must remain local and reversible. External connectors stay read-only, and legacy records without the new metadata must still load.

## Goals / Non-Goals

**Goals:**

- Represent stable source identities independently from the WorkItem's primary `source/source_ref`.
- Merge exact stable identity matches automatically during import and sync.
- Keep all source refs and evidence from every merged source.
- Make ambiguous matches visible but require manual confirmation before merging.
- Provide a rollback or manual split path for mistaken merges.
- Keep `/list` and `/work status` from repeating the same real work item.
- Make `/sync` summarize `merged`, `created`, `updated`, and `skipped`.

**Non-Goals:**

- Do not write to Redmine, GitLab, OpenSpec, Playbook, or Codex.
- Do not implement fuzzy natural-language title similarity as an automatic merge key.
- Do not delete legacy WorkItems as the primary merge mechanism.
- Do not hide evidence or source refs that disagree after a merge.
- Do not require a destructive one-way database migration.

## Decisions

### 1. Use canonical source identities as the merge key

Each incoming source observation is normalized into zero or more canonical identities:

- `redmine:<issue_id>` from explicit Redmine imports and from patterns such as `Redmine 12345`, `#12345` only when accompanied by Redmine context, `issue 12345`, or configured Playbook Redmine facts.
- `openspec:<change_id>` from explicit OpenSpec change names matching the OpenSpec-safe identifier pattern.
- `gitlab-mr:<project_or_unknown>:<mr_id>` from MR URLs or `MR !123` style references; if no project is available, use `gitlab-mr:unknown:<mr_id>` and treat collisions across project paths as ambiguous.
- `codex-thread:<thread_id>` from Codex `thread_id` values or source refs that match the thread-id format.

Rationale: Stable external identifiers survive title edits and next-action rewrites. Free-text title similarity is useful for suggestions but too risky for automatic merges.

Rejected alternative: Use normalized title text as the primary key. It would merge unrelated tasks with similar titles and cannot support reliable rollback.

### 2. Store source refs as append-only identity metadata

Extend WorkItem persistence with compatible metadata rather than replacing the existing `source/source_ref` fields. Existing fields remain as the primary display source for old callers. New metadata should capture:

- canonical identities currently associated with the WorkItem;
- observed source refs and source-specific labels;
- merge audit entries recording merged WorkItem ids, previous primary fields, timestamp, reason, and source identity;
- conflict flags for ambiguous or contradictory observations.

Rationale: This preserves compatibility with current JSON/SQLite records and lets the UI show the original source while still de-duplicating by stable identity.

Rejected alternative: Create a separate SourceIdentity aggregate immediately. It may be cleaner long term, but it increases migration scope before the current local assistant needs it.

### 3. Automatic merge only for exact stable identity matches

An incoming observation SHALL automatically merge into an existing WorkItem only when at least one canonical identity exactly matches a non-closed WorkItem in the same project scope or in an explicitly global source scope.

Priority when merging fields:

1. Status: `done` wins only when the incoming source is an explicit completed Codex entry or another completion signal; otherwise keep `blocked` over `active`, and never reopen `done` automatically.
2. Priority: keep the highest priority using `high > medium > low`.
3. Title: keep a human-authored or Redmine title over a generic Codex/thread title; otherwise prefer the latest non-empty specific title.
4. Next action: prefer the latest non-empty actionable next action from Codex, then manual, then connector summary.
5. Project path: prefer an exact non-empty path; if two non-empty paths differ, keep the existing path and record a conflict/evidence note.
6. Sync summary: append or summarize source-specific details without discarding the previous summary.

Rationale: Merge behavior should reduce duplicates while preserving the user's most actionable local view.

Rejected alternative: Let the latest import blindly overwrite all fields. That would lose manual priority/status decisions and make imports surprising.

### 4. Ambiguous matches require manual confirmation

The system SHALL skip automatic merging and mark a candidate for manual confirmation when:

- only a title similarity or weak numeric id hint exists;
- the same non-namespaced MR id appears in different project paths;
- multiple active WorkItems share the same candidate identity because of legacy data;
- an incoming observation would merge two closed/done histories into an active work item;
- source facts conflict on project path or source type in a way that changes user intent.

Rationale: Preventing false merges is more important than maximizing automatic cleanup.

Rejected alternative: Always pick the newest candidate. That hides data conflicts and makes mistaken merges harder to notice.

### 5. Rollback uses merge audit and manual split

Every automatic merge SHALL record enough audit data to restore the previous separate WorkItem or at least allow a deterministic manual split:

- previous WorkItem ids and serialized field snapshots;
- identities moved into the survivor;
- evidence ids added during merge;
- timestamp and merge reason.

Rationale: Local mistakes are acceptable only if the user can undo or split them without external data loss.

Rejected alternative: Only keep a text note saying a merge happened. That is not enough to reconstruct source refs or evidence ownership.

## Risks / Trade-offs

- [Risk] Legacy JSON/SQLite records do not have identity metadata -> Mitigation: load missing fields with empty defaults and backfill identities lazily during import/list/sync.
- [Risk] Redmine ids in arbitrary text may be false positives -> Mitigation: require Redmine context before treating a bare number as `redmine:<id>`.
- [Risk] MR ids are not globally unique -> Mitigation: namespace by project path or remote URL when available; otherwise mark cross-project matches ambiguous.
- [Risk] Merged WorkItems can obscure conflicting statuses -> Mitigation: deterministic field priority plus conflict evidence instead of silent overwrite.
- [Risk] Rollback implementation can grow too broad -> Mitigation: first support local manual split/undo from recorded merge audit; defer advanced interactive conflict UI.

## Migration Plan

1. Add compatible metadata fields or repository-level metadata storage with defaults for old records.
2. Backfill canonical identities from existing `source/source_ref/title/next_action` when a WorkItem is loaded or before import matching.
3. Preserve existing WorkItem ids when a duplicate is absorbed; do not delete data without writing a merge audit entry.
4. Add a split/rollback operation that can recreate absorbed WorkItems from merge audit snapshots and move selected source refs/evidence back.
5. Validate JSON and SQLite repositories can read pre-change records.

Rollback strategy: if the feature misbehaves, disable identity-based merging and use merge audit records to manually split affected local WorkItems. Because external connectors remain read-only, rollback is local to workflow storage.

## Open Questions

- Whether the first implementation exposes rollback as a CLI subcommand, an internal service method covered by tests, or both. At minimum the service-level manual split/rollback path must exist and be documented.
- Whether project scoping should prefer normalized filesystem path, git remote URL, or both for MR identities. The safe default is path when remote URL is unavailable.
