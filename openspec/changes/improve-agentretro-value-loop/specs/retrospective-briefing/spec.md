## MODIFIED Requirements

### Requirement: Briefs use only active accepted knowledge

The system SHALL resolve a brief project reference to one canonical project before selecting knowledge. It SHALL build a task brief in the fixed category order active project rules, explicitly global rules, current project or explicitly global task state, and relevant project or explicitly global lessons, and SHALL exclude pending, rejected, conflicting, archived, and effectively expired items.

#### Scenario: [BR-06] Build a project brief

- **WHEN** the user runs `retro brief "<task>" --project <reference>` with a canonical project ID, mapped repository/workspace path, worktree path, or normalized credential-free remote that resolves to one canonical project
- **THEN** the system SHALL use that canonical project ID and preserve the existing knowledge category order, evidence references, budget, omissions, and warnings

#### Scenario: [BR-07] Exclude invalid knowledge

- **WHEN** matching knowledge is pending, rejected, conflicting, archived, or effectively expired
- **THEN** the system SHALL exclude it from the brief body

#### Scenario: [BR-08] Synchronization is pending

- **WHEN** selected SQLite knowledge has an unresolved Obsidian synchronization failure
- **THEN** the system SHALL use the accepted SQLite version
- **AND** it SHALL include a concise synchronization warning

#### Scenario: [BR-29] Brief project reference is unknown

- **WHEN** the supplied project reference matches no active canonical ID, mapped path, worktree remote, or normalized remote identity
- **THEN** the system SHALL return `unknown_project_reference` with `retro project list` as the recovery command
- **AND** it SHALL NOT render a successful empty brief or read project knowledge

#### Scenario: [BR-30] Brief project reference is ambiguous or conflicting

- **WHEN** equally specific active path mappings match different projects, or path/worktree-remote identities resolve to different projects
- **THEN** the system SHALL return `ambiguous_project_reference` with safe conflicting mapping IDs and reason `mapping_identity_conflict`
- **AND** it SHALL NOT choose a project or read project knowledge

#### Scenario: [BR-35] Resolve a nested workspace path

- **WHEN** an existing input path is contained by more than one active workspace mapping
- **THEN** the system SHALL use only the unique longest normalized containing root
- **AND** equal-length matches to different canonical projects SHALL be ambiguous

#### Scenario: [BR-36] Resolve a Git worktree path

- **WHEN** an existing input path belongs to a Git worktree whose root differs from the stored Git mapping root but whose credential-free normalized remote matches one active Git mapping
- **THEN** the system SHALL resolve to that mapping's canonical project
- **AND** credentials or user-info found in a remote SHALL never appear in diagnostics or output

## ADDED Requirements

### Requirement: Empty brief diagnostics are actionable and content-safe

When a resolved project brief contains no selected knowledge, the system SHALL return aggregate health facts and exact recovery commands without exposing candidate text, evidence excerpts, source paths, model error details, or credentials. Counts SHALL use the same injected current time and canonical project as knowledge selection.

#### Scenario: [BR-31] Resolved project has only expired and pending knowledge

- **WHEN** a brief selects no item but the project has effectively expired task state or pending review candidates
- **THEN** the result SHALL include `eligible_knowledge_count`, `expired_task_state_count`, `pending_review_count`, and `captured_session_count`
- **AND** `eligible_knowledge_count` SHALL count accepted records visible after scope/status/conflict/archive/expiry filters and before lesson relevance or budget selection
- **AND** it SHALL return `retro review inbox --project <canonical-project-id>` and `retro capture --recent <recovery-count> --dry-run`, where `recovery-count` is `min(5, recent_capture_max)`

#### Scenario: [BR-32] Resolved project has no captured sessions

- **WHEN** a brief selects no item and no captured session belongs to the canonical project
- **THEN** `captured_session_count` SHALL be zero
- **AND** the result SHALL include the exact bounded recent-capture preview command

#### Scenario: [BR-33] Non-empty brief remains concise

- **WHEN** a brief selects at least one knowledge item
- **THEN** the system SHALL preserve the existing category order, budget, omissions, evidence references, and warnings
- **AND** aggregate recovery guidance SHALL NOT displace selected knowledge

#### Scenario: [BR-34] Request an empty brief as JSON

- **WHEN** an empty brief is requested with `--json`
- **THEN** the system SHALL return stable English fields for the canonical project, four counts, and both recovery commands
- **AND** it SHALL contain no ANSI sequences or sensitive candidate, evidence, path, model-error, or credential content
