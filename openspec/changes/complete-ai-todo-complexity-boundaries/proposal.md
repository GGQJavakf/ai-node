## Why

The ai-todo assistant still has five command, workflow, and triage functions above the established McCabe ceiling of 15. Their branching mixes routing, filtering, mutation, and rendering, which makes common CLI and Codex-resume behavior harder to change safely even though the current 84 focused regressions are green.

## What Changes

- Decompose the five ai-todo `C901` hotspots above 15 into focused private helpers or declarative dispatch while preserving public method signatures and output.
- Add an ai-todo complexity manifest and architecture guard that cover the affected facade modules and any extracted private collaborators.
- Add focused characterization for command routing, list filtering/rendering, work-item operations, triage reasons, and Codex resume candidate selection before refactoring.
- Enforce Ruff `C901` at 15 for the declared ai-todo scope without suppressions or expanding this phase to functions already at or below 15.
- Record full regression, coverage, packaging, Windows compatibility, and independent review evidence before delivery.

## Capabilities

### New Capabilities
- `ai-todo-maintainability`: Defines ownership, complexity, compatibility, and verification guardrails for the remaining ai-todo hotspots above 15.

### Modified Capabilities

None. Existing command, workflow, resume, and triage requirements remain behaviorally unchanged.

## Impact

- Affected code: `ai_todo_assistant.application.workflow.codex_resume` and `ai_todo_assistant.presentation.cli`, plus narrowly scoped private helpers they own.
- Affected tests and tooling: command-surface, personal-assistant, workflow CLI, Codex-resume, architecture, and complexity checks.
- Public CLI commands, Python entry points, persistence schemas, resume/exclusion semantics, dependencies, and installed-package interfaces remain unchanged.
