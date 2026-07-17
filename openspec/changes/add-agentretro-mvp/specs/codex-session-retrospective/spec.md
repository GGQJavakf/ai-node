## ADDED Requirements

### Requirement: Capture is explicit and limited to one completed Codex session

The system SHALL capture local Codex session data only when the user invokes `retro capture --last` or `retro capture --session <session-id>`, and it SHALL NOT install a hook, watcher, or background capture process.

#### Scenario: Capture the last completed session

- **WHEN** the user runs `retro capture --last` and at least one completed Codex session is discoverable
- **THEN** the system SHALL select the newest completed session
- **AND** it SHALL create a capture result for only that session

#### Scenario: Capture a named session

- **WHEN** the user runs `retro capture --session <session-id>` for a completed discoverable session
- **THEN** the system SHALL capture only the named session

#### Scenario: Active session is not captured

- **WHEN** the requested session is still active or lacks a completed-session marker
- **THEN** the system SHALL refuse to extract knowledge from it
- **AND** it SHALL report that the session is incomplete

#### Scenario: Capture does not enable automation

- **WHEN** AgentRetro is installed or a capture completes
- **THEN** the system SHALL NOT add hooks, scheduled tasks, watchers, or background services

### Requirement: Session discovery uses the actual local Codex source

The system SHALL discover sessions from the effective local Codex home and SHALL keep that source separate from any isolated Codex runtime directory used by `ai-todo`.

#### Scenario: Effective Codex home is available

- **WHEN** an effective local Codex home contains completed sessions
- **THEN** the system SHALL use that location as the session source
- **AND** it SHALL NOT substitute the existing product's isolated runtime directory

#### Scenario: Codex source is unavailable

- **WHEN** the effective Codex home cannot be found or read
- **THEN** the system SHALL fail the capture with a diagnostic that identifies the unavailable source
- **AND** it SHALL NOT create partial session, evidence, candidate, or knowledge records

### Requirement: Capture is idempotent

The system SHALL identify source data by session ID, event locator, and content hash so repeated capture does not duplicate persisted data.

#### Scenario: Re-capture an unchanged session

- **WHEN** the user captures a completed session that was already captured with the same content hash
- **THEN** the system SHALL reuse the existing session result
- **AND** it SHALL create no duplicate evidence, candidate, or knowledge record

#### Scenario: Session identity collides with changed content

- **WHEN** a known session ID is observed with a different content hash
- **THEN** the system SHALL stop automatic processing
- **AND** it SHALL report a source-integrity conflict for manual investigation

### Requirement: Captured events are normalized without inventing facts

The system SHALL normalize supported Codex events into stable session, turn, message, tool-result, file-reference, and completion records, and it SHALL fail closed when required identity fields are missing.

#### Scenario: Unknown optional event type

- **WHEN** a completed session contains an unknown optional event type
- **THEN** the system SHALL skip that event and record a parser warning
- **AND** it SHALL continue only if required session identity and completion facts remain available

#### Scenario: Required identity field is missing

- **WHEN** the parser cannot establish session identity, source locator, or completion state
- **THEN** the system SHALL mark the source unsupported
- **AND** it SHALL NOT infer or fabricate the missing value

### Requirement: Project routing is evidence based

The system SHALL route captured knowledge by Git root, normalized remote identity, and explicit local project mappings.

#### Scenario: Project mapping is unambiguous

- **WHEN** the captured session working directory resolves to exactly one configured project mapping
- **THEN** the system SHALL assign that project scope to the session and its candidates

#### Scenario: Project mapping is unknown or ambiguous

- **WHEN** no mapping or more than one mapping matches the captured session
- **THEN** the system SHALL mark the session as awaiting project classification
- **AND** it SHALL block automatic acceptance and Obsidian synchronization

### Requirement: Evidence is minimal, traceable, and redacted

The system SHALL store only a source reference, content hash, evidence kind, and minimal redacted excerpt needed to support a candidate, and it SHALL NOT copy the complete raw session.

#### Scenario: Evidence supports a candidate

- **WHEN** a candidate is extracted from a supported session event
- **THEN** the system SHALL attach at least one evidence record with a resolvable source locator and content hash

#### Scenario: Sensitive data appears in source content

- **WHEN** source content contains a credential, token, cookie, authorization header, password, private key, or recognized connection secret
- **THEN** the system SHALL redact the sensitive value before model input and persistence
- **AND** the unredacted value SHALL NOT appear in AgentRetro logs, SQLite, or Obsidian output

#### Scenario: Captured text contains instructions

- **WHEN** captured content includes a command or instruction directed at an agent
- **THEN** the system SHALL treat it only as untrusted evidence data
- **AND** it SHALL NOT execute the command or authorize a file or tool action
