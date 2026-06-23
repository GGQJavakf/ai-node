## ADDED Requirements

### Requirement: Resume only explicitly continueable Codex report entries

The assistant SHALL derive Codex resume candidates from the latest Codex task report without reading Codex internal session storage.

#### Scenario: Entry is eligible for resume

- **GIVEN** the latest report has an `unfinished` entry with `thread_id`
- **AND** the entry has `resume_eligible: true`
- **AND** the entry has `resume_prompt` or `next_action`
- **WHEN** the user runs `/codex resume --dry-run`
- **THEN** the assistant SHALL list the thread as resumeable
- **AND** it SHALL show the prompt that would be sent.

#### Scenario: Continueable status is eligible

- **GIVEN** the latest report has an `unfinished` entry with `thread_id`
- **AND** the entry has status or classification `continueable`, `paused`, `ready`, `needs_action`, or `needs_resume`
- **AND** the entry has `resume_prompt` or `next_action`
- **WHEN** the user runs `/codex resume --dry-run`
- **THEN** the assistant SHALL list the thread as resumeable.

#### Scenario: Blocked and completed entries are skipped

- **GIVEN** the latest report contains blocked and completed Codex entries
- **WHEN** the user runs `/codex resume --dry-run`
- **THEN** the assistant SHALL not mark those entries resumeable
- **AND** it SHALL report skip reasons for blocked or completed entries when they are relevant to the selection.

#### Scenario: Ambiguous entries are skipped

- **GIVEN** an unfinished entry lacks a thread id, lacks a continuation prompt, or is classified as needing user/human input
- **WHEN** the user runs `/codex resume --dry-run`
- **THEN** the assistant SHALL skip the entry
- **AND** it SHALL report the specific reason.

### Requirement: Codex resume dry-run is read-only

The assistant SHALL support a dry-run mode that previews Codex resume actions without sending messages or writing local Evidence.

#### Scenario: Dry-run does not call resume client

- **GIVEN** a latest report contains one resumeable thread
- **WHEN** the user runs `/codex resume --dry-run`
- **THEN** the assistant SHALL not call the Codex resume client
- **AND** it SHALL not add Evidence.

### Requirement: Codex resume sends continuation prompts through an injectable client

The assistant SHALL send continuation prompts only through a configured or injected Codex resume client.

#### Scenario: Resume client sends prompt

- **GIVEN** a latest report contains one resumeable thread
- **AND** a working Codex resume client is configured
- **WHEN** the user runs `/codex resume`
- **THEN** the assistant SHALL send the continuation prompt to that thread
- **AND** it SHALL report the thread id, title, and send outcome.

#### Scenario: Resume client unavailable

- **GIVEN** a latest report contains one resumeable thread
- **AND** no working Codex resume client is configured
- **WHEN** the user runs `/codex resume`
- **THEN** the assistant SHALL report that the resume client is unavailable
- **AND** it SHALL not crash.

#### Scenario: Targeted resume only evaluates one thread

- **GIVEN** the latest report contains multiple unfinished threads
- **WHEN** the user runs `/codex resume thread-1`
- **THEN** the assistant SHALL only evaluate `thread-1`
- **AND** it SHALL not send prompts to other threads.

### Requirement: Codex resume attempts are recorded as local Evidence

The assistant SHALL record each non-dry-run Codex resume attempt in the local Evidence journal for the matching Codex WorkItem.

#### Scenario: Successful attempt records evidence

- **GIVEN** a matching Codex WorkItem exists for a resumeable thread
- **WHEN** `/codex resume` sends the prompt successfully
- **THEN** the assistant SHALL append Evidence with source `codex`
- **AND** the Evidence SHALL include the thread id, success outcome, and prompt excerpt.

#### Scenario: Missing WorkItem is created before evidence

- **GIVEN** no local WorkItem exists for a resumeable thread
- **WHEN** `/codex resume` attempts to send the prompt
- **THEN** the assistant SHALL create a Codex WorkItem from the report entry
- **AND** it SHALL append Evidence to that WorkItem.

### Requirement: Sync watch can optionally resume safe Codex threads

The assistant SHALL allow sync watch to optionally run Codex resume after each sync trigger.

#### Scenario: User runs sync watch with resume

- **WHEN** the user runs `/sync watch --resume --once`
- **THEN** the assistant SHALL run one sync trigger
- **AND** it SHALL run Codex resume for safe candidates after the sync trigger
- **AND** the trigger report SHALL include resume results.

#### Scenario: Existing sync watch remains reporting-only by default

- **WHEN** the user runs `/sync watch --once` without `--resume`
- **THEN** the assistant SHALL preserve existing sync watch behavior
- **AND** it SHALL not call the Codex resume client.
