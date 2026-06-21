## 1. Command Alias Behavior

- [x] 1.1 Add focused CLI tests showing `/next` returns the same recommendation behavior as `/continue`.
- [x] 1.2 Add focused CLI tests showing bare `/review` returns the same daily review behavior as `/review day`.
- [x] 1.3 Wire `/next` in slash-command dispatch to the existing continue recommendation handler.
- [x] 1.4 Wire bare `/review` to the existing daily review handler while preserving `/review day`.

## 2. Help, Startup, and Completion UX

- [x] 2.1 Add tests that `/help` highlights `/list`, `/sync`, `/next`, `/review`, and `/help` before advanced commands.
- [x] 2.2 Add tests that `/help` groups advanced commands and keeps compatibility entries visible.
- [x] 2.3 Add tests that command completions include both preferred and compatible commands.
- [x] 2.4 Update `CommandCompleter` descriptions to make `/next` and `/review` primary while retaining `/continue` and `/review day`.
- [x] 2.5 Restructure `/help` into primary commands and advanced command groups without removing legacy commands.
- [x] 2.6 Update the startup panel so primary commands are shown first and advanced commands are grouped below.
- [x] 2.7 Add categorized help topics for Todo, workflow/evidence, preferences, and system commands.
- [x] 2.8 Keep main `/help` and the startup panel compact and free of Rich markup syntax.

## 3. Documentation and Compatibility

- [x] 3.1 Update README command documentation to describe the primary daily command set and compatibility aliases.
- [x] 3.2 Verify `/list` and `/sync` behavior stays unchanged through existing workflow CLI tests.
- [x] 3.3 Verify command guidance does not claim external Redmine/GitLab/MR writes, time logging, merge, push, closeout, cleanup, or publish behavior.

## 4. Validation

- [x] 4.1 Run targeted CLI/workflow unittest coverage.
- [x] 4.2 Run the full unittest suite with `python -m unittest discover -s tests`.
- [x] 4.3 Run `openspec validate simplify-assistant-command-surface --strict`.
- [x] 4.4 Review the final diff to confirm no unrelated user changes were reverted or modified.
