## Why

Recent-session validation proved that AgentRetro can complete capture, review, Obsidian projection, and briefing, but common Codex workspace and subagent formats still cause sessions to be misrouted or skipped, while optional-event noise and redundant review input reduce operational reliability. These issues must be fixed before unattended analysis of recent Codex sessions is safe and useful.

## What Changes

- Add an explicit non-Git workspace mapping that routes a configured workspace root and its contained sessions to one logical project without pretending that the workspace is a Git repository.
- Accept a validated Codex parent/child session metadata chain while continuing to reject unrelated, ambiguous, or conflicting repeated metadata.
- Aggregate unsupported optional event warnings by event type and deduplicate identical evidence content without losing traceable source locations.
- Reduce model review input to unique evidence, record every review attempt and duration, and apply bounded retry handling for retryable model failures without lowering review thresholds or weakening schema validation.
- Add isolated regressions and recent-session fixtures for the four observed failure modes.

## Capabilities

### New Capabilities

- `workspace-project-routing`: Explicit, audited routing from a non-Git multi-repository workspace root to one AgentRetro project.
- `codex-session-family-capture`: Conservative capture of validated parent/child Codex session metadata chains.
- `retrospective-ingestion-quality`: Aggregated parser diagnostics and content-level evidence deduplication with traceable source locations.
- `retrospective-review-resilience`: Bounded, observable, idempotent model-review retry over minimal unique evidence.

### Modified Capabilities

None. The existing AgentRetro MVP safety and acceptance requirements remain unchanged; this change adds stricter capabilities around them.

## Impact

- Affected code: AgentRetro project mapping, Codex JSONL discovery/parsing, evidence persistence, model review orchestration, CLI output, and doctor/diagnostic reporting.
- Affected interfaces: `retro project` mapping commands, capture result diagnostics, and review attempt audit output.
- Data and safety: a compatible local database migration may be required for mapping kind, evidence source locations, or review timing metadata; no automatic write to real Obsidian, global AGENTS, Codex native memory, or external services is introduced.
- Dependencies: no new runtime dependency is expected.
