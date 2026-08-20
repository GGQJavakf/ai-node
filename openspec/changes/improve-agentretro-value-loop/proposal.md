## Why

AgentRetro is operationally healthy but still produces too little day-to-day value: users can pass a mapped worktree path and silently miss project knowledge, an empty brief does not explain how to recover, capture is limited to one explicitly selected session, and pending or unrouted review work is easy to leave unattended. The next change should close that usage loop without weakening explicit capture, review, redaction, or no-background-write safety boundaries.

## What Changes

- Resolve `retro brief --project` and project-filtered inbox input through active project mappings so a canonical project ID, mapped Git/workspace path, worktree remote, or normalized credential-free remote selects the same project; reject unknown, multiple, or conflicting identities instead of rendering a misleading empty result.
- Add actionable empty-brief diagnostics that summarize eligible, expired, pending-review, and captured-session counts without exposing candidate, evidence, path, model-error, or credential content.
- Add `retro capture --recent <count> --dry-run` as a bounded, newest-first preview and `retro capture --recent <count> --apply <plan-id>` as an explicit batch capture. Bind the plan to the ordered session/source/mapping/reuse identities and the effective limits, revalidate it before the first write, and report partial failure without claiming batch atomicity.
- Add `retro review inbox` as a concise project-aware queue showing bounded counts, age, status, exact next commands, and a safe `awaiting` routing bucket.
- Report expired `TASK_STATE` consistently in read-only brief and inbox summaries without mutating SQLite, audit, projection, or Obsidian state.
- Preserve single-session capture, manual review decisions, fail-closed project routing, redaction, evidence provenance, and projection confirmation behavior.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `codex-session-retrospective`: Add bounded, preview-first recent-session batch capture while retaining explicit invocation and fail-closed routing.
- `retrospective-knowledge-review`: Add a concise review inbox, an awaiting-routing view, and consistent effective task-state expiry reporting.
- `retrospective-briefing`: Resolve mapped project references and return actionable diagnostics when no eligible knowledge is selected.

## Impact

- Affected CLI: `retro capture`, `retro review`, and `retro brief`.
- Affected application services: session discovery/capture planning, project-reference resolution, review summaries, and brief diagnostics.
- Affected persistence ports: read-only aggregate counts and bounded session/candidate queries; no schema migration and no new external-system write.
- Affected tests and documentation: CLI, subprocess, scenario coverage, security/redaction, README first-use flow, and OpenSpec scenario mappings.
- Planning dependency: this delta layers on the merged implementations described by `add-agentretro-mvp` and `harden-recent-session-capture`; closeout archives those completed changes before this change.
- No new runtime dependency and no automatic hook, watcher, background task, implicit capture, or implicit review acceptance.
