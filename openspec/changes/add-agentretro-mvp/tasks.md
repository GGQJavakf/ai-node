## 1. Independent Product Foundation

- [x] 1.1 Add failing tests and then the minimal `agent_retro` package plus `retro` console entry point, proving `ai-todo` remains independently importable and runnable.
- [x] 1.2 Define AgentRetro configuration loading under `<user-home>/.agentretro/` with path containment, defaults, environment overrides, and isolated test directories.
- [x] 1.3 Implement the SQLite schema, repositories, versioned migrations, pre-migration backup, migration rollback, and lifecycle audit records with migration failure tests.
- [x] 1.4 Implement the read-only legacy model configuration adapter and tests proving credentials are never serialized, logged, or persisted.
- [x] 1.5 Add stable Chinese human output, stable English `--json` envelopes, and Unicode-safe Windows console rendering for AgentRetro commands.
- [x] 1.6 Implement validated, configurable safety limits with defaults for session discovery count and deadline, maximum session size, model-call deadline, local brief-render deadline, and brief budget.

## 2. Codex Session Capture and Evidence

- [x] 2.1 Add representative completed, active, malformed, changed-hash, and unknown-event Codex session fixtures without real credentials or user data.
- [x] 2.2 Implement effective Codex-home discovery and explicit `--last` / `--session` selection, including active-session and unavailable-source failures.
- [x] 2.3 Implement the versioned Codex session adapter and normalized session/event models with fail-closed required-field validation.
- [x] 2.4 Implement session, event, and content-hash idempotency plus source-integrity conflict detection, with duplicate-capture tests.
- [x] 2.5 Implement Git-root and normalized-remote project routing plus audited SQLite project mapping records, including unknown and ambiguous project states.
- [x] 2.6 Implement pre-model and pre-persistence redaction, minimal evidence excerpts, source locators, and tests proving captured instructions cannot trigger actions.
- [x] 2.7 Wire `retro capture` to one database transaction so parser or evidence failure creates no partial session, candidate, or knowledge state.
- [x] 2.8 Implement `retro project map/list/remove/reclassify` with containment checks, collision rejection, actor/time audit records, and reclassification of awaiting sessions without reparsing source events.
- [x] 2.9 Bound newest-first session discovery by configured candidate count and deadline, stream parsing, reject oversized files before model work, and preserve an explicit diagnostic for every skipped or timed-out source.
- [ ] 2.10 Add tests whose names or metadata reference every Codex retrospective scenario `CR-01` through `CR-22`, and record the scenario-to-test mapping in verification evidence.

## 3. Knowledge Extraction, Review, and Lifecycle

- [x] 3.1 Define `RULE`, `LESSON`, and `TASK_STATE` models, type-specific evidence validators, project/global scope, versioning, status transitions, and 14-day task-state expiry.
- [x] 3.2 Implement a strict structured extraction request and response parser that produces evidence-bound candidates without accepting them.
- [x] 3.3 Implement the separate structured review request and response parser for verdict, confidence, reason, normalized text, duplicate assessment, and conflict assessment.
- [x] 3.4 Implement type thresholds and deterministic hard gates for secrets, evidence, project identity, duplicates, conflicts, speculation, rule authority, and lesson verification.
- [x] 3.5 Implement automatic acceptance with complete gate and actor audit records, and keep below-threshold or unavailable-model candidates pending.
- [x] 3.6 Implement `retro review` list/show/accept/edit/reject commands with evidence display, before/after hashes, and stable JSON output.
- [x] 3.7 Implement conflict detection, old-item-active behavior, merge suggestions, explicit merge resolution, and superseded-version history.
- [x] 3.8 Implement project-to-global promotion, stale task-state handling, and ordinary archive without physical deletion.
- [x] 3.9 Implement `retro review retry --candidate/--session` with immutable attempt records, fresh model review, idempotent lifecycle transitions, and no duplicate accepted knowledge.
- [ ] 3.10 Implement `retro kb purge plan/apply` so an immutable plan enumerates every AgentRetro-owned SQLite, vault, backup, log, and index copy; require plan ID plus exact operation confirmation; create only a content-free tombstone; and leave `purge_incomplete` with residual locations if any cleanup fails.
- [ ] 3.11 Add tests whose names or metadata reference every knowledge-review scenario `KR-01` through `KR-24`, and record the scenario-to-test mapping in verification evidence.

## 4. Obsidian Projection and Recovery

