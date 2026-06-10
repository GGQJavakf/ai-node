## ADDED Requirements

### Requirement: Overdue tasks displayed in red
The system SHALL display overdue tasks in red color.

#### Scenario: Display overdue task in red
- **WHEN** a task's end_time is before current time
- **THEN** task is displayed with red text

### Requirement: Upcoming tasks displayed in orange
The system SHALL display tasks due within 2 days in orange color.

#### Scenario: Display upcoming task in orange
- **WHEN** a task's end_time is within 2 days from now
- **THEN** task is displayed with orange text

### Requirement: Completed tasks displayed in gray
The system SHALL display completed tasks in gray color.

#### Scenario: Display completed task in gray
- **WHEN** a task is marked as completed
- **THEN** task is displayed with gray text

### Requirement: Priority indicators displayed
The system SHALL display priority indicators with color-coded markers.

#### Scenario: Display high priority marker
- **WHEN** a task has priority="high"
- **THEN** task is displayed with 🔴 indicator

#### Scenario: Display medium priority marker
- **WHEN** a task has priority="medium"
- **THEN** task is displayed with 🟡 indicator

#### Scenario: Display low priority marker
- **WHEN** a task has priority="low"
- **THEN** task is displayed with 🟢 indicator