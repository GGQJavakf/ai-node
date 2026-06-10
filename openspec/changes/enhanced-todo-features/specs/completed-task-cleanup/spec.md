## ADDED Requirements

### Requirement: User can clear completed tasks
The system SHALL allow users to remove all completed tasks with a single command.

#### Scenario: Clear completed tasks
- **WHEN** user executes `/clear`
- **THEN** system removes all tasks with completed=true

#### Scenario: Confirmation before clearing
- **WHEN** user executes `/clear`
- **THEN** system asks for confirmation before deleting
- **AND** user confirms
- **THEN** completed tasks are removed

#### Scenario: No completed tasks to clear
- **WHEN** user executes `/clear` with no completed tasks
- **THEN** system displays "No completed tasks to clear"

### Requirement: User can undo clear operation
The system SHOULD provide a way to recover recently cleared tasks (optional enhancement).

#### Scenario: No undo available (basic implementation)
- **WHEN** user clears completed tasks
- **THEN** tasks are permanently removed (no undo in basic version)