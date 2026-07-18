# Task 4 Implementer Report

## Milestone A: strict review contracts and deterministic policy core

Status: complete for the explicitly scoped milestone; Task 4 as a whole remains incomplete.

### RED evidence

- Command: `python -m pytest tests/test_agentretro_review.py -q`
- Result: exit 1 during collection.
- Expected failure: `ModuleNotFoundError: No module named 'agent_retro.application.review'`.
- The failing test file was present before any Task 4 production module was added.

### GREEN evidence

- Focused command: `python -m pytest tests/test_agentretro_review.py -q`
- Result: `18 passed in 0.08s`.
- Full command: `python -m pytest -q`
- Result: `289 passed in 9.84s`.
- Whitespace check: `git diff --check` returned no findings before staging.

### Implemented behavior

- Strict Pydantic extraction and independent-review response contracts reject coercion, missing required fields, and unknown fields.
- Extraction and review use distinct prompts and distinct model requests and forward the effective timeout to the shared client.
- Fixed automatic-acceptance thresholds are implemented for `RULE`, `LESSON`, and `TASK_STATE`.
- Deterministic blockers are returned in stable order for `secret`, `insufficient_evidence`, `unknown_project`, `duplicate`, `conflict`, `speculation`, `rule_authority`, and `lesson_verification`.

### Scope boundary

- Not implemented in this milestone: repository changes, candidate persistence, review service orchestration, retry, manual lifecycle actions, conflicts/versions, CLI review commands, or project reclassification wiring.
- No OpenSpec task was marked complete because `2.8` and `3.1` through `3.9` require the remaining milestones.
- No purge, Obsidian, briefing, global `AGENTS.md`, memory, external write, or `.playbook/` change was made.

## Milestone B: persisted review orchestration and idempotent retry

Status: complete for the explicitly scoped milestone; manual lifecycle, conflicts, and CLI work remain incomplete.

### RED evidence

- Command: `python -m pytest tests/test_agentretro_review.py -q`
- Result: exit 1 during collection after the service-ordering and retry-idempotence tests were added.
- Expected failure: `ImportError: cannot import name 'ReviewService' from 'agent_retro.application.review'`.
- The expanded failure, timeout, decision, task-state, and session-retry tests retained the same missing-service RED before production implementation.

### GREEN evidence

- Focused command: `python -m pytest tests/test_agentretro_review.py -q`
- Result after helper-boundary refactor: `30 passed in 1.14s`.
- Persistence plus review command: `python -m pytest tests/test_agentretro_persistence.py tests/test_agentretro_review.py -q`
- Result after helper-boundary refactor: `53 passed in 1.83s`.
- Full command: `python -m pytest -q`
- Result after helper-boundary refactor: `301 passed in 11.84s`.
- OpenSpec command: `openspec validate add-agentretro-mvp --strict`
- Result: `Change 'add-agentretro-mvp' is valid`.
- Whitespace check: `git diff --check` returned no findings.

### Implemented behavior

- `ReviewService.review_session()` persists every redacted extracted candidate before the independent review request.
- `review_stored_evidence()` reuses stored evidence and pending candidates and exposes a stable retryable failure without reading source JSONL.
- Review attempts are append-only after terminal completion, store only an input hash and redacted result or stable sanitized error code, and remain retryable after failure.
- Completed review attempts are reused by candidate plus canonical-input hash, preventing another model request, attempt, or accepted knowledge row.
- Session retry selects only pending candidates without a completed model attempt; low-confidence, model-rejected, and gate-blocked completed reviews stay pending without repeated model work.
- Successful `ACCEPT` results pass through type threshold and every deterministic gate before `auto_accepted`; audit detail records actor, threshold, verdict, blockers, and evidence IDs.
- Automatically accepted `TASK_STATE` knowledge receives a default `valid_until` exactly 14 days after the injected acceptance clock.
- Application orchestration uses only typed `RetroRepository` methods; SQLite details remain inside the infrastructure adapter.

### Scope boundary

- Not implemented in this milestone: manual accept/edit/reject, conflict creation/resolution, promotion, expiry mutation, archive, CLI review/retry commands, or project-reclassify CLI wiring.
- OpenSpec task checkboxes remain unchanged until the complete `2.8` and `3.1` through `3.9` behavior is delivered.
- No purge, Obsidian, briefing, global `AGENTS.md`, memory, external write, or `.playbook/` change was made.

## Milestone C: manual lifecycle, version history, and reclassification consistency

Status: complete for the explicitly scoped non-CLI milestone.

### RED evidence

- First command: `python -m pytest tests/test_agentretro_knowledge.py -q`.
- First result: exit 1 during collection with `ModuleNotFoundError: No module named 'agent_retro.application.knowledge'`.
- Second RED command used the same focused file after conflict, version, expiry, archive, and reclassification tests were added.
- Second result: `4 passed, 4 failed`; the failures identified the missing lifecycle methods and confirmed that reclassification left pending candidates on the awaiting project.

