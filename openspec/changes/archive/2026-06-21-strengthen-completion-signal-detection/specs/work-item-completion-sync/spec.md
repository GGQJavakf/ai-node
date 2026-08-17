## ADDED Requirements

### Requirement: Local completion signals can close Codex WorkItems

The assistant SHALL treat conservative local completion signals in Codex report entries as completion evidence even when the entry appears under `unfinished` or `blocked`.

#### Scenario: MR merged signal closes unfinished Codex item

- **GIVEN** a local Codex WorkItem has status `active`
- **WHEN** the latest Codex report lists the same thread under `unfinished` with text indicating an MR or PR was merged
- **THEN** the assistant SHALL mark the WorkItem `done`
- **AND** it SHALL append local Evidence describing the merge completion signal.

#### Scenario: Redmine resolved signal closes blocked Codex item

- **GIVEN** a local Codex WorkItem has status `blocked`
- **WHEN** the latest Codex report lists the same thread under `blocked` with text indicating Redmine was resolved or closed
- **THEN** the assistant SHALL mark the WorkItem `done`
- **AND** it SHALL append local Evidence describing the Redmine completion signal.

#### Scenario: OpenSpec archived signal closes Codex item

- **GIVEN** a local Codex WorkItem has status `active`
- **WHEN** the latest Codex report includes local text indicating an OpenSpec change was archived or all OpenSpec tasks are complete
- **THEN** the assistant SHALL mark the WorkItem `done`.

#### Scenario: Playbook closeout verified signal closes Codex item

- **GIVEN** a local Codex WorkItem has status `active`
- **WHEN** the latest Codex report includes local text indicating Playbook closeout was verified or completed
- **THEN** the assistant SHALL mark the WorkItem `done`.

#### Scenario: Final validation passed signal closes Codex item

- **GIVEN** a local Codex WorkItem has status `active`
- **WHEN** the latest Codex report includes local text indicating final validation passed with no required follow-up
- **THEN** the assistant SHALL mark the WorkItem `done`.

### Requirement: Done WorkItems produce reopen review candidates instead of automatic reopen

The assistant SHALL preserve local `done` status when later Codex reports list the same WorkItem as unfinished or blocked, and SHALL expose the case as a review-only reopen candidate.

#### Scenario: Done item appears unfinished later

- **GIVEN** a local Codex WorkItem has status `done`
- **WHEN** a later Codex report lists the same thread under `unfinished` without a strong completion signal
- **THEN** the assistant SHALL keep the WorkItem status `done`
- **AND** it SHALL record a reopen candidate in the import result details.

#### Scenario: Done item appears blocked later

- **GIVEN** a local Codex WorkItem has status `done`
- **WHEN** a later Codex report lists the same thread under `blocked` without a strong completion signal
- **THEN** the assistant SHALL keep the WorkItem status `done`
- **AND** it SHALL include the candidate in `/sync` output for manual review.

#### Scenario: Strong completion signal on done item is not a reopen candidate

- **GIVEN** a local Codex WorkItem has status `done`
- **WHEN** a later Codex report lists the same thread under `unfinished` but includes strong completion evidence
- **THEN** the assistant SHALL keep the WorkItem status `done`
- **AND** it SHALL record only new completion Evidence instead of a reopen candidate.

### Requirement: Sync summary reports completion detection and reopen candidates

The assistant SHALL include detected completion transitions and reopen review candidates in Codex import summaries used by `/sync` and dry-run preview.

#### Scenario: Sync closes stale unfinished item by local signal

- **WHEN** `/sync` imports a report where an unfinished item contains a strong completion signal
- **THEN** the Codex summary SHALL count the item as completed rather than reactivated or unchanged.

#### Scenario: Sync reports reopen candidates

- **WHEN** `/sync` imports a report where a done item appears as unfinished or blocked without strong completion evidence
- **THEN** the Codex summary SHALL include the number of reopen candidates
- **AND** the details SHALL identify the candidate WorkItem.

#### Scenario: Dry-run reports the same local classification without writes

- **WHEN** `/sync --dry-run` previews a report with strong completion signals and reopen candidates
- **THEN** the preview SHALL show the same completion and reopen candidate counts
- **AND** no WorkItem or Evidence writes SHALL occur.