- [x] 4.1 Implement deterministic rendering and parsing for `规则.md`, `经验.md`, and `任务状态.md`, including stable item IDs and archived sections.
- [x] 4.2 Implement managed project-summary and index-link markers plus append-only log records, proving automatic sync preserves bytes outside managed regions.
- [x] 4.3 Implement vault-root containment, unexpected symlink rejection, marker validation, and mapped-project preflight checks.
- [x] 4.4 Implement sync planning, pre-write hashes, all-target backups, SQLite journals, same-directory temporary files, replacement, and post-write readback.
- [x] 4.5 Add multi-file failure-injection tests that prove all targets restore to exact pre-write hashes and restoration failure blocks future sync with `rollback_required`.
- [x] 4.6 Trigger one preflighted, idempotent same-command projection after every committed projection-changing SQLite transaction; on any preflight or write failure preserve SQLite as authoritative and mark affected knowledge `sync_pending` with a recovery diagnostic.
- [x] 4.7 Implement external managed-content hash detection and `retro sync reconcile` choices without silent bidirectional overwrite.
- [x] 4.8 Implement preview-only semantic merge planning with target hashes, complete diffs, conflicts, and destructive-operation disclosure.
- [x] 4.9 Implement explicit merge apply through the journaled write protocol, rejecting stale plans and requiring exact confirmation for delete, rename, move, or unresolved conflict.
- [ ] 4.10 Integrate sensitive purge with journaled vault and backup cleanup so retention never recreates sensitive content, and verify a residual scan before marking the purge complete.
- [ ] 4.11 Add tests whose names or metadata reference every Obsidian synchronization scenario `OS-01` through `OS-24`, and record the scenario-to-test mapping in verification evidence.

## 5. Briefing, Diagnostics, and Codex Integration

- [x] 5.1 Implement deterministic local `retro brief` selection in fixed category order using NFKC/case-folded CJK and Latin tokens, configured keyword/recency/evidence weights, and stable knowledge-ID tie-breaking, without a model call or vector database.
- [x] 5.2 Implement the configurable 6000-token default budget using the conservative UTF-8 byte estimate, atomic item inclusion, reproducible omission notice, mandatory-rule overflow failure, evidence references, sync warnings, and terminal/Markdown/JSON formats.
- [x] 5.3 Implement `retro doctor` checks for source access and safety limits, database/migrations, redacted model readiness, audited project mappings, vault safety, backups, sync and purge recovery, canonical Codex integration and override conflicts, and console encoding.
- [x] 5.4 Implement preview-only `retro integrate codex` targeting exactly `<effective-codex-home>/AGENTS.md`, with canonical containment and symlink checks, one managed block, target hash, complete diff, backup location, and explicit missing-file creation preview.
- [x] 5.5 Implement explicit Codex integration apply and remove with readback, encoding/newline/byte preservation outside the block, manual-edit detection, refusal when `AGENTS.override.md` exists, no native-memory modification, and a non-writing discoverability smoke check.
- [x] 5.6 Verify the managed guidance triggers task-scoped `retro brief` only for work that depends on retained context and never requires an unconditional vault scan.
- [x] 5.7 Enforce the configurable local brief-render deadline and return a diagnostic instead of a successful partial brief.
- [ ] 5.8 Add tests whose names or metadata reference every briefing and integration scenario `BR-01` through `BR-28`, and record the scenario-to-test mapping in verification evidence.

## 6. End-to-End and Regression Verification

- [x] 6.1 Add a temporary Codex-home and temporary Obsidian-vault integration test covering capture, extraction, review, acceptance, synchronization, and briefing.
- [x] 6.2 Add security fixtures and repository-wide output assertions proving test secrets never reach logs, SQLite, model traces, backups, or vault files.
- [x] 6.3 Add Windows GBK and UTF-8 subprocess smoke tests for `retro --help`, capture, review, and brief, and isolate any legacy output compatibility patch from business behavior.
- [x] 6.4 Run the complete existing `ai-todo` suite and verify AgentRetro tests do not modify the existing Todo database or configuration behavior.
- [ ] 6.5 Verify that every `CR-01..CR-22`, `KR-01..KR-24`, `OS-01..OS-24`, and `BR-01..BR-28` ID has at least one passing automated test or an explicitly justified manual check, with no orphan scenario or test reference.
- [ ] 6.6 Run `openspec validate add-agentretro-mvp --strict`, full tests, CLI smoke checks, and a final scope/security self-review before declaring implementation complete.
