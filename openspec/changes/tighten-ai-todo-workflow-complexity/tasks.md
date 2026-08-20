## 1. Baseline and Guardrails

- [ ] 1.1 Record the eight C901@10 findings and the focused 118-test compatibility baseline.
- [ ] 1.2 Extend the manifest to the three owner modules and split the gate into manifest C901@10 and package C901@15 scans with suppression resistance.
- [ ] 1.3 Add characterization for import/preview equivalence and writes, skip-copy precedence, CLI exact output, ordering, failure containment, and monkeypatch seams.

## 2. Codex Report Workflow

- [ ] 2.1 Extract shared Codex entry classification and preparation without changing collision, identity, status, count, detail, or ordering behavior.
- [ ] 2.2 Keep preview zero-write and import persistence, merge audit, and completion evidence explicit and exact.
- [ ] 2.3 Run focused workflow import/preview regressions and confirm `services.py` passes C901@10.

## 3. Resume Skip Mapping

- [ ] 3.1 Replace the parallel skip progress and next-action ladders with one ordered mapping while preserving raw and normalized matching semantics.
- [ ] 3.2 Run overlap, fallback, blocked/completed de-duplication, targeted, exclusion, and dry-run regressions and confirm `codex_resume.py` passes C901@10.

## 4. CLI Orchestration

- [ ] 4.1 Extract daily-triage loading and rendering owners while preserving repository/evidence failure containment and row order.
- [ ] 4.2 Extract Codex report row and completed-signal formatting while preserving exact text and entry order.
- [ ] 4.3 Extract resume option, exclusion, and index resolution while preserving validation precedence, failure text, and runtime monkeypatch seams.
- [ ] 4.4 Extract work-item source, merge-audit, conflict, and evidence detail appenders while preserving exact rendering.
- [ ] 4.5 Run command-surface, personal-assistant, workflow CLI, resume CLI, and failure regressions and confirm `cli.py` passes C901@10.

## 5. Verification and Delivery

- [ ] 5.1 Run focused and full branch-aware pytest, Ruff, both C901 gates, focused mypy, compileall, architecture checks, and diff check.
- [ ] 5.2 Run package build/Twine/isolated-wheel smoke, UTF-8/GBK command smoke, and strict validation for this change and all OpenSpec artifacts.
- [ ] 5.3 Run OCR delegate preview/rule over the exact diff and one fresh compatibility review; resolve material findings and account for exclusions.
- [ ] 5.4 Publish responsibility-sized commits to a Draft PR with exact evidence, verify remote CI on the immutable head, then perform authorized Ready/merge and archive readback.
