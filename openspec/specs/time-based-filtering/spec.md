# time-based-filtering Specification

## Purpose
TBD - created by archiving change enhanced-todo-features. Update Purpose after archive.
## Requirements
### Requirement: User can filter tasks by today
The system SHALL allow users to view only tasks due today using `/list today` command.

#### Scenario: Filter tasks by today
- **WHEN** user executes `/list today`
- **THEN** system displays only tasks with end_time equal to today

### Requirement: User can filter tasks by week
The system SHALL allow users to view tasks due this week using `/list week` command.

#### Scenario: Filter tasks by week
- **WHEN** user executes `/list week`
- **THEN** system displays tasks with end_time in the current calendar week

### Requirement: User can filter tasks by month
The system SHALL allow users to view tasks due this month using `/list month` command.

#### Scenario: Filter tasks by month
- **WHEN** user executes `/list month`
- **THEN** system displays tasks with end_time in the current calendar month

### Requirement: User can filter tasks by upcoming
The system SHALL allow users to view tasks due within 2 days using `/list upcoming` command.

#### Scenario: Filter tasks by upcoming
- **WHEN** user executes `/list upcoming`
- **THEN** system displays tasks with end_time within the next 2 days

### Requirement: User can filter tasks by overdue
The system SHALL allow users to view tasks that are past their due date using `/list overdue` command.

#### Scenario: Filter tasks by overdue
- **WHEN** user executes `/list overdue`
- **THEN** system displays tasks where end_time is before current time

