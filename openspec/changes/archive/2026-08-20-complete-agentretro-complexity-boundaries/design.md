## Context

The first complexity change established stable public facades, a declared manifest, a Ruff C901 ceiling of 15, architecture checks, and broad compatibility evidence. On `main@d5b083f2f90e16cbd7b31a3024b5adb541400ac6`, a repository scan still reports six AgentRetro violations: `BriefService.build` (18), `MergePlanner.plan` (20), `CodexGuidance._execute` (23), `CodexSessionSource._parse` (25), `_header_value_end` (16), and `run_review_command` (23).

These functions sit on different trust boundaries. Session parsing and redaction process untrusted local content; guidance execution performs backup-first filesystem changes; brief and merge planning enforce budgets, deadlines, ordering, and path constraints; review commands expose stable CLI outcomes. The work therefore completes the existing maintainability capability without combining it with product behavior or the separate ai-todo CLI hotspots.

## Goals / Non-Goals

**Goals:**

- Make a full `src/agent_retro` C901 scan pass at the established ceiling of 15 without suppressions.
- Preserve public constructors/imports, command syntax, response envelopes, plan/session identity, budgets, deadlines, ordering, path containment, redaction, backup/rollback, persistence, and recovery behavior.
- Extend the existing manifest and architecture test so every remaining affected facade and any newly imported private collaborator is measured.
- Keep file reads, clocks, gateways, repositories, backups, replacements, and renderers owned by the same orchestration boundary; extracted helpers are deterministic or receive effects explicitly.
- Add focused security/performance characterization for session bounds and sensitive-header scanning before relying on the full suite.

**Non-Goals:**

- No new capture, brief, merge, review, or Codex integration feature.
- No output-field, exit-code, exception-policy, redaction-policy, path-policy, timeout, budget, persisted-format, SQLite, vault, or dependency change.
- No repository-wide threshold reduction below 15 and no refactor of the five remaining ai-todo C901 findings.
- No parser framework, generic command bus, model abstraction, or broad module/package reorganization.

## Decisions

### Reuse one complete AgentRetro complexity boundary

The existing manifest remains the CI source of truth and is extended with the six affected modules plus any private modules created by this change. A full AgentRetro C901 scan becomes the characterization oracle for this phase, while the architecture test continues to reject a private collaborator imported by a covered module but omitted from the manifest.

Alternative considered: create a second manifest for phase two. Rejected because two overlapping ownership lists would allow drift and make “all AgentRetro hotspots complete” harder to prove.

### Split at trust and effect boundaries

`BriefService` and `MergePlanner` retain deadline/budget and repository/gateway orchestration while pure selection, validation, and result assembly steps become named helpers. `CodexSessionSource` retains bounded file access and discovery identity while event decoding and metadata assembly are separated. `CodexGuidance` retains the backup/replace/restore transaction while precondition, target-state, and result calculations are decomposed. Review presentation retains service calls while command-family outcome shaping is separated.

Alternative considered: move each large function wholesale into a new module. Rejected because that would only relocate complexity and obscure ownership of clocks, files, repositories, and rollback.

### Preserve the redaction scanner and prove its cost bound

Sensitive-header parsing remains a single-pass scanner with explicit quote, escape, obs-fold, flattened-header, and HTTP-token state. Complexity is reduced through small state predicates and transition helpers rather than a broad regex rewrite. Existing credential classes remain fail-closed, non-sensitive `X-*` headers remain unchanged, repeated redaction remains idempotent, and long whitespace/header inputs receive deterministic bounded-work assertions.

Alternative considered: replace the scanner with one or more regular expressions. Rejected because prior edge cases include quoted delimiters, folded schemes, Set-Cookie attributes, flattened headers, and adversarial whitespace where regex backtracking or over-redaction is difficult to audit.

### Characterize each boundary before and after extraction

Focused suites cover brief budgets/deadlines and stale filtering; merge path/limit/deadline/tamper behavior; Codex session size/count/deadline/encoding/symlink behavior; guidance preview/apply/remove/backup/rollback; redaction component and capture-to-model/storage flow; review commands, Unicode/GBK, JSON, retry, and projection outcomes. The full branch-coverage, package, strict OpenSpec, Ruff, mypy, compile, and OCR gates remain required.

### Keep rollback commit-granular

The implementation is divided into characterization/manifest, brief and merge planning, session parsing and redaction, guidance execution and review presentation, and final verification. No stored representation changes, so rollback is a normal revert of the affected refactor commit.

## Risks / Trade-offs

- [Session helper extraction changes which records count toward limits or identity] -> Preserve source order and hashing inputs exactly; test malformed, oversized, truncated, symlinked, and mixed-encoding sessions plus replay identity.
- [Redaction refactor leaks or over-redacts authentication material] -> Keep fail-closed defaults and add end-to-end raw-byte absence, idempotency, folded/flattened header, quote/escape, and bounded-work regressions.
- [Guidance decomposition changes write/backup/rollback ordering] -> Keep effect ordering in `_execute`, retain injected replace and public monkeypatch seams, and test failure at backup, replace, readback, and restore stages.
- [Brief or merge planning changes deterministic output] -> Compare stable rendered output, plan IDs, ordering, budgets, deadlines, file limits, and gateway inputs against existing characterization suites.
- [Review routing changes CLI semantics] -> Assert every action's exit code, JSON/human envelope, retryability, projection warning, and recovery command.
- [New helpers merely move complexity] -> Measure every covered facade and private collaborator and require the full AgentRetro scan to report zero C901 findings at 15.

## Migration Plan

1. Record the six-function baseline and extend characterization plus the shared manifest in a failing state.
2. Decompose brief composition and merge planning, then run their focused deterministic suites.
3. Decompose session parsing and sensitive-header scanning, then run security, bounds, performance, and capture-flow suites.
4. Decompose guidance execution and review presentation, then run filesystem rollback and CLI/encoding suites.
5. Run the full local gate matrix, OCR delegation with explicit excluded-file accounting, publish a Draft PR, and merge only after all remote matrices pass.

Rollback is commit-level revert. No data, schema, vault, or credential migration is introduced.

## Open Questions

None. The six hotspots, ceiling, compatibility boundary, validation matrix, excluded ai-todo scope, and rollback strategy are fixed for this change.
