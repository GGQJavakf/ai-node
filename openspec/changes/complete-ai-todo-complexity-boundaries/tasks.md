## 1. Baseline and Guardrails

- [x] 1.1 Record the five ai-todo C901 findings above 15 and run the focused command, workflow, and Codex-resume regression baseline.
- [ ] 1.2 Add the ai-todo complexity manifest, package-wide C901@15 script, and architecture regressions for target validity and extracted ownership.
- [ ] 1.3 Add missing characterization for handler monkeypatching, mixed list/source behavior, work-command failures, overlapping triage reasons, and resume skip precedence/de-duplication.

## 2. Codex Resume Selection

- [ ] 2.1 Decompose `_select_candidates` into named exclusion, unfinished-entry, non-resumeable-bucket, and missing-target steps without changing ordering, reasons, target semantics, or fail-closed policy behavior.
- [ ] 2.2 Run Codex resume service and CLI shortcut regressions, including manual exclusions, malformed reports, denied buckets, duplicates, dry-run, and targeted selection.

## 3. Slash Routing and List Rendering

- [ ] 3.1 Decompose `_handle_slash_command` into tokenization and explicit handler dispatch while preserving aliases, argument shapes, terminal values, unknown-command text, and instance monkeypatch seams.
- [ ] 3.2 Decompose `_handle_list_command` into named filter selection, row assembly, ordering, and rendering helpers without changing titles, source handling, Rich values, or empty states.
- [ ] 3.3 Run command-surface, personal-assistant, list/filter, daily-triage, source-filter, and mixed todo/work-item regressions.

## 4. Work Commands and Triage Reasons

- [ ] 4.1 Decompose `_handle_work_command` into focused subcommand handlers while preserving validation precedence, service calls, persistence, exception translation, and exact response text.
- [ ] 4.2 Decompose `_work_item_triage_reason` into named precedence checks without changing the first selected reason for overlapping conditions.
- [ ] 4.3 Run work-item add/status/conflicts/show/rollback/import/split/evidence plus triage ordering and failure regressions.

## 5. Verification and Delivery

- [ ] 5.1 Make the manifest and full `src/ai_todo_assistant` scan pass C901 at 15, plus Ruff, focused mypy, compileall, architecture checks, and `git diff --check` without suppressions.
- [ ] 5.2 Run the full branch-aware pytest and coverage gate, package build/Twine/isolated-wheel smoke, UTF-8/GBK command smoke, and strict validation for this change and all OpenSpec artifacts.
- [ ] 5.3 Run OCR delegate preview/rule over the exact diff and a fresh compatibility review of routing, rendering, persistence, triage precedence, resume exclusions, and skip ordering; resolve every material finding and account for exclusions.
- [ ] 5.4 Publish responsibility-sized commits to a Draft PR with exact evidence, verify remote CI on the immutable head, then perform authorized Ready/merge and archive readback.
