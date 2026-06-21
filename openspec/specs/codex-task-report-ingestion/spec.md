# codex-task-report-ingestion Specification

## Purpose
TBD - created by archiving change add-personal-workflow-orchestrator. Update Purpose after archive.
## Requirements
### Requirement: Read Codex unfinished-task reports from a local directory

The assistant SHALL read Codex unfinished-task reports and daily summaries from a configured local directory instead of reading Codex internal storage directly.

#### Scenario: Latest report exists

- **WHEN** the report directory contains one or more JSON report files
- **THEN** the assistant SHALL load the latest report by `generated_at`
- **AND** it SHALL expose unfinished and blocked tasks as structured facts.

#### Scenario: Matching daily summary exists

- **WHEN** the latest JSON report has a same-date Markdown file next to it
- **THEN** the assistant SHALL read the Markdown daily summary
- **AND** it SHALL preserve the summary path and content for daily planning, review, and user display.

#### Scenario: Report directory is empty or missing

- **WHEN** the user asks for Codex unfinished tasks and no report exists
- **THEN** the assistant SHALL return a clear "no snapshot" status
- **AND** it SHALL include the configured report directory path.

#### Scenario: Report file is malformed

- **WHEN** a report file contains invalid JSON or a non-object payload
- **THEN** the assistant SHALL skip that file
- **AND** it SHALL continue reading other valid reports without failing the CLI or Agent loop.

### Requirement: Codex report schema is stable and minimal

Codex daily task reports SHALL use a stable JSON schema that ai-node can consume across Codex implementation changes.

#### Scenario: Automation writes a daily report

- **WHEN** the Codex automation finishes inspecting recent threads
- **THEN** it SHALL write a JSON report containing `generated_at`, `total_unfinished`, `unfinished`, `blocked`, `completed`, and `summary`
- **AND** each task entry SHOULD include `thread_id`, `title`, `status`, `cwd`, `source`, `next_action`, `evidence`, and `completion_signals` when known.
- **AND** it SHALL write a same-date Markdown daily summary containing sections for follow-up, blockers, completed work, and uninspected risks.

#### Scenario: Automation classifies completed work

- **WHEN** a thread contains evidence that closeout was triggered or completed, MRs were merged, Redmine was updated to resolved, release/publish succeeded, or final validation passed with no required follow-up
- **THEN** the automation SHALL classify that task under `completed`
- **AND** it SHALL include the concrete evidence in `completion_signals`.

#### Scenario: Completion evidence conflicts with pending language

- **WHEN** a thread summary contains stale "next step" wording but later evidence shows MR merge, closeout completion, Redmine resolved, or publish success
- **THEN** the automation SHALL prefer the latest concrete completion evidence
- **AND** it SHALL not count the task in `total_unfinished`.

#### Scenario: Optional fields are absent

- **WHEN** optional fields such as `summary`, `next_action`, or `evidence` are absent
- **THEN** ai-node SHALL still load the report
- **AND** it SHALL derive counts from `unfinished` and `blocked` when `total_unfinished` is absent.

### Requirement: CLI exposes Codex unfinished-task report

The assistant SHALL provide a CLI command for reading the latest Codex task report.

#### Scenario: User runs Codex tasks command

- **WHEN** the user runs `/codex tasks`
- **THEN** the assistant SHALL print the report generation time, unfinished count, summary, and top unfinished or blocked items
- **AND** it SHALL show the next action for each unfinished or blocked item when available
- **AND** it SHALL show recent completed items and their completion signals when available.
- **AND** it SHALL show the Markdown daily summary path when a paired summary exists.

