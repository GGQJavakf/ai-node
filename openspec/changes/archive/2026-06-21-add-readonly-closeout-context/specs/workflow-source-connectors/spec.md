## MODIFIED Requirements

### Requirement: Read external workflow facts through existing tools

The assistant SHALL read external workflow facts by invoking existing local tools rather than implementing duplicate Redmine, GitLab, Playbook, or OpenSpec clients.

#### Scenario: Read Playbook closeout gaps

- **WHEN** the assistant synchronizes project context for a Playbook-managed workspace
- **THEN** it SHALL read Playbook closeout or closure gap facts with a dry-run/read-only command
- **AND** it SHALL expose those facts as structured source snapshots
- **AND** it SHALL label those facts as observations or recommendations, not completed actions.

#### Scenario: Read closeout context without external writes

- **WHEN** the assistant reads Redmine, MR, OpenSpec, Git, or Playbook facts for closeout context
- **THEN** it SHALL use existing read-only connectors or existing local snapshot files
- **AND** it SHALL NOT write Redmine, GitLab/MR, OpenSpec, Playbook, Git branches, time entries, or remote repositories.

### Requirement: Connector failures degrade to explicit unavailable snapshots

Connectors SHALL return explicit unavailable snapshots when commands are missing, fail, or return unparsable output.

#### Scenario: Closeout tool unavailable

- **WHEN** Playbook, OpenSpec, or Git is unavailable while synchronizing closeout context
- **THEN** the connector SHALL return `success=false`
- **AND** the snapshot SHALL include a concise error and output excerpt when available
- **AND** the CLI SHALL continue by persisting the unavailable snapshot as local Evidence instead of aborting the whole sync.

### Requirement: Connector operations are read-only

The first version of workflow connectors SHALL perform only read-only operations.

#### Scenario: Project sync reads closeout context

- **WHEN** the user runs `/sync [path]`
- **THEN** the assistant MAY run read-only Git, OpenSpec, and Playbook commands
- **AND** it SHALL NOT run Playbook `closeout --apply`, OpenSpec archive/sync mutation commands, GitLab/MR writes, Redmine writes, time logging, merge, finalize, cleanup, publish, or push commands.
