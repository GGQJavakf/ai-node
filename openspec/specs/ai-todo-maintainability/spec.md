## Purpose

Define stable ownership, measurable complexity boundaries, compatibility guarantees, and delivery evidence for maintaining the ai-todo command and Codex-resume workflows.

## Requirements

### Requirement: ai-todo hotspot responsibilities have explicit owners

The system SHALL retain the existing ai-todo command facade and Codex resume service entry points while assigning command tokenization and dispatch, list selection and rendering, work-command validation and execution, triage-reason precedence, and resume-candidate classification to focused private owners. The decomposition SHALL NOT introduce a circular import or change existing constructor and monkeypatch seams.

#### Scenario: Import and patch stable entry points
- **WHEN** callers import or instantiate the existing CLI and Codex resume service and replace a historical handler on an instance
- **THEN** every public import, signature, constructor contract, and instance-level handler seam SHALL remain available
- **AND** command dispatch SHALL resolve the replacement at invocation time

#### Scenario: Inspect decomposed ownership
- **WHEN** architecture checks inspect the affected facade modules and declared complexity manifest
- **THEN** tokenization, dispatch, selection, rendering, mutation, classification, and precedence responsibilities SHALL each have one named owner
- **AND** the facade methods SHALL delegate instead of duplicating extracted branches

### Requirement: ai-todo complexity reduction is measurable and scoped

Every function in `src/ai_todo_assistant` and each private helper introduced by this change SHALL pass Ruff `C901` with `lint.mccabe.max-complexity=15`. The complexity gate SHALL validate a manifest containing the affected owner modules, SHALL scan the full ai-todo source tree, and SHALL NOT use per-function suppressions.

#### Scenario: ai-todo passes the established ceiling
- **WHEN** CI runs the declared manifest check and full ai-todo C901 scan at 15
- **THEN** both commands SHALL report no `C901` finding
- **AND** the manifest SHALL include the CLI and Codex-resume owner modules

#### Scenario: A new hotspot or invalid target appears
- **WHEN** a covered function exceeds 15 or the manifest contains a duplicate, missing, or out-of-package path
- **THEN** the complexity gate SHALL fail with the affected function or target

### Requirement: Command and workflow behavior remains compatible

The system SHALL preserve existing slash-command spellings and aliases, argument splitting, handler monkeypatching, list filters, source filters, row categories and ordering, Rich rendering, work-item operations, exact usage and error text, return types, persistence effects, and triage-reason precedence throughout the decomposition.

#### Scenario: Route supported, aliased, terminal, and unknown commands
- **WHEN** a caller issues any existing slash command, `/r` or `/resume`, `/next` or `/continue`, `/exit` or `/quit`, or an unknown command
- **THEN** the same handler SHALL receive the same argument shape and return the same value as before the change
- **AND** an instance-level replacement handler SHALL still be invoked

#### Scenario: Select and render list variants
- **WHEN** `/list` receives default, date, status, priority, unknown, or source-filter arguments with todo-only, workflow-only, mixed, or empty data
- **THEN** the same data sources, title, empty-state text, category ordering, row fields, and Rich values SHALL be returned

#### Scenario: Execute work-item subcommands
- **WHEN** `/work` receives add, status, conflicts, show, rollback, import, split, evidence, incomplete, invalid, or service-failure input
- **THEN** the same validation precedence, service call, persistence effect, exception translation, and exact response text SHALL be preserved

#### Scenario: Resolve overlapping triage conditions
- **WHEN** a work item and optional evidence match one or more completion, blocking, failure, staleness, branch, source, or next-action conditions
- **THEN** the first reason selected by the pre-change precedence SHALL be returned unchanged

### Requirement: Codex resume candidate behavior remains compatible

The system SHALL preserve unfinished-first traversal, target filtering, manual exclusion loading, fail-closed exclusion errors, blocked and completed denial precedence, invalid-entry handling, skip de-duplication, candidate and skip ordering, missing-target reporting, and zero-write dry-run behavior.

#### Scenario: Select bulk resume candidates and skips
- **WHEN** a report contains valid, malformed, excluded, denied, blocked, completed, duplicate, or non-resumeable entries
- **THEN** the same ordered candidates and skips with the same thread identifiers, titles, prompts, and reasons SHALL be produced
- **AND** denied entries SHALL NOT be emitted twice when present in multiple buckets

