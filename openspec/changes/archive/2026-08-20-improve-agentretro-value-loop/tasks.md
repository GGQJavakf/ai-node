## 1. Characterization and project references

- [x] 1.1 Add failing resolver tests for canonical ID, normalized credential-free remote, unique longest workspace path, Git worktree remote, unknown input, equal-specificity ambiguity, and path/remote identity conflict. (BR-06, BR-29, BR-30, BR-35, BR-36)
- [x] 1.2 Implement one read-only project-reference resolver over active mappings and wire canonical resolution into `retro brief` and project-filtered inbox queries. (BR-06, BR-35, BR-36, KR-27)
- [x] 1.3 Add JSON and terminal tests proving unknown or ambiguous input returns stable safe diagnostics and never reads knowledge or renders a successful empty result. (BR-29, BR-30, KR-27)

## 2. Preview-first recent capture

- [x] 2.1 Add settings validation for positive `recent_capture_max` default 20 and prove out-of-bounds input performs no discovery or write. (CR-26)
- [x] 2.2 Extend the Codex source adapter with bounded newest-first completed-session discovery and tests for active, incomplete, unsupported, duplicate, timeout, and source-size cases. (CR-01, CR-02, CR-03, CR-23)
- [x] 2.3 Add versioned canonical plan models and hashing over requested count, effective maximum, and ordered session/source/resolution/project/mapping/reuse identity; prove every identity change rejects before the first write. (CR-23, CR-25)
- [x] 2.4 Add `retro capture --recent <count> --dry-run` with deterministic output and repository, audit, projection, vault, hook, watcher, and scheduler no-write assertions. (CR-04, CR-23)
- [x] 2.5 Add `retro capture --recent <count> --apply <plan-id>` with pre-write revalidation, unresolved routing skips, per-session idempotent capture, and four disjoint ordered result lists. (CR-24)
- [x] 2.6 Add partial-failure and re-preview tests proving first failure stops the batch, prior commits remain, remaining items are skipped, the old plan is invalid, and a new plan reuses prior commits without duplicates. (CR-27, CR-28)

## 3. Review inbox and brief health

- [x] 3.1 Add count/ID-only repository/application queries for captured sessions, pending/retryable candidates, eligible knowledge, effective expiry, and unknown/ambiguous awaiting sessions without returning sensitive content. (BR-31, BR-32, KR-25, KR-26, KR-28, KR-29, KR-30)
- [x] 3.2 Implement cross-project, project-filtered, and awaiting inbox output with fixed ordering, injected-clock ages, limit 1..50/default 20, total/returned/truncated fields, exact commands, and the specified retryability predicate. (KR-25, KR-26, KR-28)
- [x] 3.3 Extend empty brief results with the canonical project, four defined counts, and exact inbox/capture commands using `min(5, recent_capture_max)`, while preserving non-empty budget and ordering behavior. (BR-31, BR-32, BR-33, BR-34)
- [x] 3.4 Add injected-clock tests proving stored active `TASK_STATE` is effectively expired at `valid_until <= now` without mutating SQLite, audit, projection, or Obsidian state. (BR-07, KR-29, KR-30)
- [x] 3.5 Add model-boundary and subprocess tests proving inbox and empty-brief output never includes candidate text, evidence excerpts, source paths, remote credentials, model errors, reusable credentials, or ANSI sequences. (BR-34, KR-25, KR-28)
- [x] 3.6 Preserve SQLite-as-authority synchronization warnings and non-empty brief semantics in focused regressions. (BR-08, BR-33)

## 4. Documentation and executable scenario coverage

- [x] 4.1 Update README first-use and daily-loop guidance for project references, recent capture preview/apply with plan ID, awaiting/project inbox, and actionable empty briefs.
- [x] 4.2 Update executable AgentRetro scenario mappings for CR-01..04, CR-23..28, KR-25..30, and BR-06..08/29..36; make the mapping test fail on any missing scenario.
- [x] 4.3 Run `openspec validate improve-agentretro-value-loop --strict` and resolve every artifact or scenario validation error.

## 5. Verification, review, and closeout prerequisites

- [x] 5.1 Run focused mapping, capture, review, briefing, CLI, persistence, security, and subprocess tests.
- [x] 5.2 Run full pytest, Ruff, mypy on touched production files, compileall, branch coverage, and Windows UTF-8/GBK command smoke.
- [x] 5.3 Run OCR delegate review and a fresh independent decision/code review; resolve material findings and record exact evidence in the Draft PR.
- [x] 5.4 After implementation verification, archive completed prerequisite changes in order: `add-agentretro-mvp`, strict validate all, then `harden-recent-session-capture`, strict validate all; stop and fix any conflict before this change is readied for archive.
- [x] 5.5 Sync this delta against the resulting main specs, run strict validation for this change and all specs, and record that `improve-agentretro-value-loop` is ready for final archive after its tasks are complete.
