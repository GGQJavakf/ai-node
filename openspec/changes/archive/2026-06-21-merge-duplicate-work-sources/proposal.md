## Why

Codex reports, Redmine imports, OpenSpec changes, MR references, and manual follow-up notes can describe the same piece of work through different fields, which currently creates duplicate WorkItems in `/list` and splits evidence across records. This change introduces stable work-source identity and deterministic merge behavior so the local assistant can keep one actionable WorkItem per real work item while preserving all observed sources.

## What Changes

- Add a unified source identity capability for WorkItems.
- Detect duplicate work sources from explicit `source_ref` values and from Redmine/OpenSpec/MR/thread identifiers embedded in Codex titles, Codex source references, and `next_action`.
- Merge or associate matching sources into one WorkItem instead of displaying duplicate active items.
- Preserve every contributing source reference and evidence entry when a merge occurs.
- Return a `/sync` merge summary with `merged`, `created`, `updated`, and `skipped` counts.
- Provide a manual confirmation boundary for ambiguous matches and a rollback path for mistaken merges.
- Keep external systems read-only; this change only updates local workflow records and local evidence.

## Capabilities

### New Capabilities

- `work-source-identity`: Defines stable identity extraction, duplicate detection, source-reference preservation, merge conflict behavior, `/list` de-duplication, `/sync` summaries, and manual rollback/split expectations for local WorkItems.

### Modified Capabilities

- None.

## Impact

- Affected domain model: `src/ai_todo_assistant/domain/workflow.py` may need multi-source identity metadata or compatible extension fields.
- Affected services: `WorkItemService.import_codex_report`, `WorkItemService.import_from_snapshot`, `WorkflowSyncService.import_redmine`, and project sync persistence in `src/ai_todo_assistant/application/workflow/services.py`.
- Affected persistence: JSON and SQLite workflow repositories may need schema-compatible storage for source refs, merge audit records, or split/rollback metadata.
- Affected CLI: `/list`, `/work status`, `/codex tasks`, and `/sync` output should display one WorkItem per real work item and report merge statistics.
- Affected tests: workflow service tests, repository compatibility tests, CLI command tests, and OpenSpec validation.
- No new external dependencies, no Redmine/GitLab/OpenSpec write operations, and no production data migration.
