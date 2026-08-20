## ADDED Requirements

### Requirement: Users can explicitly map a non-Git workspace
The system SHALL provide an audited workspace mapping command that binds one existing canonical non-symlink directory to one validated project target without requiring that directory to be a Git worktree.

#### Scenario: [WR-01] Map a multi-repository workspace
- **WHEN** the user explicitly maps a valid non-Git workspace root to a project
- **THEN** the system SHALL persist one active `workspace` mapping and return its stable mapping id
- **AND** it SHALL NOT initialize Git, scan child repositories, or modify files under the workspace

#### Scenario: [WR-02] Reject an unsafe workspace root
- **WHEN** the supplied workspace root is missing, not a directory, a symlink, or cannot be canonicalized safely
- **THEN** the system SHALL reject the mapping and persist no partial change

### Requirement: Workspace routing is deterministic and fail closed
The system SHALL match session working directories by canonical containment, select the longest matching workspace root, and stop on incompatible Git/workspace or equal-specificity evidence.

#### Scenario: [WR-03] Contained session resolves to the workspace project
- **WHEN** a session cwd is the configured workspace root or a contained path and no incompatible mapping matches
- **THEN** the system SHALL route the session to that workspace project

#### Scenario: [WR-04] Nested workspace mapping is more specific
- **WHEN** active parent and nested workspace mappings both contain the session cwd and target compatible projects
- **THEN** the system SHALL select the longest matching root

#### Scenario: [WR-05] Git and workspace mappings disagree
- **WHEN** Git identity resolves the session to one project and a containing workspace resolves it to another
- **THEN** the system SHALL classify routing as ambiguous and SHALL NOT automatically review or project knowledge

### Requirement: Mapping lifecycle remains observable and reversible
The system SHALL list mapping kind and canonical root, audit create and deactivate actions, and allow existing awaiting sessions to be reclassified through either mapping kind without recapture.

#### Scenario: [WR-06] List and remove a workspace mapping
- **WHEN** the user lists mappings and deactivates a workspace mapping id
- **THEN** the system SHALL expose its kind, root, target and active state and SHALL stop using it for new captures
