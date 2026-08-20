## ADDED Requirements

### Requirement: Catalog includes OpenSpec validation and Playbook workspace status
The assistant SHALL expose fixed read-only catalog keys for local OpenSpec validation and Playbook workspace status.

#### Scenario: User lists expanded read-only catalog
- **WHEN** the user runs `/system list`
- **THEN** the assistant SHALL list `openspec.validate`
- **AND** it SHALL list `playbook.workspace_status`
- **AND** both commands SHALL be described as read-only local fact commands.

#### Scenario: OpenSpec validation runs through catalog
- **WHEN** a user or tool call requests `openspec.validate`
- **THEN** the assistant SHALL execute the fixed argv `openspec validate --all --strict --json --no-interactive`
- **AND** it SHALL use no shell
- **AND** it SHALL return only a compact redacted summary.

#### Scenario: Playbook workspace status runs through catalog
- **WHEN** a user or tool call requests `playbook.workspace_status`
- **THEN** the assistant SHALL execute the fixed argv `playbook workspace task status --output json --full`
- **AND** it SHALL use no shell
- **AND** it SHALL return only a compact redacted summary.

#### Scenario: Playbook workspace status degrades without workspace configuration
- **WHEN** `playbook.workspace_status` exits unsuccessfully because the repository has no configured workspace id
- **THEN** the assistant SHALL return a failed command summary with the exit code and compact excerpt
- **AND** it SHALL not throw an unhandled exception
- **AND** it SHALL not create or mutate workspace state.
