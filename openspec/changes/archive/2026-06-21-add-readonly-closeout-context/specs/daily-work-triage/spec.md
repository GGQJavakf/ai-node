## MODIFIED Requirements

### Requirement: Default list provides daily triage groups

The assistant SHALL make bare `/list` render a daily triage view that groups local WorkItems and Todo reminders by actionability and delivery risk.

#### Scenario: Closeout work is grouped separately

- **GIVEN** a local WorkItem contains local text, identities, source refs, sync summaries, or Evidence indicating MR, Redmine, or OpenSpec closeout is still pending
- **WHEN** the user runs `/list`
- **THEN** the output SHALL include a `waiting closeout` group
- **AND** that WorkItem SHALL show a closeout-specific reason.

### Requirement: WorkItems explain high-priority risk reasons

The assistant SHALL show a concise local reason for each high-priority or delivery-risk WorkItem in the default `/list` view.

#### Scenario: MR merged but Redmine not closed reason

- **GIVEN** a local WorkItem has Evidence indicating an MR is merged but the related Redmine issue is not closed
- **WHEN** the user runs `/list`
- **THEN** the WorkItem row SHALL show `MR merged but Redmine not closed` or an equivalent short closeout reason.

#### Scenario: Redmine resolved but validation evidence missing reason

- **GIVEN** a local WorkItem has Evidence indicating Redmine is resolved or closed but local validation evidence is missing
- **WHEN** the user runs `/list`
- **THEN** the WorkItem row SHALL show `Redmine resolved but validation evidence missing` or an equivalent short closeout reason.

#### Scenario: OpenSpec completed but not archived reason

- **GIVEN** a local WorkItem has Evidence indicating OpenSpec tasks or artifacts are completed but the change is not archived
- **WHEN** the user runs `/list`
- **THEN** the WorkItem row SHALL show `OpenSpec completed but not archived` or an equivalent short closeout reason.

#### Scenario: List remains local-only

- **WHEN** the user runs `/list`
- **THEN** the assistant SHALL derive closeout reasons from local WorkItems and Evidence only
- **AND** it SHALL NOT invoke Redmine, GitLab/MR, OpenSpec, Playbook, Git, or Codex commands.
