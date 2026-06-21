## Why

`ai-node` already ingests Codex reports, project Git/OpenSpec/Playbook snapshots, and WorkItem Evidence, but it does not yet turn closeout-specific facts into local actionable gaps. The default `/list` can show a `waiting closeout` group only when gap wording is already present in a WorkItem field. Daily delivery work needs the assistant to surface common closeout mismatches such as merged MRs with still-open Redmine issues, resolved Redmine issues without local validation evidence, and completed OpenSpec changes that are not archived.

This change adds read-only closeout context so `/sync` can capture local Evidence for Redmine/MR/OpenSpec closeout gaps and `/list` can show those gaps without writing external systems.

## What Changes

- Parse existing read-only Playbook, Git, and OpenSpec snapshots for closeout facts and gaps.
- Append concise local Evidence records for detected closeout gaps or connector failure summaries.
- Associate closeout gap Evidence with matching WorkItems by stable identities such as `redmine:<id>`, `gitlab-mr:<project>:<iid>`, and `openspec:<change>` when possible.
- Fall back to the project sync context WorkItem when a gap cannot be safely mapped to a specific WorkItem.
- Make default `/list` reason detection consume local Evidence summaries in addition to WorkItem fields.
- Keep connector and CLI behavior non-blocking when Playbook/OpenSpec/Git are missing, fail, or return unexpected data.

## Capabilities

### Modified Capabilities

- `workflow-source-connectors`: Clarifies closeout context parsing, read-only command boundaries, and failure snapshots.
- `work-evidence-journal`: Adds local closeout gap Evidence requirements.
- `daily-work-triage`: Extends `/list` closeout reasons to use locally persisted Evidence.

## Impact

- Affected code:
  - `src/ai_todo_assistant/infrastructure/connectors/*.py` for closeout-friendly JSON parsing helpers if needed.
  - `src/ai_todo_assistant/application/workflow/services.py` for snapshot-to-Evidence closeout gap extraction and persistence.
  - `src/ai_todo_assistant/presentation/cli.py` for `/list` reason detection from Evidence.
- Affected tests:
  - `tests/test_workflow_connectors.py`
  - `tests/test_workflow_sync_services.py`
  - `tests/test_workflow_services_cli.py`
- No migration is expected; closeout context is stored as append-only Evidence using the existing schema.

## Boundaries

This change is strictly read-only toward external systems:

- Do not write Redmine comments, fields, assignees, statuses, or time entries.
- Do not write GitLab/MR comments, labels, approvals, merge state, or branches.
- Do not run OpenSpec archive/sync/apply commands as part of runtime `/sync` or `/list`.
- Do not execute Playbook closeout with `--apply`, merge, cleanup, finalize, publish, or any writeback.
- Do not mark a WorkItem `done` solely because a closeout gap was observed; completion-state changes remain owned by existing completion sync rules.
- Do not add a new daily command; use `/sync` and `/list`.

## Success Criteria

- `/sync` writes local Evidence describing Redmine/MR/OpenSpec closeout gaps when read-only snapshots contain those facts.
- `/list` shows closeout-specific reasons using local Evidence, including:
  - `MR merged but Redmine not closed`
  - `Redmine resolved but validation evidence missing`
  - `OpenSpec completed but not archived`
- Connector failures or unavailable tools are persisted as local snapshot/error Evidence and do not interrupt the CLI.
- Existing Codex completion sync, source-identity merge behavior, and detailed `/list` filters remain compatible.
