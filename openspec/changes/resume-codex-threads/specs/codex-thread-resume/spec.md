## ADDED Requirements

### Requirement: Resume only explicitly continueable Codex report entries

The assistant SHALL derive Codex resume candidates from the latest Codex task report without reading Codex internal session storage.

#### Scenario: Entry is eligible for resume

- **GIVEN** the latest report has an `unfinished` entry with `thread_id`
- **AND** the entry has `resume_eligible: true`
- **AND** the entry has `resume_prompt` or `next_action`
- **WHEN** the user runs `/r`
- **THEN** the assistant SHALL list the thread as resumeable
- **AND** it SHALL show the task row with a stable index.

#### Scenario: Continueable status is eligible

- **GIVEN** the latest report has an `unfinished` entry with `thread_id`
- **AND** the entry has status or classification `continueable`, `paused`, `ready`, `needs_action`, or `needs_resume`
- **AND** the entry has `resume_prompt` or `next_action`
- **WHEN** the user runs `/r`
- **THEN** the assistant SHALL list the thread as resumeable.

#### Scenario: Legacy unfinished entry with next action is normalized

- **GIVEN** the latest report has an `unfinished` entry with `thread_id`
- **AND** the entry has status `unfinished`
- **AND** the entry has `next_action`
- **AND** the entry has no blocked/user-needed status or manual-action prompt marker
- **WHEN** the user runs `/r`
- **THEN** the assistant SHALL treat the entry as resumeable.

#### Scenario: Manual-action unfinished entry remains skipped

- **GIVEN** the latest report has an `unfinished` entry with `thread_id`
- **AND** the entry has `next_action` that asks for manual confirmation or user input
- **WHEN** the user runs `/r`
- **THEN** the assistant SHALL not treat that entry as resumeable.

#### Scenario: Blocked and completed entries are skipped

- **GIVEN** the latest report contains blocked and completed Codex entries
- **WHEN** the user runs `/r`
- **THEN** the assistant SHALL not mark those entries resumeable
- **AND** it SHALL report skip reasons for blocked or completed entries when they are relevant to the selection.

#### Scenario: Ambiguous entries are skipped

- **GIVEN** an unfinished entry lacks a thread id, lacks a continuation prompt, or is classified as needing user/human input
- **WHEN** the user runs `/r`
- **THEN** the assistant SHALL skip the entry
- **AND** it SHALL report the specific reason.

### Requirement: Codex resume dry-run is read-only

The assistant SHALL support a dry-run mode that previews Codex resume actions without sending messages or writing local Evidence.

#### Scenario: Dry-run does not call resume client

- **GIVEN** a latest report contains one resumeable thread
- **WHEN** the user runs `/r`
- **THEN** the assistant SHALL not call the Codex resume client
- **AND** it SHALL not add Evidence.

#### Scenario: Dry-run uses table output

- **GIVEN** a latest report contains resumeable and skipped threads
- **WHEN** the user runs `/r`
- **THEN** the assistant SHALL render a progress summary with separate readable fixed-width text tables for resumeable and skipped threads
- **AND** each visible row SHALL include a stable index, current progress, and next direction for the current latest report.

### Requirement: Codex resume sends continuation prompts through an injectable client

The assistant SHALL send continuation prompts only through a configured or injected Codex resume client.

#### Scenario: Resume client sends prompt

- **GIVEN** a latest report contains one resumeable thread
- **AND** a working Codex resume client is configured
- **WHEN** the user runs `/r all`
- **THEN** the assistant SHALL send the continuation prompt to that thread
- **AND** it SHALL report the thread id, title, and send outcome.

#### Scenario: Resume client unavailable

- **GIVEN** a latest report contains one resumeable thread
- **AND** no working Codex resume client is configured
- **WHEN** the user runs `/r all`
- **THEN** the assistant SHALL report that the resume client is unavailable
- **AND** it SHALL not crash.

#### Scenario: Targeted resume only evaluates one thread

- **GIVEN** the latest report contains multiple unfinished threads
- **WHEN** the user runs `/r 1`
- **THEN** the assistant SHALL only evaluate the thread shown at index `1`
- **AND** it SHALL not send prompts to other threads.

#### Scenario: Targeted resume accepts table index

- **GIVEN** the latest report table shows a resumeable thread at index `1`
- **WHEN** the user runs `/r 1`
- **THEN** the assistant SHALL resolve index `1` to that thread id
- **AND** it SHALL only evaluate that thread.

