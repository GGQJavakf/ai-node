## ADDED Requirements

### Requirement: AgentRetro is an independent CLI product

The system SHALL expose a `retro` console entry point backed by an independent `agent_retro` package and SHALL preserve the existing `ai-todo` entry point, behavior, configuration precedence, and data.

#### Scenario: Invoke AgentRetro help

- **WHEN** the user runs `retro --help`
- **THEN** the system SHALL display the AgentRetro command surface without starting or importing the Todo/WorkItem application domain

#### Scenario: Existing product remains unchanged

- **WHEN** AgentRetro is installed but no AgentRetro command is invoked
- **THEN** existing `ai-todo` commands and `data/todos.db` behavior SHALL remain unchanged

#### Scenario: AgentRetro initialization fails

- **WHEN** AgentRetro configuration or database initialization fails
- **THEN** the failure SHALL NOT prevent `ai-todo` from starting or using its existing data

### Requirement: Model configuration reuse is read-only and secret-safe

The system SHALL reuse the effective `ai-todo` model configuration through one read-only adapter and SHALL NOT copy credential values into AgentRetro configuration, SQLite, logs, evidence, or Obsidian.

#### Scenario: Model configuration is available

- **WHEN** AgentRetro performs extraction or review with a configured model
- **THEN** the adapter SHALL provide only the fields required by the LLM client
- **AND** AgentRetro SHALL NOT persist the API key or authorization value

#### Scenario: Model configuration is unavailable

- **WHEN** no usable model client can be constructed
- **THEN** capture, accepted-knowledge lookup, briefing, synchronization status, and doctor diagnostics SHALL remain available
- **AND** model-dependent candidates SHALL stay pending

### Requirement: Briefs use only active accepted knowledge

The system SHALL build a task brief from active project rules, relevant lessons, current task state, and explicitly global knowledge, and SHALL exclude pending, rejected, conflicting, archived, and expired items.

#### Scenario: Build a project brief

- **WHEN** the user runs `retro brief "<task>" --project <project>`
- **THEN** the system SHALL select accepted knowledge in rule, lesson, task-state, and global order
- **AND** it SHALL include evidence references for selected items

#### Scenario: Exclude invalid knowledge

- **WHEN** matching knowledge is pending, rejected, conflicting, archived, or expired
- **THEN** the system SHALL exclude it from the brief body

#### Scenario: Synchronization is pending

- **WHEN** selected SQLite knowledge has an unresolved Obsidian synchronization failure
- **THEN** the system SHALL use the accepted SQLite version
- **AND** it SHALL include a concise synchronization warning

### Requirement: Brief output is bounded and portable

The system SHALL default to an approximately 6000-token brief budget and SHALL support terminal, Markdown, and stable JSON output.

#### Scenario: Relevant knowledge exceeds the budget

- **WHEN** eligible knowledge exceeds the configured brief budget
- **THEN** the system SHALL prioritize project rules, task relevance, recency, and evidence quality
- **AND** it SHALL report that additional eligible knowledge was omitted

#### Scenario: Request JSON output

- **WHEN** the user requests `--json`
- **THEN** the system SHALL return stable English field names and enum values without ANSI formatting

#### Scenario: Render on Windows consoles

- **WHEN** AgentRetro runs under a Windows GBK or UTF-8 console
- **THEN** help, capture, review, and brief output SHALL complete without an encoding exception

### Requirement: Codex guidance integration is previewed, bounded, and reversible

The system SHALL preview global guidance changes by default and SHALL modify only one managed AgentRetro block after explicit `--apply` confirmation.

#### Scenario: Preview integration

- **WHEN** the user runs `retro integrate codex` without `--apply`
- **THEN** the system SHALL display the target, managed-block diff, and backup location
- **AND** it SHALL NOT modify global Codex guidance

#### Scenario: Apply integration

- **WHEN** the user runs `retro integrate codex --apply` and the target hash matches the previewed input
- **THEN** the system SHALL back up the target, add or update one managed block, and read back the result
- **AND** it SHALL preserve text outside the managed block byte-for-byte

#### Scenario: Guidance changed after preview

- **WHEN** the target global guidance hash differs from the preview input
- **THEN** the system SHALL refuse the apply and require a new preview

#### Scenario: Remove integration

- **WHEN** the user explicitly removes AgentRetro Codex integration
- **THEN** the system SHALL remove only the exact managed block after preview and confirmation
- **AND** it SHALL preserve native Codex memory files and memory settings

#### Scenario: Managed integration block changed manually

- **WHEN** the managed block differs from AgentRetro's recorded hash
- **THEN** the system SHALL refuse automatic update or removal
- **AND** it SHALL require reconciliation without force overwrite

### Requirement: Codex integration loads memory progressively

The managed guidance SHALL direct Codex to request `retro brief` only when a task depends on prior decisions, project history, user preferences, or current task state.

#### Scenario: Task needs historical context

- **WHEN** a Codex task depends on prior decisions, project history, preferences, or current task state
- **THEN** the managed guidance SHALL direct Codex to obtain a task-scoped `retro brief`

#### Scenario: Trivial task does not need memory

- **WHEN** a Codex task is self-contained and does not depend on retained context
- **THEN** the managed guidance SHALL NOT require a full Obsidian scan or unconditional brief generation

### Requirement: Doctor reports readiness without exposing secrets

The system SHALL provide `retro doctor` checks for session-source access, database and migrations, model availability, Obsidian mapping and write safety, backup path, synchronization recovery state, global integration state, and console encoding.

#### Scenario: Run doctor with a configured system

- **WHEN** the user runs `retro doctor`
- **THEN** the system SHALL report each readiness area as healthy, warning, or error with a recovery hint
- **AND** it SHALL report credential presence only as configured or missing without displaying the value

#### Scenario: Rollback is required

- **WHEN** a synchronization journal is in `rollback_required`
- **THEN** doctor SHALL report it as blocking later automatic synchronization
- **AND** it SHALL identify the recovery command and backup run ID
