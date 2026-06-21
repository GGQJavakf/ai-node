## ADDED Requirements

### Requirement: Default list provides daily triage groups

The assistant SHALL make bare `/list` render a daily triage view that groups local WorkItems and Todo reminders by actionability and delivery risk.

#### Scenario: Blocked work is grouped first

- **GIVEN** one or more active local WorkItems have status `blocked`
- **WHEN** the user runs `/list`
- **THEN** the output SHALL include a `blocked` group
- **AND** blocked WorkItems SHALL appear before lower-risk Todo reminders.

#### Scenario: Active work with a next action is grouped

- **GIVEN** one or more local WorkItems have status `active` and a non-empty `next_action`
- **WHEN** the user runs `/list`
- **THEN** the output SHALL include an `active needs action` group
- **AND** those WorkItems SHALL show their next action or sync summary.

#### Scenario: Closeout work is grouped separately

- **GIVEN** a local WorkItem contains local text, identities, or source refs indicating MR, Redmine, or OpenSpec closeout is still pending
- **WHEN** the user runs `/list`
- **THEN** the output SHALL include a `waiting closeout` group
- **AND** that WorkItem SHALL show a closeout-specific reason.

#### Scenario: Recently completed work is visible

- **GIVEN** one or more WorkItems have status `done`
- **WHEN** the user runs `/list`
- **THEN** the output SHALL include a `recently completed` group
- **AND** the group SHALL show a small recent slice of completed WorkItems without replacing `/list completed`.

#### Scenario: Stale sync work is grouped

- **GIVEN** one or more active or blocked WorkItems were not synced today
- **WHEN** the user runs `/list`
- **THEN** the output SHALL include a `stale sync` group or stale marker
- **AND** each stale WorkItem row SHALL visibly include a stale marker.

#### Scenario: Todo reminders remain visible

- **GIVEN** at least one incomplete Todo exists
- **WHEN** the user runs `/list`
- **THEN** the output SHALL include Todo reminders
- **AND** the Todo rows SHALL remain distinguishable from WorkItems by source.

### Requirement: Daily triage sorting prioritizes delivery risk

The assistant SHALL sort default `/list` entries so delivery-risk WorkItems appear before low-priority Todo reminders.

#### Scenario: Risky WorkItem outranks low-priority Todo

- **GIVEN** a low-priority incomplete Todo exists
- **AND** an active or blocked WorkItem has a delivery risk reason
- **WHEN** the user runs `/list`
- **THEN** the WorkItem SHALL appear before the low-priority Todo.

#### Scenario: Item appears once in highest applicable group

- **GIVEN** a WorkItem is both blocked and stale
- **WHEN** the user runs `/list`
- **THEN** the WorkItem SHALL appear once in the highest-ranked applicable group
- **AND** the row SHALL still show the stale marker.

#### Scenario: Priority and recency break ties

- **GIVEN** multiple WorkItems exist in the same daily triage group
- **WHEN** the user runs `/list`
- **THEN** higher-priority WorkItems SHALL appear before lower-priority WorkItems
- **AND** items with the same priority SHALL use recent update time as a tie breaker.

### Requirement: WorkItems explain high-priority risk reasons

The assistant SHALL show a concise local reason for each high-priority or delivery-risk WorkItem in the default `/list` view.

#### Scenario: Redmine blocker reason

- **GIVEN** a blocked WorkItem is associated with Redmine through source, source ref, identity, title, next action, or sync summary
- **WHEN** the user runs `/list`
- **THEN** the WorkItem row SHALL show `blocked by Redmine` or an equivalent short Redmine blocker reason.

#### Scenario: Validation reason

- **GIVEN** an active WorkItem has next action or sync summary text indicating validation, tests, review, or acceptance evidence is needed
- **WHEN** the user runs `/list`
- **THEN** the WorkItem row SHALL show `needs validation` or an equivalent short validation reason.

#### Scenario: MR closeout reason

- **GIVEN** a WorkItem local text indicates an MR is merged but closeout is missing
- **WHEN** the user runs `/list`
- **THEN** the WorkItem row SHALL show `MR merged but closeout missing` or an equivalent short closeout reason.

#### Scenario: Codex active reason

- **GIVEN** an active WorkItem comes from a Codex thread and has no more specific risk reason
- **WHEN** the user runs `/list`
- **THEN** the WorkItem row SHALL show `Codex thread still active` or an equivalent short active-thread reason.

### Requirement: Stale marker is based on today's sync date

The assistant SHALL mark active or blocked WorkItems as stale in default `/list` when their `last_synced_at` value is missing, invalid, or older than the local current date.

#### Scenario: WorkItem synced yesterday is stale today

- **GIVEN** a WorkItem has status `active`
- **AND** `last_synced_at` is earlier than the local current date
- **WHEN** the user runs `/list`
- **THEN** the row SHALL include a visible stale marker.

#### Scenario: WorkItem synced today is current

- **GIVEN** a WorkItem has status `active`
- **AND** `last_synced_at` is on the local current date
- **WHEN** the user runs `/list`
- **THEN** the row SHALL NOT include the stale marker.

#### Scenario: Completed old WorkItem is not stale

- **GIVEN** a WorkItem has status `done`
- **AND** `last_synced_at` is earlier than the local current date
- **WHEN** the user runs `/list`
- **THEN** the completed row SHALL NOT be marked stale only because of that older sync timestamp.

### Requirement: Existing list filters remain compatible

The assistant SHALL preserve existing detailed `/list` filters while changing only the bare `/list` default view.

#### Scenario: Completed list remains detailed

- **GIVEN** done WorkItems and completed Todos exist
- **WHEN** the user runs `/list completed`
- **THEN** the output SHALL show completed entries using the existing detailed completed-list behavior
- **AND** it SHALL NOT require daily triage groups to be present.

#### Scenario: Completed source filter remains compatible

- **GIVEN** completed WorkItems exist from Codex and another source
- **WHEN** the user runs `/list completed --source codex`
- **THEN** the output SHALL include completed Codex WorkItems
- **AND** it SHALL exclude completed WorkItems from other sources.

#### Scenario: Todo source filter remains compatible

- **GIVEN** both Todos and WorkItems exist
- **WHEN** the user runs `/list --source todo`
- **THEN** the output SHALL include Todo rows
- **AND** it SHALL suppress WorkItem rows.
