# task-search Specification

## Purpose
TBD - created by archiving change enhanced-todo-features. Update Purpose after archive.
## Requirements
### Requirement: User can search tasks by keyword
The system SHALL allow users to search tasks by keyword in title and description.

#### Scenario: Search tasks by keyword in title
- **WHEN** user executes `/search report`
- **THEN** system displays all tasks where title contains "report" (case-insensitive)

#### Scenario: Search tasks by keyword in description
- **WHEN** user executes `/search urgent`
- **THEN** system displays all tasks where description contains "urgent" (case-insensitive)

#### Scenario: Search with no results
- **WHEN** user executes `/search nonexistent`
- **THEN** system displays "No tasks found matching 'nonexistent'"

### Requirement: Search is case-insensitive
The system SHALL perform case-insensitive search matching.

#### Scenario: Case-insensitive search
- **WHEN** user executes `/search PROJECT`
- **THEN** system displays tasks with "project" or "Project" in title or description

