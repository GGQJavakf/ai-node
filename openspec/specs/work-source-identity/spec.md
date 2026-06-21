# work-source-identity Specification

## Purpose
TBD - created by archiving change merge-duplicate-work-sources. Update Purpose after archive.
## Requirements
### Requirement: WorkItem source observations have stable identities

The assistant SHALL derive stable canonical identities from explicit source references and supported identifiers found in Codex titles, Codex source refs, and next actions.

#### Scenario: Redmine id appears in multiple Codex fields

- **WHEN** a Codex report entry has the same Redmine id in its `title`, `source_ref`, or `next_action`
- **THEN** the assistant SHALL derive the same canonical identity `redmine:<id>` for each occurrence
- **AND** it SHALL treat that identity as referring to the same local WorkItem as an explicit Redmine import for that issue id.

#### Scenario: OpenSpec change is observed

- **WHEN** an incoming source mentions an OpenSpec change id using a valid OpenSpec identifier
- **THEN** the assistant SHALL derive canonical identity `openspec:<change_id>`
- **AND** it SHALL use that identity consistently across Codex, project sync, and manual work-source observations.

#### Scenario: GitLab MR id is observed

- **WHEN** an incoming source contains a GitLab MR URL or `MR !<id>` style reference
- **THEN** the assistant SHALL derive a canonical MR identity that includes the MR id and the best available project scope
- **AND** if the project scope is unavailable or conflicts with an existing candidate, it SHALL mark the match ambiguous instead of automatically merging cross-project work.

#### Scenario: Codex thread id is observed

- **WHEN** a Codex report entry includes a `thread_id`
- **THEN** the assistant SHALL derive canonical identity `codex-thread:<thread_id>`
- **AND** repeated imports of the same thread SHALL update the same WorkItem.

### Requirement: Exact identity matches merge into one WorkItem

The assistant SHALL merge incoming source observations into an existing active WorkItem when they share at least one exact canonical identity within the applicable project scope.

#### Scenario: Codex and Redmine describe the same issue

- **WHEN** a Redmine import creates or updates `redmine:<id>`
- **AND** a Codex report entry contains the same `redmine:<id>` identity in its title, source ref, or next action
- **THEN** the assistant SHALL update one WorkItem instead of creating a duplicate
- **AND** `/list` SHALL show only one active row for that real work item.

#### Scenario: OpenSpec change and Codex thread are associated

- **WHEN** a WorkItem already has `openspec:<change_id>`
- **AND** a Codex thread observation adds a `codex-thread:<thread_id>` identity for the same work item
- **THEN** the assistant SHALL associate both identities with the same WorkItem
- **AND** future imports by either identity SHALL update the same WorkItem.

#### Scenario: No stable identity exists

- **WHEN** an incoming source observation does not contain a stable identity
- **THEN** the assistant SHALL create or update only by the existing exact `(source, source_ref)` behavior
- **AND** it SHALL NOT automatically merge based only on similar wording.

### Requirement: Merged WorkItems preserve source refs and evidence

The assistant SHALL retain all contributing source refs, source identities, and evidence when merging duplicate WorkItems.

#### Scenario: Multiple source refs merge

- **WHEN** two WorkItems are merged because they share a canonical identity
- **THEN** the surviving WorkItem SHALL retain every source ref from both WorkItems
- **AND** it SHALL retain every canonical identity from both WorkItems
- **AND** it SHALL append merge evidence that identifies the source identity and previous WorkItem id.

#### Scenario: Evidence exists on absorbed item

- **WHEN** the absorbed WorkItem has evidence entries
- **THEN** the assistant SHALL keep those evidence entries accessible from the surviving WorkItem
- **AND** it SHALL NOT drop command, test, note, review, link, or snapshot evidence.

#### Scenario: Conflicting source facts are observed

- **WHEN** merged sources disagree on status, project path, title, or next action
- **THEN** the assistant SHALL apply the documented merge priority
- **AND** it SHALL preserve the conflicting source fact as evidence or conflict metadata instead of silently discarding it.

### Requirement: Ambiguous matches require manual confirmation

The assistant SHALL skip automatic merging when identity evidence is weak, conflicting, or maps to multiple candidate WorkItems.

#### Scenario: Only title similarity matches

- **WHEN** two WorkItems have similar titles but no shared canonical identity
- **THEN** the assistant SHALL NOT merge them automatically
- **AND** it SHALL report the candidate as skipped or requiring manual confirmation.

#### Scenario: Multiple candidates share one identity

- **WHEN** an incoming observation resolves to an identity already present on multiple active WorkItems
- **THEN** the assistant SHALL NOT choose a survivor automatically
- **AND** it SHALL report the conflict for manual resolution.

#### Scenario: Project-scoped MR match is ambiguous

- **WHEN** an MR id matches by number but project scope differs or is unknown
- **THEN** the assistant SHALL skip automatic merging
- **AND** it SHALL preserve the observation for later manual association.

### Requirement: Mistaken merges are reversible locally

The assistant SHALL record merge audit data that allows a mistaken merge to be rolled back or manually split without external writes.

#### Scenario: Automatic merge occurs

- **WHEN** the assistant automatically merges two WorkItems
- **THEN** it SHALL record the absorbed WorkItem snapshot, moved identities, moved source refs, affected evidence ids, timestamp, and merge reason.

#### Scenario: User requests split or rollback

- **WHEN** the user requests rollback or manual split of a merged WorkItem
- **THEN** the assistant SHALL restore or recreate the separated WorkItem from merge audit data when available
- **AND** it SHALL leave an evidence entry describing the split action.

#### Scenario: Full rollback data is unavailable

- **WHEN** a legacy merge lacks enough audit data for automatic restoration
- **THEN** the assistant SHALL expose the preserved source refs and evidence needed for manual split
- **AND** it SHALL NOT claim the merge is fully reversible.

### Requirement: Sync and list report de-duplication outcomes

The assistant SHALL make duplicate handling observable in `/sync`, `/codex tasks`, `/work status`, and `/list`.

#### Scenario: Sync imports duplicate sources

- **WHEN** `/sync` imports or refreshes Codex and project source observations
- **THEN** the output SHALL include a summary with `merged`, `created`, `updated`, and `skipped` counts
- **AND** skipped ambiguous candidates SHALL be counted separately from created or merged items.

#### Scenario: List active work

- **WHEN** the user runs `/list`
- **THEN** the assistant SHALL show at most one active WorkItem per exact canonical identity group
- **AND** the displayed row SHALL indicate the primary source while keeping other source refs available through status or evidence commands.

#### Scenario: Work status includes source identity context

- **WHEN** the user runs `/work status`
- **THEN** the assistant SHALL summarize associated source identities or source refs for each WorkItem
- **AND** it SHALL surface any merge conflicts or manual confirmation needs.

#### Scenario: User lists unresolved source conflicts

- **GIVEN** one or more WorkItems contain merge conflict metadata
- **WHEN** the user runs `/work conflicts`
- **THEN** the assistant SHALL list only WorkItems that need manual source resolution
- **AND** it SHALL include the conflict details and a next command hint such as `/work show` or `/work split`.

