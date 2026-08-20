## Context

AgentRetro currently has strong safety and regression coverage, but its common loop still requires users to know an internal project ID, capture one session at a time, inspect a verbose candidate list, and infer why a brief contains no knowledge. The change crosses CLI parsing, Codex session discovery, project mapping, capture orchestration, review summaries, briefing, and repository queries. It must preserve explicit capture, no raw transcript copies, fail-closed routing, conservative review, and read-only brief/inbox behavior.

This change starts from merged `main` commit `628f34baaba01c7066342b031f34f9234382a664`. Its delta specs layer on the completed but not yet archived `add-agentretro-mvp` and `harden-recent-session-capture` changes. Their archive order is part of closeout, not an implicit change to implementation scope.

## Goals / Non-Goals

**Goals:**

- Make mapped repository paths, workspace paths, worktree remotes, remote identities, and canonical project IDs behave consistently at read boundaries.
- Explain an empty brief using safe aggregate facts and exact recovery commands.
- Allow preview and explicit capture of a small recent batch with identity-bound confirmation.
- Turn pending review and awaiting-routing work into a concise, bounded inbox.
- Report expired task state consistently without adding writes to brief or inbox.

**Non-Goals:**

- No hook, watcher, scheduled task, automatic capture, or implicit post-session write.
- No automatic or bulk acceptance and no relaxation of review thresholds.
- No full transcript storage or unredacted candidate/evidence output.
- No database schema migration, external dependency, or new external-system write.
- No automatic Obsidian reconciliation.

## Decisions

### Resolve project references through one read-only resolver

Add a project-reference resolver beside the existing capture routing resolver. Exact canonical IDs resolve directly after confirming at least one active mapping. Existing paths are normalized and evaluated against active workspace mappings by unique longest containing root. For a Git worktree, the resolver discovers the worktree root and credential-free normalized remote, so a worktree whose root differs from the stored Git root can still match the existing Git mapping.

Path, workspace, and remote evidence are combined rather than silently prioritized. If their surviving candidates name different canonical projects, resolution fails with `ambiguous_project_reference` and reason `mapping_identity_conflict`. Diagnostics contain only safe mapping IDs and project IDs. The resolver is used before `BriefService` and project-filtered inbox queries, leaving deterministic application services on canonical IDs.

### Bind recent capture confirmation to source, mapping, and reuse identity

The source adapter returns a bounded newest-first list of completed sessions. A pure planner canonicalizes a versioned JSON structure containing `requested_count`, the effective `recent_capture_max`, and ordered entries with `session_id`, `source_hash`, `resolution_status`, `canonical_project_id`, `mapping_id`, and `reuse_status`; its SHA-256 is the plan ID. Empty project/mapping identifiers are permitted only for unresolved entries.

Apply repeats discovery, parsing, project resolution, and reuse lookup, then compares the complete hash before any write. A mapping activation/deactivation, worktree identity change, target-project change, source change, count/max change, or reuse-state change invalidates the plan. This prevents preview under one routing identity and apply under another.

Resolved entries use the existing per-session idempotent transaction. Unresolved entries are skipped without writes. On the first per-session failure, apply stops: the attempted item is failed, remaining unattempted entries are skipped as `batch_stopped`, and earlier commits remain. The recovery command always requests a new preview because a partial success changes reuse state and therefore invalidates the old plan. This behavior is deliberately not cross-session atomic.

### Keep brief and inbox diagnostics aggregate-only

Add application result models for brief health and review inbox summaries. Repository queries project only IDs, status, timestamps, and counts needed by those models; presentation never receives candidate text, evidence excerpts, source paths, remotes, or model errors for these commands.

An empty brief reports captured-session, eligible-knowledge, expired-task-state, and pending-review counts. Eligibility is measured after project/global scope, lifecycle, conflict, archive, and effective-expiry filters but before lesson relevance and token budget. Recovery uses a count of `min(5, recent_capture_max)` so the emitted command is always valid. A non-empty brief retains existing output order and budget semantics.

### Define one bounded review-inbox contract

Cross-project inbox rows are sorted by canonical ID. Project candidate IDs and awaiting session IDs use oldest-first timestamp plus ID tie-break, default to 20, and accept only limits from 1 through 50. Every bounded response includes total, returned, and truncated fields. Ages are floor elapsed seconds from the injected clock and clamp at zero.

Retryable means a `pending_review` candidate with no saved review result and either no attempt or a latest failed attempt; running and completed attempts are excluded. Awaiting captured sessions are reported separately because no candidate is extracted until project routing succeeds. The awaiting view returns safe session IDs and static project-list/reclassify command templates only.

### Treat expiry as an effective read status

Brief and inbox compute expired when an active `TASK_STATE.valid_until` is at or before the injected clock. They do not update SQLite. Existing write-side lifecycle operations may persist stale state later, but read-only commands never gain a hidden write side effect.

## Risks / Trade-offs

- [Recent discovery parses more than one source] -> Enforce `recent_capture_max`, existing file-count/deadline/size limits, newest-first discovery, and stable timeout/unsupported diagnostics.
- [Source or mapping changes between preview and apply] -> Recompute and compare the complete versioned identity plan before the first write.
- [A batch fails after earlier commits] -> Stop on first failure, report four disjoint result lists, require a new preview, and rely on per-session idempotency.
- [Path and remote evidence disagree] -> Fail closed with safe mapping IDs; never guess by precedence.
- [Aggregate output leaks sensitive content] -> Use count/ID-only repository projections and subprocess tests with credential-bearing fixtures.
- [Inbox queries grow] -> Fixed/default bounds, indexed current tables, and count queries avoid unbounded output; no schema change is expected.
- [New convenience becomes implicit automation] -> Require dry-run or exact plan apply and retain no-hook/no-watcher tests.

## Compatibility, Migration, and Rollback

- Data migration: N/A; no table or stored-record format changes.
- API compatibility: existing single-session capture, review list/show/lifecycle, and canonical-ID brief behavior remain supported; new JSON fields/commands are additive.
- Windows compatibility: commands must pass UTF-8 and GBK subprocess smoke without ANSI or secret leakage.
- Rollback: revert the implementation commit(s). Existing per-session records created by an explicitly applied batch remain valid and idempotent; rollback does not delete user data.
- Closeout order: after implementation and verification, archive `add-agentretro-mvp`, validate all; archive `harden-recent-session-capture`, validate all; then sync/validate this delta and archive `improve-agentretro-value-loop`. Stop on any archive conflict.

## Verification Strategy

Each scenario maps to a focused unit, repository, CLI, or subprocess test named in `tasks.md`. In addition to strict OpenSpec validation, run full pytest, Ruff, mypy on touched production files, compileall, branch coverage, Windows UTF-8/GBK smoke, and OCR independent review before any PR is marked ready.

## Open Questions

None. Bounds, ordering, retryability, routing conflicts, partial-failure behavior, recovery counts, compatibility, and archive order are fixed by this design.
