## 1. Regression Fixtures and Contracts

- [x] 1.1 Add synthetic non-Git workspace, nested session-family, optional-event noise, duplicate-evidence, and flaky-review fixtures.
- [x] 1.2 Add failing unit tests for workspace mapping lifecycle, longest-prefix routing, and incompatible Git/workspace ambiguity.
- [x] 1.3 Add failing parser tests for valid ancestry chains and invalid repeated metadata variants.
- [x] 1.4 Add failing capture/persistence tests for aggregated warnings, canonical evidence, and complete source locators.
- [x] 1.5 Add failing review tests for one bounded structured retry, non-retryable failures, duration/category audit, and result reuse.

## 2. Persistence and Domain Migration

- [x] 2.1 Add backward-compatible domain fields for mapping kind, evidence locators, and review-attempt timing/category.
- [x] 2.2 Add a backup-first SQLite migration that backfills existing mappings, evidence locators, and review attempt defaults.
- [x] 2.3 Verify migration rollback, prior-row readability, unique locator persistence, and purge coverage for new fields.

## 3. Workspace Routing

- [x] 3.1 Implement safe workspace-root validation and audited `map-workspace` create/list/remove behavior.
- [x] 3.2 Implement canonical containment, longest-prefix selection, and Git/workspace disagreement handling.
- [x] 3.3 Expose mapping kind and root through stable JSON and text CLI output while preserving existing Git mapping commands.

## 4. Session Capture Quality

- [x] 4.1 Implement ordered parent/child metadata-chain validation while retaining the leaf identity and existing limits.
- [x] 4.2 Aggregate unsupported optional-event diagnostics into one stable bounded summary.
- [x] 4.3 Canonicalize evidence by kind/content hash and persist every unique source locator.
- [x] 4.4 Build deterministic extraction/review input from canonical unique evidence and preserve idempotent recapture.

## 5. Review Resilience

- [x] 5.1 Implement one fresh service-level retry only after exhausted structured-response validation.
- [x] 5.2 Record stable error category and non-negative duration for every candidate review attempt without raw error leakage.
- [x] 5.3 Preserve manual retry, completed-result reuse, thresholds, deterministic gates, and projection idempotency.

## 6. Verification and Delivery

- [x] 6.1 Run focused AgentRetro tests, migration/security tests, full test suite, and Ruff.
- [x] 6.2 Run `openspec validate harden-recent-session-capture --strict` and update scenario coverage mappings.
- [x] 6.3 Run an isolated recent-session smoke using temporary SQLite and Obsidian paths; confirm no real vault, AGENTS, native memory, or external write.
- [x] 6.4 Run independent code review, resolve material findings, rerun affected checks, and verify a clean scoped diff.
