## ADDED Requirements

### Requirement: Accepted project knowledge is projected into three aggregate files

The system SHALL synchronize accepted project knowledge into `规则.md`, `经验.md`, and `任务状态.md` under the mapped project's AgentRetro directory.

#### Scenario: Synchronize an accepted rule

- **WHEN** an accepted project-scoped `RULE` is ready for synchronization
- **THEN** the system SHALL create or update its stable entry in `规则.md`

#### Scenario: Synchronize an accepted lesson

- **WHEN** an accepted project-scoped `LESSON` is ready for synchronization
- **THEN** the system SHALL create or update its stable entry in `经验.md`

#### Scenario: Synchronize task state

- **WHEN** an accepted project-scoped `TASK_STATE` is ready for synchronization
- **THEN** the system SHALL create or update its stable entry in `任务状态.md`

#### Scenario: Archive a synchronized item

- **WHEN** synchronized knowledge becomes archived
- **THEN** the system SHALL move its managed entry to the archived section of the corresponding aggregate file
- **AND** it SHALL remove the item from active summaries

### Requirement: Automatic writes stay inside managed boundaries

The system SHALL automatically modify only the three aggregate files, marked AgentRetro project-summary content, marked AgentRetro index links, and append-only AgentRetro log entries.

#### Scenario: Update a managed project summary

- **WHEN** accepted knowledge changes for a mapped project and valid summary markers exist
- **THEN** the system SHALL update only the content between those markers
- **AND** all content outside the markers SHALL remain byte-for-byte unchanged

#### Scenario: Managed boundary is malformed

- **WHEN** a target file has missing, duplicated, nested, or mismatched AgentRetro markers
- **THEN** the system SHALL refuse the automatic write
- **AND** it SHALL report a boundary error without modifying the file

#### Scenario: Target escapes the configured vault

- **WHEN** path traversal or a symlink would resolve a target outside configured AgentRetro state or vault roots
- **THEN** the system SHALL reject the write

### Requirement: Multi-file synchronization is journaled and recoverable

The system SHALL hash and back up every target, journal the run, use same-directory temporary files and replacement, read back every result, and restore all pre-write files if any write or verification fails.

#### Scenario: Multi-file synchronization succeeds

- **WHEN** every planned target passes preflight and every replacement passes readback verification
- **THEN** the system SHALL mark the synchronization complete
- **AND** it SHALL record pre-write and post-write hashes for every target

#### Scenario: A later file write fails

- **WHEN** one target fails after earlier targets were replaced
- **THEN** the system SHALL restore every target to its recorded pre-write content
- **AND** it SHALL verify every restored hash before reporting rollback success

#### Scenario: Restoration fails

- **WHEN** any target cannot be restored or its restored hash is incorrect
- **THEN** the system SHALL mark the run `rollback_required`
- **AND** it SHALL block later automatic synchronization until recovery is completed

#### Scenario: Vault is unavailable

- **WHEN** accepted knowledge cannot be synchronized because the configured vault is unavailable
- **THEN** the knowledge SHALL remain accepted in SQLite
- **AND** the system SHALL mark synchronization `sync_pending` and expose a retry action

### Requirement: External edits are never silently overwritten

The system SHALL compare managed-content hashes before synchronization and SHALL create an `external_edit_conflict` when the vault differs from the last synchronized version.

#### Scenario: Managed content changed externally

- **WHEN** a managed block or aggregate entry hash differs from the recorded synchronized hash
- **THEN** the system SHALL stop before writing that synchronization set
- **AND** it SHALL preserve both database and vault versions for reconciliation

#### Scenario: User adopts the vault edit

- **WHEN** the user selects the vault version during `retro sync reconcile`
- **THEN** the system SHALL import it as an edited candidate with provenance
- **AND** it SHALL require normal review before it becomes active knowledge

#### Scenario: User keeps the database version

- **WHEN** the user selects the database version during reconciliation
- **THEN** the system SHALL display the replacement diff and require confirmation before updating the managed vault content

### Requirement: Deep merge requires a current confirmed plan

The system SHALL keep deep organization of user-authored notes separate from automatic synchronization and SHALL write outside managed boundaries only through an explicitly applied merge plan.

#### Scenario: Generate a merge plan

- **WHEN** the user requests semantic organization for a project
- **THEN** the system SHALL generate a plan containing target files, complete diffs, input hashes, conflicts, and any delete, rename, or move operations
- **AND** it SHALL NOT modify the vault

#### Scenario: Apply a current safe merge plan

- **WHEN** the user explicitly applies a plan whose target hashes still match and which has no unconfirmed delete, rename, move, or conflict
- **THEN** the system SHALL execute it through the journaled backup and readback protocol

#### Scenario: Merge plan is stale

- **WHEN** any target hash differs from the hash recorded in the merge plan
- **THEN** the system SHALL refuse the apply
- **AND** it SHALL require a new plan

#### Scenario: Merge plan contains destructive changes

- **WHEN** a plan contains a delete, rename, move, or unresolved conflict
- **THEN** the system SHALL require explicit confirmation for those exact operations
- **AND** it SHALL NOT treat general merge confirmation as authorization

### Requirement: Synchronization backups are retained by default

The system SHALL retain synchronization and merge backups until the user explicitly requests cleanup.

#### Scenario: Synchronization completes

- **WHEN** a synchronization or merge run succeeds
- **THEN** its pre-write backup SHALL remain available for inspection and recovery
- **AND** no automatic backup cleanup SHALL run in the MVP
