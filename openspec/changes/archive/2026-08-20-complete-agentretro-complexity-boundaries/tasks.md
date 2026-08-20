## 1. Baseline and complete complexity boundary

- [x] 1.1 Record the six remaining AgentRetro C901 findings and the focused behavior/security regression baseline for each owning module.
- [x] 1.2 Extend the shared complexity manifest and architecture checks to every affected facade and new private collaborator, including a full `src/agent_retro` C901 assertion at 15.

## 2. Briefing and semantic-merge planning

- [x] 2.1 Decompose `BriefService.build` into named selection, validation, budget, and result-assembly steps without changing deadlines, ordering, stale filtering, routing, or rendered output.
- [x] 2.2 Decompose `MergePlanner.plan` into named project validation, bounded discovery, gateway, and persistence steps without changing path containment, limits, deadlines, plan identity, or zero-write failures.
- [x] 2.3 Run focused briefing, value-loop, merge-planner, nested-project, deadline, input-limit, sensitive-input, and plan-tamper regressions.

## 3. Session parsing and credential redaction

- [x] 3.1 Decompose `CodexSessionSource._parse` while preserving bounded reads, source/event ordering, encoding behavior, identity, replay handling, deadline checks, and symlink/path rejection.
- [x] 3.2 Decompose sensitive-header scanning while preserving fail-closed Authorization/Cookie handling, quote/escape/obs-fold/flattened boundaries, `X-*` non-matches, idempotency, and linear work.
- [x] 3.3 Run session-hardening, capture, redaction component, long-input complexity, model-boundary, SQLite raw-byte, and replay regressions.

## 4. Codex guidance and review presentation

- [x] 4.1 Decompose `CodexGuidance._execute` while preserving preview identity, backup-first ordering, atomic replacement, readback, rollback-required state, retained backups, and monkeypatch seams.
- [x] 4.2 Decompose `run_review_command` into command-family outcome helpers while preserving service calls, CLI arguments, JSON/human envelopes, exits, retry behavior, projection warnings, and recovery commands.
- [x] 4.3 Run Codex integration apply/remove/failure/rollback plus review/CLI/value-loop/UTF-8/GBK compatibility regressions.

## 5. Final gates and delivery

- [x] 5.1 Make the shared manifest and full AgentRetro scan pass C901 at 15, plus Ruff, focused mypy, compileall, architecture checks, and `git diff --check` without suppressions.
- [x] 5.2 Run the full branch-aware pytest and coverage gate, package build/Twine/isolated-wheel smoke, and strict validation for this change and all OpenSpec artifacts.
- [x] 5.3 Run OCR delegate preview/rule over the exact diff and a fresh high-risk review of session bounds, redaction, path containment, backup/rollback, deadline/budget, and CLI compatibility; resolve every material finding and account for exclusions.
- [x] 5.4 Publish responsibility-sized commits to a Draft PR with exact evidence, verify remote CI on the immutable head, then perform authorized Ready/merge and archive readback.
