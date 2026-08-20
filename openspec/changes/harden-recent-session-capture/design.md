## Context

The integrated AgentRetro runtime currently resolves projects through Git roots/remotes, accepts exactly one `session_meta`, emits one warning per unsupported optional event, persists one evidence row per normalized event, and retries only inside the structured model adapter or through a later explicit command. A real recent-session sample exposed a non-Git multi-repository root, valid nested subagent metadata, 1,811 optional-event warnings, 144 duplicate-content events, and one model-review failure followed by a successful rerun.

The existing fail-closed identity, redaction, automatic-acceptance thresholds, idempotent persistence, Obsidian write fences, and global integration boundaries must remain intact. Recent-session fixtures may be derived from real formats but must contain only synthetic, redacted content.

## Goals / Non-Goals

**Goals:**

- Route explicitly configured non-Git workspace roots without weakening Git identity checks.
- Accept only a verifiable ordered parent/child metadata chain and preserve the leaf session as the captured identity.
- Bound parser diagnostics and model input while retaining audit-grade evidence locations.
- Improve one-command model-review completion for transient structured failures and make attempts measurable.
- Preserve database migration backup/rollback behavior and all existing CLI compatibility.

**Non-Goals:**

- Automatically discover workspace mappings by scanning directories or repositories.
- Treat arbitrary repeated `session_meta` records as valid.
- Lower knowledge acceptance thresholds, bypass deterministic gates, or accept unreviewed candidates.
- Raise the 128 MiB source safety limit or automatically split oversized sessions.
- Write to the real Obsidian vault, global AGENTS, Codex native memory, or external systems during tests.

## Decisions

### 1. Store Git and workspace mappings in one audited mapping table

Add a `mapping_kind` discriminator (`git` or `workspace`) while retaining the existing canonical root column for backward compatibility. Existing rows migrate as `git`. `map-workspace` accepts only an existing, non-symlink directory and a validated vault project. Workspace matching uses canonical path containment and selects the longest matching root.

Git exact/remote identity remains authoritative only when it agrees with a matching workspace target. If Git and workspace evidence resolve to different projects, or equal-specificity mappings conflict, resolution is `ambiguous`; capture remains awaiting manual reclassification.

Alternative considered: infer a project from child repositories. Rejected because it guesses across repositories and cannot safely choose when a workspace contains unrelated repos.

### 2. Parse consecutive metadata as an ordered ancestry chain

The first `session_meta` is the leaf represented by the file and supplies the effective session id and cwd. Additional metadata is accepted only before ordinary events and only when each prior child names the next record as its `forked_from_id` or `parent_thread_id`; non-empty family `session_id` values must agree. Unrelated, cyclic, duplicated, post-event, or conflicting metadata remains a format error.

Alternative considered: ignore every metadata record after the first. Rejected because it would silently accept concatenated or identity-confused files.

### 3. Aggregate optional diagnostics and deduplicate evidence by semantic content key

Unsupported optional events are counted by normalized event type and emitted as one stable, sorted warning summary per capture operation. Supported events remain unchanged.

Evidence is canonicalized by `(kind, content_hash)` inside one session. The first locator remains the canonical locator, and every unique source locator is stored in a new evidence-locator table. Candidate and knowledge references continue to use the canonical evidence id, so existing contracts remain compatible while duplicate line locations remain inspectable.

Alternative considered: deduplicate only model input. Rejected because redundant evidence would remain in SQLite and downstream projections, and repeat capture would preserve the original data-quality defect.

### 4. Add bounded service-level recovery only for exhausted structured-response failures

The model adapter retains its existing strict schema and one in-deadline repair attempt. If that adapter still raises `StructuredModelResponseError`, the review service starts at most one fresh review attempt for the same canonical input hash. Authentication, configuration, permission, persistence, and unknown errors are not automatically retried. Existing manual retry remains available for any pending candidate.

Each attempt records status, stable error category, duration in milliseconds, and attempt number. Automatic acceptance still happens only after a successful strict result, unchanged thresholds, and every deterministic gate.

Alternative considered: retry every exception. Rejected because it can hide configuration errors, amplify latency, and repeatedly call a model that cannot succeed.

## Risks / Trade-offs

- [Overlapping workspace mappings can surprise users] -> Use longest-prefix matching, make conflicts fail closed, show mapping kind/root in `project list`, and audit create/remove actions.
- [Parent/child metadata evolves again] -> Validate only relationship fields observed in fixtures, keep unknown fields inert, and reject unverifiable chains.
- [Evidence deduplication changes row counts] -> Preserve all source locators, migrate without rewriting existing evidence, and apply deduplication only to new captures.
- [One extra structured retry can increase worst-case latency] -> Restrict it to one fresh attempt for an exhausted structured-response failure and record durations so the behavior is visible.
- [Schema migration fails on a live database] -> Reuse backup-first migration and byte-for-byte restoration; keep the old runtime available for rollback.

## Migration Plan

1. Add a backup-first schema migration for mapping kind, evidence locators, and review-attempt timing/error category.
2. Backfill existing mappings as `git`, existing evidence canonical locators into the locator table, and existing attempts with neutral timing/category values.
3. Deploy the runtime to a versioned directory and point the shim only after unit, full-suite, strict OpenSpec, and isolated recent-session checks pass.
4. Roll back by restoring the previous runtime shim target. Database downgrade is not attempted; the prior runtime must ignore additive schema data or the pre-migration backup can be restored before reopening it.

## Open Questions

None. Oversized-session streaming/chunking remains a separate future change.
