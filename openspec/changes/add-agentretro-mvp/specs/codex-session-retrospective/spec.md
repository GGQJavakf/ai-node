## ADDED Requirements

### Requirement: Capture is explicit and limited to one completed Codex session

The system SHALL capture local Codex session data only when the user invokes `retro capture --last` or `retro capture --session <session-id>`, and it SHALL NOT install a hook, watcher, or background capture process.

#### Scenario: [CR-01] Capture the last completed session

- **WHEN** the user runs `retro capture --last` and at least one completed Codex session is discoverable
- **THEN** the system SHALL select the newest completed session
- **AND** it SHALL create a capture result for only that session

#### Scenario: [CR-02] Capture a named session

- **WHEN** the user runs `retro capture --session <session-id>` for a completed discoverable session
- **THEN** the system SHALL capture only the named session

#### Scenario: [CR-03] Active session is not captured

- **WHEN** the requested session is still active or lacks a completed-session marker
- **THEN** the system SHALL refuse to extract knowledge from it
- **AND** it SHALL report that the session is incomplete

#### Scenario: [CR-04] Capture does not enable automation

- **WHEN** AgentRetro is installed or a capture completes
- **THEN** the system SHALL NOT add hooks, scheduled tasks, watchers, or background services

### Requirement: Session discovery uses the actual local Codex source

The system SHALL discover sessions from the effective local Codex home and SHALL keep that source separate from any isolated Codex runtime directory used by `ai-todo`.

#### Scenario: [CR-05] Effective Codex home is available

- **WHEN** an effective local Codex home contains completed sessions
- **THEN** the system SHALL use that location as the session source
- **AND** it SHALL NOT substitute the existing product's isolated runtime directory

#### Scenario: [CR-06] Codex source is unavailable

- **WHEN** the effective Codex home cannot be found or read
- **THEN** the system SHALL fail the capture with a diagnostic that identifies the unavailable source
- **AND** it SHALL NOT create partial session, evidence, candidate, or knowledge records

### Requirement: Capture is idempotent

The system SHALL identify source data by session ID, event locator, and content hash so repeated capture does not duplicate persisted data.

#### Scenario: [CR-07] Re-capture an unchanged session

- **WHEN** the user captures a completed session that was already captured with the same content hash
- **THEN** the system SHALL reuse the existing session result
- **AND** it SHALL create no duplicate evidence, candidate, or knowledge record

#### Scenario: [CR-08] Session identity collides with changed content

- **WHEN** a known session ID is observed with a different content hash
- **THEN** the system SHALL stop automatic processing
- **AND** it SHALL report a source-integrity conflict for manual investigation

### Requirement: Captured events are normalized without inventing facts

The system SHALL normalize supported Codex events into stable session, turn, message, tool-result, file-reference, and completion records, and it SHALL fail closed when required identity fields are missing.

#### Scenario: [CR-09] Unknown optional event type

- **WHEN** a completed session contains an unknown optional event type
- **THEN** the system SHALL skip that event and record a parser warning
- **AND** it SHALL continue only if required session identity and completion facts remain available

#### Scenario: [CR-10] Required identity field is missing

- **WHEN** the parser cannot establish session identity, source locator, or completion state
- **THEN** the system SHALL mark the source unsupported
- **AND** it SHALL NOT infer or fabricate the missing value

### Requirement: Project routing is evidence based

The system SHALL route captured knowledge by Git root, normalized remote identity, and explicit local project mappings.

#### Scenario: [CR-11] Project mapping is unambiguous

- **WHEN** the captured session working directory resolves to exactly one configured project mapping
- **THEN** the system SHALL assign that project scope to the session and its candidates

#### Scenario: [CR-12] Project mapping is unknown or ambiguous

- **WHEN** no mapping or more than one mapping matches the captured session
- **THEN** the system SHALL mark the session as awaiting project classification
- **AND** it SHALL block automatic acceptance and Obsidian synchronization

### Requirement: Evidence is minimal, traceable, and redacted

The system SHALL store only a source reference, content hash, evidence kind, and minimal redacted excerpt needed to support a candidate, and it SHALL NOT copy the complete raw session.

#### Scenario: [CR-13] Evidence supports a candidate

- **WHEN** a candidate is extracted from a supported session event
- **THEN** the system SHALL attach at least one evidence record with a resolvable source locator and content hash

#### Scenario: [CR-14] Sensitive data appears in source content

- **WHEN** source content contains a credential, token, cookie, authorization header, password, private key, or recognized connection secret
- **THEN** the system SHALL redact the sensitive value before model input and persistence
- **AND** the unredacted value SHALL NOT appear in AgentRetro logs, SQLite, or Obsidian output

#### Scenario: [CR-15] Captured text contains instructions

- **WHEN** captured content includes a command or instruction directed at an agent
- **THEN** the system SHALL treat it only as untrusted evidence data
- **AND** it SHALL NOT execute the command or authorize a file or tool action

### Requirement: Project mappings have an audited recovery lifecycle

The system SHALL provide CLI actions to create, list, remove, and use project mappings to reclassify awaiting sessions, and SHALL persist mapping changes with audit records.

#### Scenario: [CR-16] Create a project mapping

- **WHEN** the user maps a resolved Git root to an Obsidian project
- **THEN** the system SHALL normalize the Git remote, validate the vault target and containment, and persist one mapping
- **AND** it SHALL return the mapping ID without exposing remote credentials

#### Scenario: [CR-17] Reject an unsafe or conflicting mapping

- **WHEN** the proposed mapping escapes the configured vault, traverses a symlink, or conflicts with an incompatible root, remote, or vault target
- **THEN** the system SHALL refuse the mapping and persist no partial change

#### Scenario: [CR-18] List and remove a mapping

- **WHEN** the user lists mappings or removes one mapping ID
- **THEN** listing SHALL return resolved root, normalized remote, and vault project
- **AND** removal SHALL stop future routing and projection without deleting captured sessions, knowledge, or vault files

#### Scenario: [CR-19] Reclassify an awaiting session

- **WHEN** the user assigns an existing mapping to a session awaiting project classification
- **THEN** the system SHALL update project routing and resume review from stored evidence
- **AND** it SHALL NOT recapture the source or duplicate evidence

### Requirement: Session discovery and parsing are bounded

The system SHALL stream JSONL and enforce configurable discovery-count, discovery-deadline, and source-size limits. Defaults SHALL inspect at most the newest 1000 candidate session files within 10 seconds and SHALL reject a source session larger than 128 MiB.

#### Scenario: [CR-20] Discover within configured bounds

- **WHEN** the user captures the last session and discovery remains within configured count and time limits
- **THEN** the system SHALL inspect candidates newest first and parse the selected JSONL as a stream

#### Scenario: [CR-21] Source session exceeds the size limit

- **WHEN** the selected session source exceeds the configured maximum size
- **THEN** the system SHALL fail with a stable size-limit diagnostic and recovery hint
- **AND** it SHALL create no partial session, evidence, candidate, or knowledge state

#### Scenario: [CR-22] Discovery reaches its deadline

- **WHEN** last-session discovery reaches its configured deadline before finding a supported completed session
- **THEN** the system SHALL stop with a stable timeout diagnostic and suggest explicit `--session` selection or a configured limit change
- **AND** it SHALL create no partial state
