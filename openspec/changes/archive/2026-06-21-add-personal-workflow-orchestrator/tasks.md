## 1. Domain Model and Persistence

- [x] 1.1 Add failing tests for creating and listing WorkItems.
- [x] 1.2 Add failing tests for attaching Evidence to a WorkItem.
- [x] 1.3 Create workflow domain models for WorkItem, Evidence, SourceSnapshot, and status enums.
- [x] 1.4 Extend SQLite schema with work_items and work_evidence tables.
- [x] 1.5 Add JSON compatibility persistence for WorkItems and Evidence.
- [x] 1.6 Add repository/port protocols for workflow storage.

## 2. Source Connectors

- [x] 2.1 Add failing tests for GitConnector branch and dirty status parsing.
- [x] 2.2 Add failing tests for OpenSpecConnector list/status parsing.
- [x] 2.3 Add failing tests for PlaybookConnector Redmine issue import parsing.
- [x] 2.3a Add failing tests for Playbook workspace task/status and closeout gap parsing.
- [x] 2.3b Add failing tests for OpenSpec apply-instruction parsing.
- [x] 2.4 Implement a safe command runner with timeout, cwd, JSON parsing, and output excerpt capture.
- [x] 2.5 Implement GitConnector using read-only git commands.
- [x] 2.6 Implement OpenSpecConnector using `openspec list/status --json`.
- [x] 2.7 Implement PlaybookConnector using Playbook read-only commands.
- [x] 2.8 Implement missing-command and invalid-output degradation to unavailable SourceSnapshot.
- [x] 2.9 Implement Playbook workspace task/status and closeout gap snapshots.
- [x] 2.10 Implement OpenSpec apply-instruction snapshots.

## 2A. Codex Daily Task Reports

- [x] 2A.1 Add failing tests for reading the latest Codex unfinished-task report from a local directory.
- [x] 2A.2 Add config for the Codex task report directory with an environment override.
- [x] 2A.3 Implement a read-only CodexTaskReportService for stable JSON snapshots.
- [x] 2A.4 Add a `/codex tasks` CLI command that summarizes unfinished and blocked tasks.
- [x] 2A.4a Read paired Codex Markdown daily summaries next to JSON reports.
- [x] 2A.5 Extend WorkItem sync to import Codex report entries as source-backed WorkItems.
- [x] 2A.6 Add Agent tool support for reading Codex unfinished-task reports.
- [x] 2A.7 Document the Codex automation output schema and retention expectations.
- [x] 2A.8 Create or update the Codex daily automation that writes reports to `data/codex-task-reports/`.
- [x] 2A.9 Define Codex completion signals so MR merge, closeout, Redmine resolved, publish success, and final validation are classified as completed.

## 3. Workflow Services

- [x] 3.1 Add failing tests for importing a Redmine WorkItem through Playbook snapshots.
- [x] 3.2 Add failing tests for `/sync` style current-project context synchronization.
- [x] 3.3 Add failing tests for stale sync detection.
- [x] 3.4 Implement WorkItemService for create, import, update, list, and status summary.
- [x] 3.5 Implement WorkflowSyncService to combine Git/OpenSpec/Playbook snapshots.
- [x] 3.6 Implement EvidenceService for append-only evidence records and grouped summaries.
- [x] 3.7 Implement ContinueService to recommend the next action from WorkItems and Evidence.
- [x] 3.8 Implement DailyReviewService for startup plans and day review Markdown.

## 4. CLI Commands

- [x] 4.1 Add failing CLI tests for `/work import redmine <id>`.
- [x] 4.1a Add failing CLI tests for `/work add <title>`.
- [x] 4.1b Add failing CLI tests for `/work evidence add <work-id>` and `/work evidence summary <work-id>`.
- [x] 4.2 Add failing CLI tests for `/work status`.
- [x] 4.3 Add failing CLI tests for `/sync`.
- [x] 4.4 Add failing CLI tests for `/continue`.
- [x] 4.5 Add failing CLI tests for `/review day` and `/start day`.
- [x] 4.5a Add CLI tests for `/codex tasks`.
- [x] 4.6 Implement `/work import redmine <id>` command.
- [x] 4.6a Implement `/work add <title>` command.
- [x] 4.6b Implement `/work evidence add <work-id>` and `/work evidence summary <work-id>` commands.
- [x] 4.7 Implement `/work status` command.
- [x] 4.8 Implement `/sync` command.
- [x] 4.9 Implement `/continue` command.
- [x] 4.10 Implement `/review day` and `/start day` commands.
- [x] 4.10a Implement `/codex tasks` command.
- [x] 4.11 Update CLI help and completions.

## 5. Agent Tools

- [x] 5.1 Add tool model tests for workflow tool argument validation.
- [x] 5.2 Add tool executor tests for workflow tool dispatch.
- [x] 5.3 Add tool definitions for sync, manual work item creation, import, list status, recommend next action, record evidence, evidence summary, Codex task reports, and daily review.
- [x] 5.4 Implement ToolExecutor workflow handlers by delegating to workflow services.
- [x] 5.5 Update Agent system prompt to describe workflow orchestration boundaries and read-only external connector behavior.

## 6. Verification and Documentation

- [x] 6.1 Update README with workflow assistant commands and safety boundaries.
- [x] 6.2 Run focused workflow tests.
- [x] 6.3 Run full unittest suite.
- [x] 6.4 Run `openspec status --change add-personal-workflow-orchestrator --json`.
- [x] 6.5 Run `openspec list --json` and confirm the change is ready for apply.
- [x] 6.6 Perform code review focused on accidental external write operations and command-injection risks.