### Requirement: Codex resume attempts are recorded as local Evidence

The assistant SHALL record each non-dry-run Codex resume attempt in the local Evidence journal for the matching Codex WorkItem.

#### Scenario: Successful attempt records evidence

- **GIVEN** a matching Codex WorkItem exists for a resumeable thread
- **WHEN** `/r all` sends the prompt successfully
- **THEN** the assistant SHALL append Evidence with source `codex`
- **AND** the Evidence SHALL include the thread id, success outcome, prompt excerpt, and a stable prompt hash marker.

#### Scenario: Missing WorkItem is created before evidence

- **GIVEN** no local WorkItem exists for a resumeable thread
- **WHEN** `/r all` attempts to send the prompt
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

### Requirement: Manual exclusions suppress automatic Codex resume

The assistant SHALL allow the user to persistently exclude Codex threads from bulk and watch auto-resume until the user explicitly removes the exclusion.

#### Scenario: Bulk resume skips manually excluded thread

- **GIVEN** the latest report contains three resumeable unfinished entries
- **AND** one thread id is in the manual exclusion list
- **WHEN** the user runs `/r all`
- **THEN** the assistant SHALL send continuation prompts only for the two non-excluded threads
- **AND** it SHALL report the excluded thread as skipped.

#### Scenario: Needs-user entries remain skipped while safe entries continue

- **GIVEN** the latest report contains five unfinished entries
- **AND** three entries are resumeable
- **AND** two entries are classified as needing user input
- **WHEN** the user runs `/r all`
- **THEN** the assistant SHALL attempt only the three resumeable entries
- **AND** it SHALL report the two user-input entries as skipped.

#### Scenario: User removes manual exclusion

- **GIVEN** a thread id is in the manual exclusion list
- **WHEN** the user runs `/r unskip <序号>`
- **THEN** the assistant SHALL remove that thread id from the exclusion list
- **AND** future bulk and watch auto-resume runs SHALL consider it normally.

#### Scenario: User excludes by table index

- **GIVEN** the latest report table shows a thread at index `2`
- **WHEN** the user runs `/r skip 2`
- **THEN** the assistant SHALL resolve index `2` to that thread id
- **AND** it SHALL persist that thread id in the manual exclusion list.

#### Scenario: Targeted manual resume bypasses automatic exclusion

- **GIVEN** a thread id is in the manual exclusion list
- **AND** the latest report marks that thread resumeable
- **WHEN** the user runs `/r <序号>`
- **THEN** the assistant SHALL evaluate that single thread as an explicit manual action
- **AND** it SHALL not skip it because of the automatic-resume exclusion.

#### Scenario: Bulk resume skips repeated successful prompt

- **GIVEN** a thread was previously resumed successfully with the same continuation prompt
- **AND** the latest report still contains the same resumeable thread and prompt
- **WHEN** the user runs bulk `/r all` or `/sync watch --resume`
- **THEN** the assistant SHALL not send the same prompt again
- **AND** it SHALL report the thread as skipped because it was already resumed successfully for that prompt.

#### Scenario: Bulk resume skips repeated failed prompt

- **GIVEN** a thread previously failed resume with the same continuation prompt
- **AND** the latest report still contains the same resumeable thread and prompt
- **WHEN** the user runs bulk `/r all` or `/sync watch --resume`
- **THEN** the assistant SHALL not send the same prompt again
- **AND** it SHALL report the thread as skipped because it already failed for that prompt.

#### Scenario: Bulk resume does not confuse different long prompts

- **GIVEN** a thread was previously resumed successfully with a long continuation prompt
- **AND** the latest report contains a different long prompt whose display excerpt prefix is the same
- **WHEN** the user runs bulk `/r all` or `/sync watch --resume`
- **THEN** the assistant SHALL compare stable prompt hash markers
- **AND** it SHALL not skip the thread as already resumed for the same prompt.

#### Scenario: Targeted manual resume may repeat a prompt

- **GIVEN** a thread was previously resumed successfully with the same continuation prompt
- **AND** the latest report still contains the same resumeable thread and prompt
- **WHEN** the user runs `/r <序号>`
- **THEN** the assistant SHALL treat that as an explicit manual action
- **AND** it MAY send the prompt again.
