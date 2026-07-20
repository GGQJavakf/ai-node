# AgentRetro Obsidian Managed-Block Initialization Implementation Plan

> **Execution:** Implement sequentially with `superpowers:test-driven-development`; verify final claims with `superpowers:verification-before-completion`.

**Goal:** Add a preview-first, deterministic, recoverable initializer that safely adds AgentRetro summary/index markers to existing optional Obsidian pages, then use it to recover the known pending projection without changing pending review candidates.

**Architecture:** Add an infrastructure planner for marker inspection and deterministic target rendering, plus an application service that validates the audited mapping, applies a hash-bound plan through retained backups and all-target rollback, and journals rollback-required state. Expose it through `retro sync init`; keep the existing `retro sync retry` as a separate authorization boundary.

**Tech Stack:** Python 3.10+, argparse, dataclasses, pathlib, hashlib, difflib, tempfile, sqlite3 repository, pytest, Ruff, OpenSpec.

## Global Constraints

- Preserve all existing `ai-todo` behavior and current AgentRetro review/brief semantics.
- Preview creates no vault, backup, database, or candidate mutation.
- Never create a missing optional note or modify bytes preceding the appended managed block.
- Reject malformed/foreign markers, unsafe paths, non-regular files, non-UTF-8 content, stale plans, and rollback-blocked state.
- Keep real Obsidian apply until temporary-vault tests and the complete regression gate pass.
- Exclude `.playbook/` and all real user data from commits.

### Task 1: Lock OS-25..OS-29 in failing tests

**Files:**
- Modify: `tests/test_agentretro_obsidian.py`
- Modify: `tests/test_agentretro_cli.py` or the closest existing AgentRetro CLI test module
- Modify: `tests/agentretro_scenarios.py`

- [ ] Add a preview test proving no writes, deterministic plan ID, complete per-target hashes/diffs/backups, and no creation of missing optional files.
- [ ] Add a cross-process-style recomputation/apply test proving a matching plan applies and a changed target is rejected as stale.
- [ ] Add marker/path tests for valid idempotence, partial/duplicate/nested/mismatched/foreign markers, invalid UTF-8, directories, traversal, and symlinks.
- [ ] Add multi-target backup/write/readback/rollback failure injection tests, including `rollback_required` persistence when restoration cannot be verified.
- [ ] Add CLI JSON/human-output tests and map `OS-25..OS-29` to the new tests.
- [ ] Run the focused tests and confirm they fail for the missing initializer, not for fixture errors.

### Task 2: Implement deterministic marker planning

**Files:**
- Modify: `src/agent_retro/infrastructure/obsidian.py`
- Add: `src/agent_retro/application/obsidian_init.py`

- [ ] Add exact marker inspection/rendering helpers that preserve input bytes and newline style.
- [ ] Define immutable target/plan/result records with redaction-safe relative paths, before/after hashes, complete unified diffs, backup paths, and changed flags.
- [ ] Resolve only existing optional summary/index targets beneath the configured vault and validate the active audited project mapping.
- [ ] Derive the plan ID from canonical relative targets, existence, input hashes, planned hashes, marker kind, and project ID.
- [ ] Recompute and compare the supplied plan ID during apply; reject stale inputs before the first backup or write.

### Task 3: Implement journaled apply and CLI wiring

**Files:**
- Modify: `src/agent_retro/application/bootstrap.py`
- Modify: `src/agent_retro/presentation/cli.py`
- Modify: `src/agent_retro/application/obsidian_init.py`

- [ ] Add `retro sync init --project <project> [--apply <plan-id>]`; default to preview.
- [ ] Before writing, block on any existing `rollback_required` sync job, create retained backups, and journal the initialization run without changing knowledge/candidate rows.
- [ ] Use same-directory temporary files, exact readback, valid-marker verification, and verified all-target restoration.
- [ ] Return stable JSON codes for preview, applied/unchanged, stale plan, unsafe target, and rollback-required failure.
- [ ] Run focused tests until green, then Ruff/format checks for changed files.

### Task 4: Temporary-vault and full regression verification

**Files:**
- Modify: `openspec/changes/add-agentretro-mvp/tasks.md`
- Modify: scenario verification evidence artifact used by the repository

- [ ] Run all AgentRetro Obsidian, CLI, doctor, purge, and merge tests.
- [ ] Run `python -m pytest -q`, targeted Ruff/format checks, `git diff --check`, and `openspec validate add-agentretro-mvp --strict`.
- [ ] Mark `4.12`, `4.13`, `4.15`, and expanded `6.5` complete only after the corresponding evidence passes.
- [ ] Run a final `ai-decision-review` of the implementation diff and fix actionable findings.

### Task 5: Real preview/apply, projection recovery, clean runtime

**Files/state:**
- Read/write only through the new CLI: configured Obsidian optional managed targets and AgentRetro backup/journal state
- Read/write: `C:/Users/Administrator/.agentretro/runtime-v1`
- Read/write: `C:/Users/Administrator/.agentretro/runtime-install.json`

- [ ] Snapshot the real project page hash, relevant projection event, and pending candidate IDs/statuses.
- [ ] Run real `retro sync init --project NPKI --json` and inspect the exact plan without writing.
- [ ] Apply only that confirmed plan ID, read back the managed markers and retained backup, then run `retro sync retry projection-c685f0e7593b93630b2dc2b6`.
- [ ] Verify the project page managed summary matches accepted SQLite knowledge, the projection event is `synced`, and both pending candidates remain pending.
- [ ] Mark task `4.14` complete, run the final full verification, and commit scoped implementation/evidence files.
- [ ] Build a wheel from the clean commit, replace the local runtime, and read back the runtime manifest with the new commit, wheel hash, and `source_dirty=false`.

### Task 6: Separate historical Ruff cleanup

**Files:**
- Modify only the twelve already identified historical lint sites and their smallest relevant regression tests.

- [ ] After the feature/runtime closeout, create a separate cleanup batch from the clean feature commit.
- [ ] Run behavior-locking tests before edits, apply only mechanical behavior-preserving fixes, then run focused and full regression plus repository-wide Ruff.
- [ ] Commit the cleanup separately; do not combine it with Obsidian initialization or runtime evidence.
