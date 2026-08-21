## Context

The previous maintainability change established an ai-todo package ceiling of C901@15. A current C901@10 scan identifies exactly eight remaining findings in three related owner modules. They are duplication- and orchestration-heavy rather than algorithmically complex, so named private owners can reduce branching while preserving behavior.

## Goals / Non-Goals

**Goals:**

- Make every function in the three declared owner modules pass C901@10 without suppressions.
- Preserve Codex import/preview result counts, detail order, status transitions, merge audits, evidence, and preview zero-write behavior.
- Preserve ordered resume-skip progress and next-action copy.
- Preserve daily-triage, Codex report, resume/exclusion/index resolution, and work-item detail output and failure handling.

**Non-Goals:**

- Changing public commands, signatures, storage schema, dependencies, or product copy.
- Tightening the whole ai-todo package below 15 in this change.
- Refactoring AgentRetro complexity findings.

## Decisions

### Split the gate into a target ceiling and package ceiling

The manifest names `codex_resume.py`, `services.py`, and `cli.py`. The gate runs those files at C901@10, then retains the full `src/ai_todo_assistant` scan at C901@15. Both invocations use `--ignore-noqa`, so neither per-function suppressions nor a weaker package scan can bypass the declared boundary.

### Prepare a Codex entry once, then apply or preview it

A private preparation owner will resolve source identity, collision classification, status transition, details, and an in-memory item. Import will apply persistence, merge audit, and completion evidence after preparation; preview will return the prepared clone without writes. This keeps the shared decision path identical while leaving side effects explicit at the service boundary.

### Use one ordered resume-skip mapping

A declarative, first-match mapping will associate each existing reason condition with both progress and next-action copy. Conditions that intentionally inspect raw Chinese text remain distinct from lower-cased English checks, and fallback behavior remains unchanged.

### Extract CLI owners around existing seams

Daily triage separates source/evidence loading from row rendering. Codex report output separates report loading, entry formatting, and completed-signal formatting. Resume routing separates option parsing and exclusion/index resolution from execution. Work-item detail rendering delegates source identities, merge audit, conflicts, and evidence to focused appenders. Existing public handlers and runtime lookup of patchable instance methods remain intact.

### Deliver in responsibility-sized commits

OpenSpec and guardrails, workflow services, resume mapping, CLI extraction, and verification evidence remain separable. The exact branch head is reviewed locally, pushed as a Draft PR, validated remotely, then marked Ready and merged only when the immutable head is green.

## Risks / Trade-offs

- Shared preparation could accidentally move import-only side effects into preview. Characterization will compare repository writes and result payloads for both paths.
- Declarative mapping could change first-match precedence. Ordered overlap cases will pin the existing output pair.
- CLI helper extraction could change broad versus typed exception containment or output ordering. Focused failure and exact-text tests will pin both.
- A two-level complexity gate is slightly more configuration, but it enables gradual ratcheting without destabilizing unrelated owners.

## Verification

- Focused workflow, command-surface, personal-assistant, and Codex-resume tests.
- Architecture and gate regressions, including suppression resistance and both thresholds.
- Full pytest with branch-aware coverage for the three owner modules.
- Ruff, C901@10 target scan, C901@15 package scan, focused mypy, compileall, and diff check.
- UTF-8/GBK smoke, build/Twine/isolated-wheel smoke, strict OpenSpec validation, OCR delegate, and one fresh independent compatibility review.
