## ADDED Requirements

### Requirement: Review inbox is concise, project-aware, bounded, and content-safe

The system SHALL provide a read-only review inbox that summarizes pending review work by canonical project, candidate status, and age without returning candidate text, evidence excerpts, source paths, model-error details, or credentials. The injected current time SHALL be used for all age and expiry calculations.

#### Scenario: [KR-25] List the cross-project review inbox

- **WHEN** the user runs `retro review inbox` without a project or awaiting selector
- **THEN** the system SHALL return one row per canonical project sorted by canonical project ID with `pending_count`, `retryable_count`, and `oldest_pending_age_seconds`
- **AND** age SHALL be a non-negative whole number of elapsed seconds or `null` when the count is zero
- **AND** it SHALL return `awaiting_unknown_count` and `awaiting_ambiguous_count` for captured sessions that cannot yet be routed

#### Scenario: [KR-26] List one project's next review actions

- **WHEN** the user runs `retro review inbox --project <reference> [--limit <count>]` and the reference resolves uniquely
- **THEN** the system SHALL return pending candidate IDs ordered by `created_at` ascending then candidate ID ascending, with a default limit of 20 and an allowed range of 1 through 50
- **AND** it SHALL return `total_count`, `returned_count`, and `truncated`, plus exact `show`, `accept`, `edit`, `reject`, and eligible `retry` command templates using the canonical project ID
- **AND** `retryable_count` and retry commands SHALL include only `pending_review` candidates with no saved review result whose latest attempt failed or which have no attempt; running or completed attempts SHALL not be retryable

#### Scenario: [KR-27] Review inbox project is unknown or ambiguous

- **WHEN** the project reference cannot resolve to exactly one canonical project
- **THEN** the system SHALL fail with `unknown_project_reference` or `ambiguous_project_reference` and the same safe resolver diagnostics used by brief
- **AND** it SHALL NOT fall back to an empty inbox

#### Scenario: [KR-28] List awaiting project routing work

- **WHEN** the user runs `retro review inbox --awaiting [--limit <count>]`
- **THEN** the system SHALL return safe source session IDs ordered by capture time ascending then session ID ascending, their `unknown` or `ambiguous` routing status, the same 1 through 50 limit contract, and `total_count`, `returned_count`, and `truncated`
- **AND** it SHALL return `retro project list` and `retro project reclassify --session <session-id> --mapping <mapping-id>` command templates without returning a source path or remote value

### Requirement: Read summaries report effective task-state expiry consistently

The system SHALL report an active `TASK_STATE` whose validity end is at or before the injected current time as expired in brief and review-inbox health summaries, while keeping those commands read-only.

#### Scenario: [KR-29] Active stored task state is past validity

- **WHEN** a task state is stored as active but its `valid_until` is at or before the injected current time
- **THEN** brief and inbox health summaries SHALL count it as expired rather than eligible or active
- **AND** neither command SHALL update SQLite, audit, projection, or Obsidian state

#### Scenario: [KR-30] Task state is still current

- **WHEN** an active task state has no validity end or its validity end is after the injected current time
- **THEN** summaries SHALL count it as active and eligible according to the existing project/global scope rules
