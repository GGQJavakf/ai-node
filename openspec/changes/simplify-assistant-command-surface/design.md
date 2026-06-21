## Context

`ai-node` currently exposes a broad slash-command set in `src/ai_todo_assistant/presentation/cli.py`. Recent workflow work added `/sync`, `/codex tasks`, `/work ...`, `/continue`, `/start day`, and `/review day` on top of existing Todo commands. The underlying services already support the target behavior: `/list` is already a unified view, `/sync` is already the manual synchronization entry point, `/continue` already recommends the next action, and `/review day` already generates the daily review. This change should therefore be a narrow command-surface cleanup, not a rewrite of workflow services.

## Goals / Non-Goals

**Goals:**

- Present a small daily command set: `/list`, `/sync`, `/next`, `/review`, `/help`.
- Preserve compatibility for existing commands, including `/continue`, `/review day`, `/codex tasks`, `/work ...`, Todo commands, and exit/history commands.
- Implement `/next` as a command alias for existing next-action recommendation behavior.
- Implement `/review` as a command alias for existing daily review behavior.
- Keep advanced commands available through help and completions, grouped separately from daily commands.
- Keep behavior testable through direct `_handle_slash_command(...)` calls and help/startup text assertions.

**Non-Goals:**

- Do not remove, rename, or deprecate commands in a way that breaks existing scripts or habits.
- Do not alter workflow services, connector behavior, persistence schemas, Codex report parsing, or Todo filtering semantics unless required for alias wiring.
- Do not add background scheduling or a second automation; `/sync` remains the manual entry point over existing report handoff.
- Do not add Redmine/GitLab/MR writes, time logging, merge, push, closeout, cleanup, or production operations.

## Decisions

### 1. Alias at CLI dispatch, not service layer

`/next` should dispatch to the same method that powers `/continue`, and `/review` should dispatch to the same daily review method used by `/review day`. Keeping aliases at the CLI layer avoids duplicating application-service behavior and keeps compatibility simple.

Rejected alternative: Introduce new application services for `/next` and `/review`. That would add indirection without changing domain behavior.

### 2. Treat old commands as compatibility aliases, not deprecated failures

`/continue` and `/review day` must keep returning the same content as their preferred replacements. Help may label them as compatibility or advanced entries, but the runtime must not warn, fail, or require migration.

Rejected alternative: Emit deprecation warnings for old commands. The user explicitly requires old commands to remain compatible, and warnings would add noise to daily workflow output.

### 3. Help is structured by user workflow

`/help` should first show primary daily commands, then group advanced commands by domain: Todo management, workflow/evidence, preferences, diagnostics/history, and exit. This keeps common commands visible without hiding existing capabilities.

Rejected alternative: Keep a flat exhaustive list. The current flat list makes the assistant feel larger than the daily workflow needs.

### 4. Startup panel mirrors primary commands

The startup panel should make the primary command set the first visible command signal and move advanced commands into grouped text. This keeps first-run guidance aligned with `/help`.

Rejected alternative: Only update `/help`. Startup output is part of the command surface and would otherwise continue to teach the old broader daily set.

## Risks / Trade-offs

- [Risk] Alias commands drift from old commands over time -> Mitigation: tests assert `/next` equals `/continue` and `/review` equals `/review day`.
- [Risk] Help grouping hides advanced capabilities -> Mitigation: advanced groups remain visible in `/help`, completions still include legacy and advanced commands.
- [Risk] `/review` could be confused with code review or AI review -> Mitigation: help text labels it as daily work review; scope is local CLI workflow, not external review writes.
- [Risk] Existing tests assert old help text literally -> Mitigation: update or add focused tests for the new grouping and retained compatibility.

## Migration Plan

1. Add tests for `/next`, `/review`, retained `/continue`, retained `/review day`, help grouping, startup primary commands, and completion entries.
2. Wire `/next` and bare `/review` in CLI dispatch to existing handlers.
3. Update command completions and help text to emphasize primary commands while retaining advanced entries.
4. Update startup panel text to show primary commands first and grouped advanced commands below.
5. Update README command documentation if needed.

Rollback strategy: revert the CLI help/completion/dispatch changes. Because no data model or persistence migration is introduced, rollback does not affect existing Todo or WorkItem data.

## Open Questions

- None blocking. The implementation should use current service behavior and avoid expanding scope into workflow-service changes.
