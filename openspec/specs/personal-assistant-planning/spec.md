# personal-assistant-planning Specification

## Purpose
TBD - created by archiving change enhanced-todo-features. Update Purpose after archive.
## Requirements
### Requirement: User can view a daily assistant briefing
The system SHALL provide a daily assistant briefing that highlights today's tasks, overdue tasks, upcoming tasks, and unfinished high-priority tasks.

#### Scenario: View daily briefing
- **WHEN** user executes `/today`
- **THEN** system displays a "今日简报" section
- **AND** system includes counts for today-related, overdue, upcoming, and high-priority unfinished tasks
- **AND** system lists priority tasks under "优先处理"

### Requirement: User can generate a daily plan
The system SHALL provide a deterministic daily plan for unfinished tasks.

#### Scenario: Generate daily plan
- **WHEN** user executes `/plan day`
- **THEN** system displays a "今日计划" section
- **AND** unfinished tasks are ordered before display

#### Scenario: Daily plan ordering
- **WHEN** unfinished tasks include overdue, high-priority, medium-priority, and low-priority items
- **THEN** overdue tasks are listed first
- **AND** remaining tasks are ordered by priority, due time, and created time

#### Scenario: No pending tasks
- **WHEN** user executes `/plan day` with no unfinished tasks
- **THEN** system displays a message that there are no unfinished tasks

