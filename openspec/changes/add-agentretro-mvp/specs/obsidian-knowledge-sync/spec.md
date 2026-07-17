## ADDED Requirements

### Requirement: Accepted project knowledge is projected into three aggregate files

The system SHALL synchronize accepted project knowledge into `规则.md`, `经验.md`, and `任务状态.md` under the mapped project's AgentRetro directory.

#### Scenario: [OS-01] Synchronize an accepted rule

- **WHEN** an accepted project-scoped `RULE` is ready for synchronization
- **THEN** the system SHALL create or update its stable entry in `规则.md`

#### Scenario: [OS-02] Synchronize an accepted lesson

- **WHEN** an accepted project-scoped `LESSON` is ready for synchronization
- **THEN** the system SHALL create or update its stable entry in `经验.md`

#### Scenario: [OS-03] Synchronize task state

- **WHEN** an accepted project-scoped `TASK_STATE` is ready for synchronization
- **THEN** the system SHALL create or update its stable entry in `任务状态.md`

#### Scenario: [OS-04] Archive a synchronized item

- **WHEN** synchronized knowledge becomes archived
- **THEN** the system SHALL move its managed entry to the archived section of the corresponding aggregate file
- **AND** it SHALL remove the item from active summaries

### Requirement: Automatic writes stay inside managed boundaries

The system SHALL automatically modify only the three aggregate files, marked AgentRetro project-summary content, marked AgentRetro index links, and append-only AgentRetro log entries.

#### Scenario: [OS-05] Update a managed project summary

- **WHEN** accepted knowledge changes for a mapped project and valid summary markers exist
- **THEN** the system SHALL update only the content between those markers
- **AND** all content outside the markers SHALL remain byte-for-byte unchanged

#### Scenario: [OS-06] Managed boundary is malformed

- **WHEN** a target file has missing, duplicated, nested, or mismatched AgentRetro markers
- **THEN** the system SHALL refuse the automatic write
- **AND** it SHALL report a boundary error without modifying the file

#### Scenario: [OS-07] Target escapes the configured vault

- **WHEN** path traversal or a symlink would resolve a target outside configured AgentRetro state or vault roots
- **THEN** the system SHALL reject the write

### Requirement: Multi-file synchronization is journaled and recoverable

The system SHALL hash and back up every target, journal the run, use same-directory temporary files and replacement, read back every result, and restore all pre-write files if any write or verification fails.

#### Scenario: [OS-08] Multi-file synchronization succeeds

- **WHEN** every planned target passes preflight and every replacement passes readback verification
- **THEN** the system SHALL mark the synchronization complete
- **AND** it SHALL record pre-write and post-write hashes for every target

#### Scenario: [OS-09] A later file write fails

- **WHEN** one target fails after earlier targets were replaced
- **THEN** the system SHALL restore every target to its recorded pre-write content
- **AND** it SHALL verify every restored hash before reporting rollback success

#### Scenario: [OS-10] Restoration fails

- **WHEN** any target cannot be restored or its restored hash is incorrect
- **THEN** the system SHALL mark the run `rollback_required`
- **AND** it SHALL block later automatic synchronization until recovery is completed

#### Scenario: [OS-11] Vault is unavailable

- **WHEN** accepted knowledge cannot be synchronized because the configured vault is unavailable
- **THEN** the knowledge SHALL remain accepted in SQLite
- **AND** the system SHALL mark synchronization `sync_pending` and expose a retry action

### Requirement: External edits are never silently overwritten

The system SHALL compare managed-content hashes before synchronization and SHALL create an `external_edit_conflict` when the vault differs from the last synchronized version.

#### Scenario: [OS-12] Managed content changed externally

- **WHEN** a managed block or aggregate entry hash differs from the recorded synchronized hash
- **THEN** the system SHALL stop before writing that synchronization set
- **AND** it SHALL preserve both database and vault versions for reconciliation

#### Scenario: [OS-13] User adopts the vault edit

