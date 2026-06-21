## Why

The assistant command surface has grown from a simple Todo CLI into a workflow assistant with Todo, Codex, Git/OpenSpec/Playbook sync, WorkItem, evidence, and daily review commands. Daily use now needs fewer primary commands, clearer aliases, and help/startup output that guides users toward the stable workflow without breaking existing habits.

## What Changes

- Make `/list` the unified task view for everyday work, continuing to combine local Todo items and synchronized WorkItems.
- Keep `/sync` as the single manual synchronization entry point for Codex reports and current project context.
- Add `/next` as the preferred daily command for next-action recommendation, with `/continue` retained as a compatibility alias.
- Add `/review` as the preferred daily review command, with `/review day` retained as a compatibility alias.
- Update `/help`, completions, and the startup panel so primary commands are prominent and advanced commands are grouped below them.
- Keep legacy commands compatible; no existing slash command is removed in this change.
- Do not change external write boundaries: command help and aliases must not imply Redmine/GitLab/MR writes, time logging, merge, closeout, cleanup, or push.

## Capabilities

### New Capabilities

- `assistant-command-surface`: Defines the simplified daily command surface, compatibility aliases, help grouping, startup panel behavior, and acceptance criteria for command UX.

### Modified Capabilities

- None. Existing Todo and workflow capabilities keep their behavior; this change only adds a command-surface contract around existing and aliased entry points.

## Impact

- Affected code:
  - `src/ai_todo_assistant/presentation/cli.py` command parsing, completions, help output, and startup panel.
  - CLI-focused tests under `tests/`, especially workflow and command UX tests.
  - README command documentation if implementation updates user-facing command tables.
- Affected behavior:
  - `/next` returns the same next-action recommendation as `/continue`.
  - `/review` returns the same daily review draft as `/review day`.
  - `/help` and startup output emphasize `/list`, `/sync`, `/next`, `/review`, and `/help`, while preserving discoverability for advanced commands.
- Dependencies:
  - No new Python package dependency.
  - No database migration.
  - No external API or external write operation.
