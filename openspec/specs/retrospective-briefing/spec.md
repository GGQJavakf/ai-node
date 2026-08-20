# retrospective-briefing Specification

## Purpose
TBD - created by archiving change add-agentretro-mvp. Update Purpose after archive.
## Requirements
### Requirement: AgentRetro is an independent CLI product

The system SHALL expose a `retro` console entry point backed by an independent `agent_retro` package and SHALL preserve the existing `ai-todo` entry point, behavior, configuration precedence, and data.

#### Scenario: [BR-01] Invoke AgentRetro help

- **WHEN** the user runs `retro --help`
- **THEN** the system SHALL display the AgentRetro command surface without starting or importing the Todo/WorkItem application domain

#### Scenario: [BR-02] Existing product remains unchanged

- **WHEN** AgentRetro is installed but no AgentRetro command is invoked
- **THEN** existing `ai-todo` commands and `data/todos.db` behavior SHALL remain unchanged

#### Scenario: [BR-03] AgentRetro initialization fails

- **WHEN** AgentRetro configuration or database initialization fails
- **THEN** the failure SHALL NOT prevent `ai-todo` from starting or using its existing data

### Requirement: Model configuration reuse is read-only and secret-safe

The system SHALL reuse the effective `ai-todo` model configuration through one read-only adapter and SHALL NOT copy credential values into AgentRetro configuration, SQLite, logs, evidence, or Obsidian.

#### Scenario: [BR-04] Model configuration is available

- **WHEN** AgentRetro performs extraction or review with a configured model
- **THEN** the adapter SHALL provide only the fields required by the LLM client
- **AND** AgentRetro SHALL NOT persist the API key or authorization value

#### Scenario: [BR-05] Model configuration is unavailable

- **WHEN** no usable model client can be constructed
- **THEN** capture, accepted-knowledge lookup, briefing, synchronization status, and doctor diagnostics SHALL remain available
- **AND** model-dependent candidates SHALL stay pending

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

### Requirement: Brief output is bounded and portable

The system SHALL default to a configurable approximately 6000-token brief budget, SHALL estimate an item's cost as `ceil(UTF-8 byte length / 3)`, SHALL include or omit each item atomically, and SHALL support terminal, Markdown, and stable JSON output.

#### Scenario: [BR-09] Relevant knowledge exceeds the budget

- **WHEN** eligible knowledge exceeds the configured brief budget
- **THEN** the system SHALL preserve the fixed category order and use deterministic relevance, recency, evidence-quality, and stable-ID ordering within a category
- **AND** it SHALL report that additional eligible knowledge was omitted
- **AND** it SHALL NOT truncate an individual item

#### Scenario: [BR-10] Request JSON output

- **WHEN** the user requests `--json`
- **THEN** the system SHALL return stable English field names and enum values without ANSI formatting

#### Scenario: [BR-11] Render on Windows consoles

- **WHEN** AgentRetro runs under a Windows GBK or UTF-8 console
- **THEN** help, capture, review, and brief output SHALL complete without an encoding exception

### Requirement: Codex guidance integration is previewed, bounded, and reversible

The system SHALL resolve the canonical target as `<effective-codex-home>/AGENTS.md`, SHALL preview global guidance changes by default, and SHALL modify only one managed AgentRetro block after explicit `--apply` confirmation. It SHALL never target `AGENTS.override.md`; if that override exists, integration SHALL refuse to apply because it can shadow the canonical target.

#### Scenario: [BR-12] Preview integration

- **WHEN** the user runs `retro integrate codex` without `--apply`
- **THEN** the system SHALL display the target, managed-block diff, and backup location
- **AND** it SHALL NOT modify global Codex guidance

#### Scenario: [BR-13] Apply integration

- **WHEN** the user runs `retro integrate codex --apply` and the target hash matches the previewed input
- **THEN** the system SHALL verify canonical-target containment and safe symlink resolution, back up the target, add or update one managed block, and read back the result
- **AND** it SHALL preserve encoding, newline style, and text outside the managed block byte-for-byte

#### Scenario: [BR-14] Guidance changed after preview

- **WHEN** the target global guidance hash differs from the preview input
- **THEN** the system SHALL refuse the apply and require a new preview

#### Scenario: [BR-15] Remove integration

- **WHEN** the user explicitly removes AgentRetro Codex integration
- **THEN** the system SHALL remove only the exact managed block after preview and confirmation
- **AND** it SHALL preserve native Codex memory files and memory settings

#### Scenario: [BR-16] Managed integration block changed manually

- **WHEN** the managed block differs from AgentRetro's recorded hash
- **THEN** the system SHALL refuse automatic update or removal
- **AND** it SHALL require reconciliation without force overwrite