- **WHEN** the user selects the vault version during `retro sync reconcile`
- **THEN** the system SHALL import it as an edited candidate with provenance
- **AND** it SHALL require normal review before it becomes active knowledge

#### Scenario: [OS-14] User keeps the database version

- **WHEN** the user selects the database version during reconciliation
- **THEN** the system SHALL display the replacement diff and require confirmation before updating the managed vault content

### Requirement: Deep merge requires a current confirmed plan

The system SHALL keep deep organization of user-authored notes separate from automatic synchronization and SHALL write outside managed boundaries only through an explicitly applied merge plan.

#### Scenario: [OS-15] Generate a merge plan

- **WHEN** the user requests semantic organization for a project
- **THEN** the system SHALL generate a plan containing target files, complete diffs, input hashes, conflicts, and any delete, rename, or move operations
- **AND** it SHALL NOT modify the vault

#### Scenario: [OS-16] Apply a current safe merge plan

- **WHEN** the user explicitly applies a plan whose target hashes still match and which has no unconfirmed delete, rename, move, or conflict
- **THEN** the system SHALL execute it through the journaled backup and readback protocol

#### Scenario: [OS-17] Merge plan is stale

- **WHEN** any target hash differs from the hash recorded in the merge plan
- **THEN** the system SHALL refuse the apply
- **AND** it SHALL require a new plan

#### Scenario: [OS-18] Merge plan contains destructive changes

- **WHEN** a plan contains a delete, rename, move, or unresolved conflict
- **THEN** the system SHALL require explicit confirmation for those exact operations
- **AND** it SHALL NOT treat general merge confirmation as authorization

### Requirement: Synchronization backups are retained by default

The system SHALL retain ordinary synchronization and merge backups until the user explicitly requests cleanup. A fully confirmed sensitive purge SHALL remove affected backups listed in its current impact plan.

#### Scenario: [OS-19] Synchronization completes

- **WHEN** a synchronization or merge run succeeds
- **THEN** its pre-write backup SHALL remain available for inspection and recovery
- **AND** no automatic backup cleanup SHALL run in the MVP

#### Scenario: [OS-20] Sensitive purge includes an affected backup

- **WHEN** a current sensitive-purge plan identifies content inside a retained synchronization or merge backup
- **THEN** that backup location SHALL receive an exact purge operation ID
- **AND** ordinary retention SHALL NOT prevent the confirmed purge from cleaning and verifying that copy

### Requirement: Projection-changing commits trigger one same-command synchronization

The system SHALL create one deterministic project projection event after a committed automatic acceptance, manual acceptance or edit, reviewed vault adoption, conflict resolution, archive, or completed purge, and SHALL synchronously attempt the affected project projection before the initiating command returns.

#### Scenario: [OS-21] Accepted knowledge triggers projection

- **WHEN** a command commits a projection-changing knowledge transition and synchronization preflight is healthy
- **THEN** the same command SHALL apply one batched projection for the affected project
- **AND** it SHALL report both committed SQLite state and verified vault state

#### Scenario: [OS-22] Projection preflight or apply fails

- **WHEN** mapping, containment, markers, hashes, vault availability, rollback state, write, or readback prevents projection
- **THEN** committed SQLite knowledge SHALL remain authoritative
- **AND** the system SHALL record `sync_pending` with a stable reason and retry action
- **AND** it SHALL NOT report the vault as current

#### Scenario: [OS-23] Retry an unchanged projection event

- **WHEN** the same projection event is retried after the blocking condition is resolved
- **THEN** the system SHALL render identical target bytes
- **AND** it SHALL create no duplicate managed item or append-only log entry

#### Scenario: [OS-24] Automatic projection reaches only managed boundaries

- **WHEN** same-command synchronization runs after a projection-changing transition
- **THEN** it SHALL modify only aggregate files and valid managed summary, index, or log locations
- **AND** it SHALL NOT authorize or apply a deep merge into user-authored prose
