## 1. OpenSpec and Review

- [x] 1.1 Add proposal, design, tasks, and spec delta for stronger completion signal detection.
- [x] 1.2 Run `openspec validate strengthen-completion-signal-detection --strict`.
- [x] 1.3 Run `ai-decision-review` OpenSpec review and fix any blocking document issues before implementation.

## 2. Regression Tests First

- [x] 2.1 Add workflow service tests proving unfinished or blocked Codex entries with MR/Redmine/OpenSpec/Playbook/final-validation completion signals become `done`.
- [x] 2.2 Add tests proving `done` WorkItems do not regress and produce reopen review candidate details when later reports are unfinished or blocked.
- [x] 2.3 Add tests proving repeated imports and dry-run preview remain idempotent and do not write duplicate Evidence.
- [x] 2.4 Add CLI `/sync` tests proving completion counts and reopen candidate counts appear in the summary/details.

## 3. Implementation

- [x] 3.1 Add conservative local completion-signal detection helpers for Codex report entries.
- [x] 3.2 Apply detected strong completion signals before Codex blocked/unfinished state transitions.
- [x] 3.3 Add `reopen_candidates` to the import result summary without changing persisted schema.
- [x] 3.4 Ensure real import and dry-run preview share the same classification behavior.
- [x] 3.5 Keep external systems read-only and write only local WorkItem/Evidence state.

## 4. Verification and Closeout

- [x] 4.1 Run focused workflow service and CLI tests.
- [x] 4.2 Run `python -m compileall -q src tests`.
- [x] 4.3 Run `python -m unittest discover -s tests`.
- [x] 4.4 Run `openspec validate strengthen-completion-signal-detection --strict`.
- [x] 4.5 Archive the change and run `openspec validate --specs --strict` plus `openspec list`.
- [x] 4.6 Review the diff for behavior boundary, sensitive data, generated output, and local runtime data before commit.