### Requirement: Codex integration loads memory progressively

The managed guidance SHALL direct Codex to request `retro brief` only when a task depends on prior decisions, project history, user preferences, or current task state.

#### Scenario: [BR-17] Task needs historical context

- **WHEN** a Codex task depends on prior decisions, project history, preferences, or current task state
- **THEN** the managed guidance SHALL direct Codex to obtain a task-scoped `retro brief`

#### Scenario: [BR-18] Trivial task does not need memory

- **WHEN** a Codex task is self-contained and does not depend on retained context
- **THEN** the managed guidance SHALL NOT require a full Obsidian scan or unconditional brief generation

### Requirement: Doctor reports readiness without exposing secrets

The system SHALL provide `retro doctor` checks for session-source access, configured safety limits, database and migrations, model availability, audited project mappings, Obsidian write safety, backup path, synchronization and purge recovery state, global integration and override-conflict state, and console encoding.

#### Scenario: [BR-19] Run doctor with a configured system

- **WHEN** the user runs `retro doctor`
- **THEN** the system SHALL report each readiness area as healthy, warning, or error with a recovery hint
- **AND** it SHALL report credential presence only as configured or missing without displaying the value

#### Scenario: [BR-20] Rollback is required

- **WHEN** a synchronization journal is in `rollback_required`
- **THEN** doctor SHALL report it as blocking later automatic synchronization
- **AND** it SHALL identify the recovery command and backup run ID

### Requirement: Brief relevance is deterministic and local

The system SHALL calculate task relevance locally without a model call or vector database. It SHALL normalize task and knowledge text using Unicode NFKC and case folding, tokenize CJK and Latin text deterministically, combine keyword overlap, recency, and evidence-quality scores with configured fixed weights, and use the stable knowledge ID as the final tie-breaker.

#### Scenario: [BR-21] Repeat deterministic relevance selection

- **WHEN** the same task, active knowledge snapshot, configuration, and clock input are used twice
- **THEN** both runs SHALL select the same ordered knowledge IDs
- **AND** neither run SHALL invoke a model or vector service

#### Scenario: [BR-22] Resolve equal relevance scores

- **WHEN** two eligible items have equal category, relevance, recency, and evidence-quality scores
- **THEN** the item with the lexically earlier stable knowledge ID SHALL sort first
- **AND** any budget omission SHALL be reproducible

#### Scenario: [BR-23] Mandatory rules exceed the budget

- **WHEN** the accepted project and explicitly global rules alone exceed the configured brief budget
- **THEN** the system SHALL return a diagnostic failure identifying the required budget increase or rule cleanup
- **AND** it SHALL NOT silently omit or truncate a rule

#### Scenario: [BR-24] Brief rendering reaches its deadline

- **WHEN** local selection and rendering exceed the configurable deadline whose default is 5 seconds
- **THEN** the command SHALL fail with a bounded-time diagnostic
- **AND** it SHALL NOT emit a partial brief as successful output

### Requirement: Canonical Codex integration is safely discoverable

The system SHALL create a missing canonical `AGENTS.md` only through the preview/apply workflow, SHALL verify the effective file after write, and SHALL run a non-writing smoke check proving that the managed instruction is discoverable from the configured Codex home.

#### Scenario: [BR-25] Canonical guidance file is missing

- **WHEN** `<effective-codex-home>/AGENTS.md` does not exist and the user previews integration
- **THEN** the preview SHALL explicitly show creation of that exact file and its complete initial content
- **AND** the file SHALL be created only after a matching explicit apply

#### Scenario: [BR-26] Override guidance exists

- **WHEN** `<effective-codex-home>/AGENTS.override.md` exists
- **THEN** preview and doctor SHALL report the shadowing conflict
- **AND** integration apply or removal SHALL refuse without modifying either guidance file

#### Scenario: [BR-27] Integration readback succeeds

- **WHEN** canonical integration apply completes
- **THEN** the system SHALL confirm the read-back hash and exact managed-block contents
- **AND** a non-writing discoverability smoke check SHALL confirm the managed instruction is effective

### Requirement: Model-dependent operations are time-bounded

The system SHALL use the filtered existing model-request deadline when configured and otherwise default to 120 seconds, and a deadline failure SHALL NOT create an accepted candidate or projection event.

#### Scenario: [BR-28] Model request reaches its deadline

- **WHEN** extraction or review reaches the effective model-request deadline
- **THEN** the system SHALL stop that model request with a stable timeout diagnostic
- **AND** any already persisted candidate SHALL remain pending and retryable
- **AND** it SHALL create no partial acceptance or Obsidian projection state

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
