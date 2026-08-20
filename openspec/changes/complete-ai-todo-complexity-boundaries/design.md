## Context

The ai-todo package has five functions above McCabe 15: resume candidate selection plus four CLI routing, listing, work-item, and triage helpers. These paths sit on public interactive commands and persisted workflow data, so the work is a behavior-preserving decomposition rather than a feature change. The current focused baseline is 84 passing tests across command surface, personal-assistant behavior, workflow CLI, and Codex thread resume.

## Goals / Non-Goals

**Goals:**

- Reduce every `src/ai_todo_assistant` function to McCabe complexity 15 or below.
- Give parsing, dispatch, selection, rendering, and triage decisions small named owners.
- Preserve every existing command spelling, alias, argument split, return type, text/table output, ordering, side effect, exception translation, resume exclusion, and skip-precedence rule.
- Add a repeatable complexity gate and focused regression evidence for the five affected paths.

**Non-Goals:**

- Changing CLI UX, help text, persistence schemas, work-item state transitions, Codex report formats, resume execution, or exclusion policy.
- Reducing functions already at or below 15 in this phase.
- Introducing a command framework, dependency, plugin system, or cross-package abstraction.
- Rewriting unrelated legacy agent, reactor, LLM, GUI, settings, or AgentRetro code.

## Decisions

### Characterize branch precedence before decomposition

Add focused cases for alias and unknown-command routing, list/source combinations, work-command validation and exception paths, triage-reason precedence, and targeted/bulk resume skip de-duplication before moving branches. The 84-test baseline remains the primary compatibility suite.

Alternative considered: rely only on the current full suite. Rejected because a green suite can miss the ordering between overlapping triage or skip conditions.

### Keep helpers inside their current owning modules

Extract private functions and small methods in `presentation.cli` and `application.workflow.codex_resume`. Keep the existing facade methods and signatures in place, and resolve bound handlers at call time so historical instance monkeypatch seams continue to work.

Alternative considered: add a new command-router package. Rejected because two modules already own the behavior and a new cross-package layer would increase dependency and compatibility risk.

### Use explicit dispatch and selection phases

The slash facade will separate tokenization, command lookup, argument-shape adaptation, and invocation. List and work handlers will separate validation/selection from rendering or mutation. Resume selection will separate unfinished-entry evaluation from non-resumeable bucket reporting. Triage reasoning will use named precedence steps rather than one branching chain.

Alternative considered: suppress `C901` or split branches into anonymous lambdas. Rejected because suppression hides regressions and anonymous routing obscures ownership and debugging.

### Gate the full ai-todo package at 15

Add a dedicated ai-todo manifest for the affected owner modules and a script that validates the manifest before scanning both it and the full `src/ai_todo_assistant` tree with Ruff `C901` at 15. No per-function suppression is allowed.

Alternative considered: scan only the two edited files. Rejected because a future hotspot could be introduced elsewhere without detection after this baseline is cleared.

### Deliver in responsibility-sized commits

Commit planning/guardrails, resume selection, and CLI decomposition separately. Run focused checks after each responsibility, then run full regression, branch coverage, Ruff, mypy, compileall, package/Twine/isolated-wheel, strict OpenSpec, Windows encoding smoke, and OCR review before remote delivery.

## Risks / Trade-offs

- [Risk] Declarative routing can bind stale methods and break tests or integrations that monkeypatch an instance handler. → Mitigation: resolve handler names or bound methods inside each call and retain all facade methods.
- [Risk] Splitting list/work logic can alter validation precedence, table ordering, or exact Chinese output. → Mitigation: characterize mixed-source, empty, invalid, exception, and ordering paths and compare rendered output.
- [Risk] Resume helper extraction can duplicate or reorder skipped entries. → Mitigation: preserve unfinished-before-blocked/completed traversal, denied precedence, manual exclusion behavior, target filtering, and de-duplication tests.
- [Risk] Triage helper extraction can change the first matching reason. → Mitigation: encode current precedence explicitly and add overlapping-condition regressions.
- [Trade-off] A package-wide ceiling of 15 leaves functions between 11 and 15 for later work. → This phase first removes all current violations at the established ceiling without mixing a second, broader cleanup.
