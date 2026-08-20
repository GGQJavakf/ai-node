## 1. Characterization and enforceable boundaries

- [x] 1.1 Add public-import and compatibility-seam tests for CLI entry points, repository/service constructors, and extracted-module import order.
- [x] 1.2 Add a declared refactor-module manifest plus a scoped Ruff C901 ceiling of 15 that fails for an uncovered owned module or covered complexity regression.
- [x] 1.3 Capture the focused CLI envelope, SQLite schema/migration/WAL, sync, merge-plan, and purge-journal regression baselines before extraction.

## 2. Presentation decomposition

- [x] 2.1 Extract command-family dispatch and rendering from `presentation/cli.py` into focused internal presentation modules while retaining `main`, `_run_command`, parser behavior, and historical monkeypatch seams.
- [x] 2.2 Run CLI, value-loop, subprocess UTF-8/GBK, and JSON content-safety regressions; resolve every compatibility difference before continuing.

## 3. SQLite repository decomposition

- [x] 3.1 Extract schema/migration backup, consistency-check, and restore mechanics behind `SQLiteRetroRepository` without changing schema version, lock ordering, or the module-level test seams.
- [x] 3.2 Extract purge inspection/journal persistence behind the repository facade without changing transaction ownership, row ordering, or port behavior.
- [x] 3.3 Run persistence, migration rollback, backup quick-check, concurrent WAL writer, capture/review, and purge repository regressions after the SQLite split.

## 4. Synchronization and semantic-merge decomposition

- [x] 4.1 Extract projection path/preflight, confirmed-operation validation, backup/replace, and lock helpers while preserving `SyncService` and `ProjectionCoordinator` behavior.
- [x] 4.2 Extract semantic-merge external-edit discovery, reconciliation helpers, and plan codec/persistence mechanics while preserving plan identity and public models.
- [x] 4.3 Run Obsidian synchronization and semantic-merge success, already-applied, preflight-failed, backup/write-failed, rollback-required, nested-project, and plan-tamper regressions.

## 5. Purge decomposition

- [x] 5.1 Extract registered-target, manifest, fingerprint, containment, and filesystem-operation mechanics from `PurgeService` with all effects passed explicitly.
- [x] 5.2 Extract interrupted-operation recovery classification and stage transitions while preserving purge journal identity, idempotency, and fail-closed residual handling.
- [x] 5.3 Run purge preview/apply/interruption/retry/recovery, residual, symlink/containment, SQLite-authority, and projection cleanup regressions.

## 6. Final gates and review

- [x] 6.1 Make every declared target and extracted module pass scoped C901 at 15, Ruff, focused mypy, compileall, import/architecture checks, and `git diff --check` without per-function suppression.
- [x] 6.2 Run the full deterministic pytest suite, branch-coverage gate, package build/Twine/isolated-wheel smoke, Windows UTF-8/GBK smoke, and strict validation for this change and all OpenSpec artifacts.
- [x] 6.3 Run OCR delegate preview/rule over the exact branch diff and a fresh high-risk review of SQLite concurrency, filesystem containment, rollback, CLI compatibility, and excluded-file accounting; resolve every material finding.
- [x] 6.4 Record exact commit/check evidence in the Draft PR, verify remote CI on the published head, and keep the change unmerged until its external state is read back.
