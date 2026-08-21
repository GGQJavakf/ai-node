## ADDED Requirements

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
