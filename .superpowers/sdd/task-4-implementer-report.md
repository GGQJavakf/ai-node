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

## Task 4 follow-up: post-candidate exception context

- Added real `ReviewService` plus temporary SQLite RED coverage for both candidate paths: phase-one extraction returns zero and phase two fails after a newly saved candidate's review attempt is completed; a preexisting pending candidate fails at the same persistence boundary.
- Once a candidate batch is known, pending retry and extract-then-review now wrap every subsequent exception in `ReviewUnavailableError` with that exact batch's candidate IDs. Candidate persistence failures after IDs are deterministically known use the same boundary; extraction failures before candidates exist retain empty IDs.
- Wrapping preserves the original exception as `__cause__` while the outer message contains only the stable `safe_error` code. Secret-like injected exception text is neither exposed by the outer exception nor persisted as diagnostics.
- The exact IDs feed typed reclassification rollback, so target candidates return to awaiting/pending, attempts/audits remain, and a later reclassification converges through canonical hash reuse/retry without selecting unrelated candidates.
- RED: `2 failed`. GREEN: new target `2 passed`; all reclassification tests `5 passed`; focused `133 passed`; full `343 passed`; scoped Ruff format/check, OpenSpec strict validation, and diff check passed.

## Task 4 follow-up: second-phase candidate compensation

- A real `ReviewService` plus temporary SQLite regression covers awaiting extraction returning no candidates, target extraction creating two candidates, the first accepting and the second failing review.
- Reclassification snapshots every preexisting candidate state and the complete knowledge/conflict baseline. Review failure carries the exact IDs handled by that invocation, so rollback restores only prior pending candidates and explicitly affected second-phase candidates without using a time window or a session-wide difference.
- Rollback restores preexisting state, moves newly created affected candidates to the previous project as pending, removes only knowledge/conflict absent from the baseline, and retains attempts/audits. Reclassification then converges through canonical-input reuse/retry.
- RED reproduced the two target-project candidates left after rollback. GREEN: target `3 passed`, focused `131 passed`, full `341 passed`; OpenSpec strict and diff checks passed.
- Changed AgentRetro files, including formatting-only `review_contracts.py`, pass Ruff format/check. Repository-wide Ruff still reports preexisting unrelated debt: 66 files would reformat and 13 legacy lint errors.

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

## Milestone D review remediation: real evidence, complete audit, atomic recovery, and conflicts

Status: all four independent-review Important findings and the requested manual-edit validation are resolved.

### RED evidence

- Real capture vocabulary: the synthetic Codex JSONL cross-layer test produced real `user`, `assistant`, and `command` evidence, but both grounded RULE and LESSON candidates remained pending (`2 failed, 2 passed`).
- Decision audit: accepted, below-threshold, rejected, and blocked reviews were persisted with actor `system` and without threshold, threshold-pass, ordered blockers, or evidence facts (`5 failed`).
- Conflict application: a valid active-knowledge `conflict_with` created no conflict record, while the hallucinated-ID negative control already stayed pending (`1 failed, 1 passed`).
- Manual edit validation: empty text and invalid `valid_until` combinations were accepted (`3 failed`).
- Reclassification: an obsolete completed attempt hid a pending candidate, target-project review did not run, and a second-phase failure did not roll back (`3 failed`).
- Compensation review: a same-result target review lost its second decision audit and rollback deleted a preexisting conflict (`2 failed`).

### GREEN evidence

- Review-focused vocabulary and gate slice: `13 passed`.
- Decision-audit slice: `5 passed`.
- Conflict and lifecycle slices: `3 passed` and `4 passed`.
- Reclassification, rollback-difference, and decision-idempotence slices: `3 passed`.
- Cross-layer focused command: `python -m pytest tests/test_agentretro_review.py tests/test_agentretro_capture.py tests/test_agentretro_knowledge.py tests/test_agentretro_cli.py tests/test_agentretro_persistence.py -q`.
- Focused result: `130 passed in 8.58s`.
- Full command: `python -m pytest -q`.
- Full result: `340 passed in 15.19s`.
- Ruff formatting and lint checks passed for all eleven changed Python files.
- `openspec validate add-agentretro-mvp --strict` returned `Change 'add-agentretro-mvp' is valid`; `git diff --check` returned no findings.

### Remediated behavior

- RULE authority accepts real captured `user` evidence while preserving independent model review and speculation gates. LESSON grounding recognizes explicit failure, correction, and verification semantics across three distinct real evidence items and retains support for semantic evidence kinds.
- Every completed model review writes a typed decision audit with actor, threshold, threshold result, ordered blockers, verdict, and evidence IDs. Result-plus-decision hashing preserves distinct old/new-project decisions while preventing terminal replay duplicates.
- Pending selection no longer treats any completed attempt as globally terminal; `ReviewService` alone decides reuse from the current canonical input hash.
- Reclassification now performs stored-evidence review before classification, transactionally changes the session and pending candidates, then reviews and gates against the target project. A second-phase failure uses a typed compensation snapshot to restore awaiting state and remove only second-phase knowledge/conflict differences while retaining immutable review attempts and preexisting entities.
- Valid model conflicts create one deterministic open record using the redacted normalized text; terminal replay is idempotent. Hallucinated or incompatible knowledge IDs remain audited blockers and do not crash review.
- Manual edit rejects blank text, restricts `valid_until` to `TASK_STATE`, and requires timezone-aware values.

### Scope boundary

- OpenSpec completion remains `2.8` and `3.1` through `3.9`; `3.10` and `3.11` remain open.
- Tests use temporary synthetic Codex capture data and injected gateways. They do not call a real model, read a real user session path, or reread source JSONL during reclassification.
- No purge, Obsidian, briefing, global `AGENTS.md`, memory, external write, or `.playbook/` change was made.
