## ADDED Requirements

### Requirement: User can view task statistics
The system SHALL provide statistics including total tasks, completed tasks, pending tasks, overdue tasks, and completion rate.

#### Scenario: View task statistics
- **WHEN** user executes `/stats`
- **THEN** system displays:
  - Total tasks count
  - Completed tasks count
  - Pending tasks count
  - Overdue tasks count
  - Upcoming tasks count
  - Completion rate percentage

#### Scenario: Statistics with no tasks
- **WHEN** user executes `/stats` with no tasks
- **THEN** system displays "No tasks available" with all counts at 0

### Requirement: Completion rate calculated correctly
The system SHALL calculate completion rate as (completed / total) * 100.

#### Scenario: Calculate completion rate
- **WHEN** there are 10 tasks and 3 are completed
- **THEN** completion rate is displayed as 30%