### GREEN evidence

- Knowledge command: `python -m pytest tests/test_agentretro_knowledge.py -q`.
- Result after the transaction rollback case was added: `9 passed in 0.85s`.
- Review, lifecycle, and persistence command: `python -m pytest tests/test_agentretro_review.py tests/test_agentretro_knowledge.py tests/test_agentretro_persistence.py -q`.
- Result: `61 passed in 2.53s` before the additional rollback-only test.
- Full command: `python -m pytest -q`.
- Final result after the rollback-only test: `310 passed in 16.36s`.
- OpenSpec command: `openspec validate add-agentretro-mvp --strict`.
- Result: `Change 'add-agentretro-mvp' is valid`.
- Ruff checks for the new lifecycle service and tests passed; `git diff --check` returned no findings.

### Implemented behavior

- Manual `accept`, `edit`, and `reject` are user-only, pending-only transitions with typed repository operations, original evidence links, and before/after audit hashes.
- A successful `review_session` is a terminal readback: repeating it does not re-extract, re-review, or create another candidate or knowledge row.
- Conflict detection leaves the old knowledge active and the new candidate pending. User resolution creates a new version under the same knowledge ID, records superseded knowledge/candidate references, resolves the conflict, and preserves prior versions.
- Explicit user promotion creates a global-scope version. Expiry creates a stale `TASK_STATE` version. Archive creates an archived version. None of these operations deletes text, evidence, or history.
- Typed knowledge history returns every version, evidence reference, acceptance actor, superseded reference, and lifecycle audit entry.
- Reclassification updates the awaiting session and only its pending candidates in one transaction, with a combined before/after audit. An injected audit failure proves that both updates roll back together.

### Scope boundary

- No CLI or model gateway wiring was added in Milestone C, per the milestone instruction.
- OpenSpec checkboxes remain unchanged because `2.8`, `3.6`, and `3.9` explicitly require CLI surfaces not authorized in this milestone; partially covered task groups were not reported as complete.
- No purge, Obsidian, briefing, global `AGENTS.md`, memory, external write, or `.playbook/` change was made.

## Milestone D: review CLI, model composition, and stored-evidence reclassification

Status: complete for OpenSpec tasks `2.8` and `3.1` through `3.9`; purge and scenario-index work remain open.

### RED evidence

- First command: `python -m pytest tests/test_agentretro_cli.py -q`.
- First result: `3 failed`; the parser did not recognize `review`, and the CLI had no `_build_review_service` composition boundary.
- Second command: `python -m pytest tests/test_agentretro_foundation.py::test_legacy_model_client_from_config_refilters_and_copies_allowlist tests/test_agentretro_cli.py -q`.
- Second result: `6 failed, 5 passed`; failures identified the missing allowlisted one-read model composition, incorrect null-retry success, and missing project reclassification CLI wiring.
- Final security RED: the focused sensitive-error test failed because `api_key=must-not-leak` appeared in the JSON detail; the generic error path now applies the shared redactor before human or JSON output.

### GREEN evidence

- Focused command: `python -m pytest tests/test_agentretro_cli.py tests/test_agentretro_review.py tests/test_agentretro_knowledge.py tests/test_agentretro_capture.py tests/test_agentretro_foundation.py -q`.
- Result: `137 passed in 5.72s`.
- Full command: `python -m pytest -q`.
- Final result after the sensitive-error regression test: `322 passed in 15.95s`.
- Formatting and lint checks: all seven changed Python files were already formatted after the scoped formatter run, and `ruff check` reported `All checks passed!`.
- OpenSpec command: `openspec validate add-agentretro-mvp --strict`.
- Result: `Change 'add-agentretro-mvp' is valid`.

### Implemented behavior

- `retro review` now exposes run, list, show, accept, edit, reject, retry, merge, promote, and archive commands with typed arguments and mutually exclusive retry selectors.
- List, show, and manual lifecycle commands compose no model client. Run, retry, and project reclassification build the review service from one allowlisted legacy-config read, with a stable error when the model is absent.
- JSON responses use stable English messages and serialize enums and datetimes safely; human output remains Unicode-safe.
- Model unavailability produces a stable retryable result rather than a successful null response.
- `retro project reclassify` reviews only evidence already persisted in SQLite. Failed review leaves the session and candidates awaiting classification; successful review then reclassifies the session and its pending candidates transactionally.
- The model-client helper reapplies the allowlist to the already-read config, so unrelated legacy values cannot reach client construction.

### Scope boundary

- OpenSpec tasks `2.8` and `3.1` through `3.9` are marked complete. Tasks `3.10` and `3.11` remain open.
- Tests use injected or monkeypatched gateways and temporary SQLite repositories; no real model request or user session path was used.
- No purge, Obsidian, briefing, global `AGENTS.md`, memory, external write, or `.playbook/` change was made.
