# persistent-preferences Specification

## Purpose
TBD - created by archiving change enhanced-todo-features. Update Purpose after archive.
## Requirements
### Requirement: User can persist long-term preferences
The system SHALL allow users and the Agent tool layer to persist stable user preferences by key and value.

#### Scenario: Remember preference from CLI
- **WHEN** user executes `/remember 工作时间 工作日 09:30-18:30`
- **THEN** system stores key `工作时间` with value `工作日 09:30-18:30`

#### Scenario: List preferences from CLI
- **WHEN** user executes `/preferences`
- **THEN** system displays all stored long-term preferences

#### Scenario: Forget preference from CLI
- **WHEN** user executes `/forget 工作时间`
- **THEN** system removes the `工作时间` preference

### Requirement: Agent can manage long-term preferences
The system SHALL expose tools for remembering, listing, and forgetting long-term preferences.

#### Scenario: Agent remembers preference
- **WHEN** the model calls `remember_preference` with `key` and `value`
- **THEN** the tool executor persists that preference

#### Scenario: Agent lists preferences
- **WHEN** the model calls `list_preferences`
- **THEN** the tool executor returns all stored preferences

#### Scenario: Agent forgets preference
- **WHEN** the model calls `forget_preference` with `key`
- **THEN** the tool executor removes that preference if it exists

### Requirement: Agent prompt includes long-term preferences
The system SHALL include stored long-term preferences in the Agent system prompt.

#### Scenario: Build system prompt with preferences
- **WHEN** preferences exist in the active repository
- **THEN** `AgentCore` includes them in the "长期偏好" section

### Requirement: Preferences survive process restart
The system SHALL persist preferences across repository instances.

#### Scenario: SQLite preference persistence
- **WHEN** a preference is stored in a SQLite repository
- **THEN** a new repository instance for the same database can read that preference

#### Scenario: JSON preference persistence
- **WHEN** a preference is stored through the JSON repository
- **THEN** a new JSON repository instance for the same data file can read that preference from its sidecar preference file

