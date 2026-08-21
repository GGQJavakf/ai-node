## Why

The package-wide ai-todo complexity ceiling of 15 is green, but eight workflow and CLI owners still sit between 11 and 13: Codex import/preview, resume skip copy, daily-triage rendering, Codex report rendering, resume command routing, and work-item detail rendering. The focused compatibility baseline is healthy at 118 tests, so this is a controlled opportunity to lower the maintenance cost without changing the command surface, persistence, ordering, or user-visible text.

## What Changes

- Tighten the declared complexity manifest to Ruff C901@10 for the three affected owner modules while retaining C901@15 for the full ai-todo package.
- Share Codex report entry classification and preparation between import and preview, keeping preview zero-write and import persistence, merge audit, evidence, counts, and ordering exact.
- Replace parallel resume-skip copy ladders with one ordered reason mapping that supplies both progress and next-action text.
- Extract focused data-loading, selection, formatting, and rendering owners from the four affected CLI handlers without changing exception containment or instance monkeypatch seams.
- Extend characterization, architecture, gate, package, Windows-encoding, and independent-review evidence before delivery.

## Capabilities

### Modified Capabilities

- `ai-todo-maintainability`: adds a stricter C901@10 boundary for declared workflow/CLI modules and compatibility requirements for shared Codex import planning, skip copy, and CLI rendering.

## Impact

- Affected code: `application/workflow/codex_resume.py`, `application/workflow/services.py`, `presentation/cli.py`, the complexity gate, manifest, and focused tests.
- Public interfaces, commands, storage schema, dependencies, configuration, and user experience remain unchanged.
- Delivery risk is controlled by the green 118-test focused baseline, exact-output characterization, full regression, package smoke, and fresh independent review.