#### Scenario: Select a targeted thread
- **WHEN** a targeted resume identifies an eligible, excluded, denied, malformed, or missing thread
- **THEN** only the matching thread SHALL be evaluated under the existing targeted exclusion policy
- **AND** the same candidate or skip reason SHALL be returned without mutating workflow data during preview

#### Scenario: Manual exclusion policy cannot be read
- **WHEN** bulk selection cannot load the configured exclusion policy
- **THEN** selection SHALL fail closed with the existing single policy-unavailable skip
- **AND** no resume candidate SHALL be returned

### Requirement: ai-todo refactor delivery is independently verifiable

The change SHALL provide focused characterization, architecture, complexity, full regression, branch coverage, lint, compile, type, package, Windows encoding, strict OpenSpec, and independent review evidence before it is marked ready.

#### Scenario: Produce ready-for-review evidence
- **WHEN** all implementation tasks are complete
- **THEN** evidence SHALL identify the exact commit and include command-surface, personal-assistant, workflow CLI, Codex-resume, full-suite, branch-coverage, Ruff, manifest and full ai-todo C901, mypy, compileall, package/Twine/isolated-wheel, UTF-8/GBK, strict OpenSpec, and OCR results
- **AND** OCR accounting SHALL include every changed file or explain unsupported exclusions
- **AND** any unresolved material finding or unavailable compatibility check SHALL keep the change from being marked ready

### Requirement: Declared ai-todo workflow owners satisfy a stricter complexity boundary

The system SHALL validate every function in the declared Codex workflow and CLI owner modules with Ruff C901 at a maximum complexity of 10 while retaining the full ai-todo package ceiling of 15. Both scans SHALL ignore per-function suppression directives.

#### Scenario: Run the two-level complexity gate
- **WHEN** CI runs the ai-todo complexity gate
- **THEN** the manifest modules SHALL report no C901 finding at 10
- **AND** the full ai-todo source tree SHALL report no C901 finding at 15
- **AND** a `noqa` suppression SHALL NOT make either scan pass

### Requirement: Codex import and preview share decisions without sharing side effects

The system SHALL classify and prepare each Codex report entry through one decision path for import and preview. Preview SHALL remain zero-write, while import SHALL preserve exact persistence, merge-audit, completion-evidence, count, detail, item-order, collision, and status-transition behavior.

#### Scenario: Import and preview the same report
- **WHEN** the same report contains existing, identity-matched, title-colliding, conflicting, reopened, active, and completed entries
- **THEN** import and preview SHALL classify them in the same order with the same result metadata
- **AND** preview SHALL perform no repository write
- **AND** import SHALL retain its existing saves, merge audits, and completion evidence

### Requirement: Resume skip copy has one ordered source of truth

The system SHALL derive skip progress and next-action text from one ordered reason mapping while preserving the existing raw-text versus normalized-text matching rules and fallback copy.

#### Scenario: Resolve overlapping and unknown skip reasons
- **WHEN** a skip reason matches multiple known conditions or no known condition
- **THEN** the existing first-match progress and next-action pair SHALL be returned
- **AND** unknown reasons SHALL retain the existing reason-or-default progress and manual-review next action

### Requirement: Refactored CLI orchestration remains compatible

The system SHALL preserve daily-triage data sources and failure containment, Codex report row and completed-signal ordering, resume option/exclusion/index resolution, work-item detail rendering, exact user-visible text, and runtime handler monkeypatch seams after extracting private owners.

#### Scenario: Render success, empty, and failure paths
- **WHEN** the affected CLI handlers receive populated, empty, invalid, excluded, indexed, missing, repository-failure, or evidence-failure input
- **THEN** they SHALL return or render the same titles, rows, fields, ordering, usage text, and errors as before
- **AND** exception handling SHALL remain at the same observable boundary

### Requirement: Workflow complexity delivery is independently verifiable

The change SHALL provide focused characterization, architecture, complexity, full regression, branch coverage, lint, compile, type, package, Windows encoding, strict OpenSpec, OCR, and fresh independent-review evidence before it is marked ready.

#### Scenario: Produce ready-for-review evidence
- **WHEN** implementation is complete
- **THEN** evidence SHALL identify the exact commit and all required local and remote checks
- **AND** every changed file SHALL be reviewed or explicitly accounted for
- **AND** any unresolved material finding SHALL keep the change from being marked ready
