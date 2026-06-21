## 1. Regression Tests First

- [x] 1.1 Add workflow service tests for Redmine identity extraction from Codex `title`, `source_ref`, and `next_action`.
- [x] 1.2 Add workflow service tests for OpenSpec change, GitLab MR, and Codex thread canonical identities.
- [x] 1.3 Add tests proving exact identity matches merge or associate into one WorkItem while preserving source refs and evidence.
- [x] 1.4 Add tests proving ambiguous title-only, cross-project MR, and multi-candidate matches are skipped for manual confirmation.
- [x] 1.5 Add tests proving merge audit data can restore or manually split a mistaken merge.
- [x] 1.6 Add CLI tests proving `/list` does not duplicate the same real work item and `/sync` reports `merged`, `created`, `updated`, and `skipped`.

## 2. Domain and Persistence

- [x] 2.1 Add compatible WorkItem metadata for canonical source identities, observed source refs, merge audit entries, and conflict flags.
- [x] 2.2 Update JSON workflow persistence to read old records with empty metadata and write the new metadata.
- [x] 2.3 Update SQLite workflow persistence and migration logic without breaking existing `work_items` rows.
- [x] 2.4 Add repository helpers for finding WorkItems by canonical identity and moving or preserving evidence during merges.

## 3. Identity Extraction and Merge Policy

- [x] 3.1 Implement canonical identity extraction for Redmine ids, OpenSpec changes, GitLab MR ids, and Codex thread ids.
- [x] 3.2 Implement project scoping for identities where ids are not globally unique.
- [x] 3.3 Implement deterministic field merge priority for status, priority, title, next action, project path, and sync summary.
- [x] 3.4 Implement ambiguity detection and skipped-candidate reporting for weak or conflicting matches.

## 4. Workflow Service Integration

- [x] 4.1 Update Codex report import to attach extracted identities before matching and saving.
- [x] 4.2 Update Redmine import to merge with existing Codex or manual WorkItems carrying the same `redmine:<id>` identity.
- [x] 4.3 Update project sync/OpenSpec handling to associate OpenSpec identities with the relevant WorkItem instead of creating display duplicates.
- [x] 4.4 Preserve and append evidence for every contributing source observation.
- [x] 4.5 Implement merge audit recording and service-level rollback or manual split support.

## 5. CLI and Output

- [x] 5.1 Update `/sync` output to report `merged`, `created`, `updated`, and `skipped` counts.
- [x] 5.2 Update `/list` and `/work status` display to show one row per merged identity group and surface associated source refs.
- [x] 5.3 Add user-facing output for ambiguous candidates that require manual confirmation.
- [x] 5.4 Document the rollback or manual split command/path in CLI help or README.
- [x] 5.5 Add `/work conflicts` to list unresolved merge conflicts with show/split hints.

## 6. Verification

- [x] 6.1 Run focused workflow sync tests.
- [x] 6.2 Run focused CLI workflow tests.
- [x] 6.3 Run full unittest suite.
- [x] 6.4 Run `openspec validate merge-duplicate-work-sources --strict`.
- [x] 6.5 Self-review the diff for accidental external writes and compatibility gaps.
