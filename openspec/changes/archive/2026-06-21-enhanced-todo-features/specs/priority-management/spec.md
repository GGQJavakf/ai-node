## ADDED Requirements

### Requirement: User can set task priority
The system SHALL allow users to specify priority when adding tasks: high, medium, or low.

#### Scenario: Add task with high priority
- **WHEN** user executes `/add high Finish project report`
- **THEN** system creates a task with priority="high"

#### Scenario: Add task with medium priority
- **WHEN** user executes `/add medium Review code`
- **THEN** system creates a task with priority="medium"

#### Scenario: Add task with low priority
- **WHEN** user executes `/add low Read documentation`
- **THEN** system creates a task with priority="low"

#### Scenario: Add task without priority defaults to medium
- **WHEN** user executes `/add Buy groceries`
- **THEN** system creates a task with priority="medium"

### Requirement: User can update task priority
The system SHALL allow users to update the priority of an existing task.

#### Scenario: Update task priority
- **WHEN** user executes `/update <task-id> priority high`
- **THEN** system updates the task's priority to "high"

### Requirement: User can filter tasks by priority
The system SHALL allow users to filter tasks based on priority level.

#### Scenario: Filter high priority tasks
- **WHEN** user executes `/list high`
- **THEN** system displays only tasks with priority="high"