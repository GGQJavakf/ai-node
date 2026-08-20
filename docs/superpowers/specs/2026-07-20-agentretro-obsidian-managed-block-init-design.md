# AgentRetro Obsidian Managed-Block Initialization Design

**Status:** Approved for implementation

**Approval:** 2026-07-20; the user selected option A for safe preview/apply initialization, explicit projection retry, clean-commit runtime rebuild, and a separate historical Ruff cleanup batch.

## Problem

AgentRetro correctly refuses to update an existing Obsidian project page or project index when its AgentRetro managed markers are absent. That fail-closed behavior protects user-authored prose, but the CLI currently provides no safe way to initialize those markers. A valid accepted knowledge item can therefore remain `sync_pending` even though the vault and project mapping are otherwise healthy.

## Scope

Add a bounded `retro sync init --project <project>` workflow for the two existing optional projection targets:

- `项目/<project>/项目_<project>.md` with a `summary` block;
- `项目/项目索引.md` with an `index` block.

The command initializes only targets that already exist. Missing optional targets remain absent because normal projection does not require them. It never creates, deletes, renames, or moves a user-authored note.

## CLI Contract

```text
retro sync init --project NPKI
retro sync init --project NPKI --apply <plan-id>
retro sync retry <projection-event-id>
```

The first command is strictly preview-only and returns a stable plan ID, target paths, input and output hashes, complete unified diffs, and planned backup locations. The second command recomputes the current plan and applies it only when the supplied plan ID still matches. Initialization and projection retry are separate commands so marker authorization cannot implicitly authorize later knowledge writes.

## Planning Rules

- Resolve the configured vault root and audited project mapping before planning.
- Reject traversal, symlink components, non-regular targets, invalid UTF-8, and target paths outside the vault.
- If a target has no AgentRetro marker, append exactly one empty managed block using its existing newline style.
- If the correct marker pair is already present and well formed, report that target as unchanged.
- If any AgentRetro marker is partial, duplicated, nested, mismatched, or belongs to another project, reject the complete plan without writing.
- Preserve every existing byte and append only the required newline separator plus the managed block.
- Derive the plan ID deterministically from project ID, canonical relative target paths, target existence, input hashes, and planned output hashes. No preview state needs to be persisted.

## Apply and Recovery

Before the first write, apply repeats all containment, marker, type, and hash checks. It creates retained backups for every existing target, writes through same-directory temporary files, replaces targets, and reads back exact planned bytes and valid markers. If any target fails, it restores every previously changed target and verifies original hashes. A failed restoration reports `rollback_required` and blocks projection through the existing synchronization recovery boundary.

No SQLite knowledge, candidate, or review status changes during initialization. After a successful apply, the existing `retro sync retry <event-id>` command renders current accepted SQLite knowledge into the newly initialized block. Pending candidates remain pending.

## Tests

- Preview is byte-for-byte non-writing and exposes complete diffs and hashes.
- Apply requires the matching deterministic plan ID and rejects stale targets.
- Summary and index blocks are initialized together when both targets exist.
- Existing user prose, encoding bytes, and newline style remain unchanged outside appended blocks.
- Missing targets are not created.
- Valid existing markers are idempotent; malformed or foreign markers fail closed.
- Traversal, symlink, directory target, backup failure, replace failure, readback failure, and rollback failure are covered.
- Real-state smoke uses preview first, applies the confirmed plan, retries only the known pending projection event, and verifies the project page plus retained backup.

## Delivery Boundary

The already completed model-readiness fixes are committed with this feature only after the full regression gate passes, then the user runtime is rebuilt from that clean commit and its manifest must report `source_dirty=false`. The unrelated twelve historical Ruff findings are handled afterward as a separate behavior-preserving cleanup commit with targeted regression evidence.
