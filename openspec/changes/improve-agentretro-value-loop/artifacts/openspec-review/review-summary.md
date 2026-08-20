# OpenSpec 审核摘要

## 1. 结论

APPROVE

## 2. 变更概述

该 change 在合并后的 AgentRetro 主线上补齐项目引用解析、身份绑定的近期会话批量捕获、可执行的空 brief 诊断，以及项目/awaiting 双视角 review inbox。原二审的计划身份、worktree 路由、积压可见性、失败语义、归档依赖、边界字段和命令格式缺口均已收敛，可以进入测试先行实现。

## 3. 功能范围

### 范围内

- canonical ID、最长 workspace 路径、Git worktree remote 和无凭据 remote 的统一 fail-closed 项目解析。
- 绑定 count、有效上限、session/source、resolution、canonical project、mapping 和 reuse identity 的 preview/apply 批量捕获。
- 明确停止于首个失败、保留既有单会话提交、四类互斥结果及重新 preview 的恢复路径。
- bounded project inbox、awaiting routing inbox、有效过期汇总和内容安全的空 brief 恢复命令。

### 范围外

- 不安装 hook、watcher、计划任务或后台捕获。
- 不自动或批量接受知识，不放宽模型审核门禁。
- 不新增数据库 schema、外部依赖、全文会话存储或隐式 Obsidian 写入。
- 本 change 不承担最后的 SQLite/CLI/sync/merge/purge 复杂度拆分。

## 4. 实现范围

- 涉及模块：CLI parser/dispatch、project mapping resolver、Codex source discovery、capture planner/service、brief/review application models、repository aggregate queries、README 与 scenario registry。
- 数据模型：新增内存中的版本化 capture plan 与安全 summary DTO；不迁移 SQLite schema，不改变既有会话/知识记录格式。
- 接口 / 响应：新增 recent dry-run/apply、review inbox/awaiting 和 empty-brief JSON 字段；旧单会话、review list/show/lifecycle、canonical-ID brief 保持兼容。
- 安全 / 审计：preview 和 brief/inbox 均只读；apply 复用既有单会话事务与审计；输出只含安全 ID、计数、状态和静态命令，不含正文、路径、remote、模型错误或凭据。
- 迁移 / 兼容 / 回滚：无数据迁移；覆盖 Windows UTF-8/GBK；实现可通过 revert 回滚，已显式提交的会话记录保留且幂等。

## 5. 审核问题

NONE

## 6. 可保留内容

- proposal、三份 delta spec、design 与 tasks 范围一致，27 个 scenario 均有实现或测试任务覆盖。
- 现有显式捕获、脱敏、保守审核、SQLite 权威、只读 brief/inbox 和单会话事务边界均被保留。
- closeout 已固定 `add-agentretro-mvp` → `harden-recent-session-capture` → `improve-agentretro-value-loop` 的归档与逐步严格校验顺序。

## 7. 开发决策

- 是否可以进入开发：是。
- 进入开发前必须补什么：无；从 tasks 1.1 的失败用例开始，按任务顺序测试先行实现。
- 可接受的后续事项：复杂度拆分保持在本 change 归档和 CI 治理完成之后，不混入当前实现。

## Appendix

### 覆盖与校验证据

- requirement-to-task 核对：6 个 requirement、27 个 scenario，缺失 0。
- `openspec validate improve-agentretro-value-loop --strict`：通过。
- `openspec validate --all --strict`：27 passed，0 failed。
