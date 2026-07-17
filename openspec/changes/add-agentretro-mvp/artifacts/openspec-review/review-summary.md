# OpenSpec 审核摘要

## 1. 结论

APPROVE

`stage_fingerprint`: `agentretro-mvp-revised-spec-review-pending:v2:sha256:3961eaa07d052542f894961587534c908bba2cc33ef82b69496616186ecbfaae`

上一版指纹 `agentretro-mvp-design-approved:v1:sha256:abba15f8d4b52001977b22ceb264e2edfca55ed4ff99a52993c03e491af35d89` 的 `REVISE` 结论所列七项 `MAJOR` 和一项 `MINOR` 已全部形成单义、可观察、可测试的规格与任务。当前 OpenSpec 足以支撑实现、验证和归档；本轮边界仍是设计文档，不进入业务代码、真实 Obsidian、全局 AGENTS 或 Codex 原生记忆修改。

## 2. 变更概述

该 change 在完整保留 `ai-todo` 的前提下，新增独立 `retro` CLI，把显式选择的已完成 Codex 会话转成带证据的 `RULE`、`LESSON`、`TASK_STATE`。修订稿补齐了自动投影触发与失败恢复、敏感内容全介质清除、项目映射和模型审核重试、确定性 brief、规范的全局 AGENTS 接入以及性能上限，已消除实现者自行选择关键语义的空间。

## 3. 功能范围

### 范围内

- 显式、幂等、有界地捕获一个已完成 Codex 会话，执行项目路由、最小证据留存和双重脱敏。
- 两阶段提取/审核、固定阈值与硬门禁、人工生命周期操作、冲突、重试、过期、归档、敏感清除和审计。
- SQLite 权威存储、同命令 Obsidian 投影、受控摘要/索引/日志、事务日志、备份、回滚、外部编辑协调和深度合并确认。
- 确定性 `retro brief`、`retro doctor`，以及只面向 `<effective-codex-home>/AGENTS.md` 的预览/应用/移除集成。

### 范围外

- 不修改现有 Todo/WorkItem 业务语义，不迁移或共享 `data/todos.db` 业务表。
- 不增加 hook、watcher、后台服务、Web/GUI/MCP、向量数据库或其它 Agent 数据源。
- 不自动深度修改用户笔记，不绕过冲突、哈希或精确确认门禁，不修改 Codex 原生 memory 文件或设置。

## 4. 实现范围

- 涉及模块：新增 `src/agent_retro/` 的 domain、application、infrastructure、presentation 分层；仅通过只读适配器复用现有模型配置与 LLM 客户端。
- 数据模型：独立、版本化的用户级 SQLite，覆盖 session、evidence、candidate、review attempt、knowledge、conflict、sync journal、project mapping、purge job 和 audit。
- 接口 / 响应：本地 `retro` CLI；人类输出默认中文，`--json` 使用稳定英文键和枚举；不新增网络 API。
- 认证 / 鉴权 / JWT / filter / audit：认证、JWT、HTTP filter 不适用；凭据不得落盘或进入证据；所有知识、映射、同步和清除动作均审计。
- 迁移 / 兼容 / 回滚：数据库迁移前备份并失败回滚；文件写入采用预览、哈希、备份、同目录替换、回读和恢复；敏感清除经逐项确认后对已确认副本不可逆。

## 5. 审核问题

NONE

## 6. 可保留内容

- 独立产品边界、SQLite 权威与 Obsidian 投影分工、前置脱敏、不可信会话输入、旧知识冲突时继续生效等原设计保持成立。
- 自动投影、清除、AGENTS、映射、重试、brief 和性能契约现已在 proposal、design、spec 和 tasks 中闭合。
- 33 条 requirement、98 个连续且唯一的 scenario 均有稳定 ID，并由分组测试任务和最终覆盖核对任务明确追踪。

## 7. 开发决策

- 是否可以进入开发：OpenSpec 质量门已通过；当前会话仍需遵守“先审阅落盘规格”的人工确认门。
- 进入开发前必须补什么：用户确认本次落盘规格后，按 `writing-plans` 更新详细实施计划并重新核对任务顺序；不需要再补业务选择。
- 可接受的后续事项：实现阶段按场景 ID 生成测试映射证据；任何真实 Obsidian 或全局 AGENTS 写入仍须走规格规定的预览和精确确认。

## Appendix

### 文档与验证证据

- 已读取并复核：`proposal.md`、`tasks.md`、`design.md` 和四份 `specs/**/spec.md`；缺失项：无。
- `openspec validate add-agentretro-mvp --strict`：`Change 'add-agentretro-mvp' is valid`。
- 场景审计：`CR-01..CR-22`、`KR-01..KR-24`、`OS-01..OS-24`、`BR-01..BR-28` 连续、无遗漏、无重复，共 98 条。
- 回归验证：`python -m pytest -q`，`161 passed in 5.80s`。
- 指纹复算：按设计稿、现有详细计划、proposal、design、tasks 和四份 spec 的固定路径顺序，先计算各文件 SHA-256，再对 UTF-8/LF 的 `path<TAB>hash` 清单计算 SHA-256；评审摘要自身不参与哈希。
