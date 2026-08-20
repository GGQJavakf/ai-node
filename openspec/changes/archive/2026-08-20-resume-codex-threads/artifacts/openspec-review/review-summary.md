# OpenSpec Review Summary

## 1. Verdict

APPROVE_WITH_NOTES

## 2. Change in One Paragraph

This change adds explicit Codex thread resume support on top of the existing report ingestion flow. It is suitable to enter development because the specs define strict eligibility rules, dry-run behavior, skip reasons, Evidence recording, and a fail-closed injectable resume client boundary instead of coupling `ai-node` to Codex internal storage.

## 3. Functional Scope

### In Scope

- Select resume candidates from the latest Codex task report.
- Add `/r`/`/resume` with preview, indexed targeting, bulk resume, and unavailable-client reporting.
- Record non-dry-run resume attempts as local Evidence on Codex WorkItems.
- Allow `/sync watch --resume` to run sync and then resume only safe candidates.

### Out of Scope

- Direct Codex internal session storage inspection.
- Resuming blocked, completed, ambiguous, or user-input-required threads.
- Redmine/GitLab/MR writes, time logging, merge, push, publish, deploy, or production changes.
- Persistent OS scheduler setup or claims that Codex app integration exists without a configured resume client.

## 4. Implementation Scope

- 涉及模块：`src/ai_todo_assistant/application/workflow/` for a resume service and client protocol; `src/ai_todo_assistant/presentation/cli.py` for `/r`/`/resume` and `/sync watch --resume`; `src/ai_todo_assistant/application/workflow/sync_watch.py` if the trigger report needs an optional resume section; README/help/completion text.
- 数据模型：不需要迁移；复用 existing `WorkItem` and `Evidence` storage, creating a Codex WorkItem only when an attempted resume needs a local evidence target.
- 接口 / 响应：new `/r`, `/r <序号>`, `/r all`, `/r skip`, `/r unskip`; extended `/sync watch --resume`; existing `/sync`, `/sync watch`, `/codex tasks`, `/list`, `/next`, and `/review` remain compatible.
- 认证 / 鉴权 / JWT / filter / audit：N/A for web auth; local audit is Evidence recording. Actual message sending must stay behind an injected/configured Codex resume client.
- 迁移 / 兼容 / 回滚：additive local service and CLI paths only; rollback is removing the new command path and service. Existing WorkItems/Evidence remain readable.

## 5. Review Findings

| Severity | Issue | Impact | Recommendation |
|---|---|---|---|
| MINOR | The MVP may ship with an unavailable default client. | Users can see safe candidate selection but cannot actually resume threads until a bridge/client is configured. | Make CLI output explicit and keep tests focused on the injectable client contract; wire a real Codex app bridge in a separate change if needed. |

## 6. What Already Looks Good

- `openspec validate resume-codex-threads --strict` passed.
- The specs define testable eligibility and skip behavior before implementation.
- Dry-run and unavailable-client behavior fail closed.
- External-write boundaries are explicit and limited to the configured Codex resume client.
- Task coverage includes service tests, CLI tests, watch integration, help text, and full regression.

## 7. Decision

- 是否可以进入开发：可以，带注意事项。
- 进入开发前必须补什么：无阻塞项。
- 可接受的后续事项：如果需要 `ai-node` 在当前 Codex Desktop 中真正发送 thread messages，需要另接 Codex app bridge 或 automation adapter；本 change 先交付可测试的 service/client seam and safe command surface.
