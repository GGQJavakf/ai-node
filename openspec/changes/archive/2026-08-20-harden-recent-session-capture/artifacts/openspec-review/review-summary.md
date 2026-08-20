# OpenSpec 审核摘要

## 1. 结论

APPROVE

stage_fingerprint: `agentretro-session-hardening:openspec:v1:sha256:5fdca364e10b3b3f938a3720ffa95f6d2a39563a395131ad630648b7a194ce95`

## 2. 变更概述

该变更修复近期 Codex 会话实测暴露的四个可靠性缺口：非 Git 工作区无法自动归类、合法子代理元数据链被拒、大量可选事件和重复证据形成噪声、结构化模型审核需要人工再次执行。规格保持现有 fail-closed、严格 Schema、入库阈值、Obsidian 写入边界和幂等约束，可直接支撑开发和测试。

## 3. 功能范围

### 范围内

- 用户显式建立非 Git 工作区到逻辑项目的映射，并按规范化路径最长前缀匹配。
- 仅接受可验证的子到父 `session_meta` 链，继续拒绝身份冲突或不相关重复元数据。
- 按事件类型聚合未知可选事件告警，按类型与内容哈希去重证据并保留全部来源定位。
- 对结构化响应修复耗尽进行一次受控新尝试，并记录稳定错误分类和耗时。
- 数据库兼容迁移、CLI 兼容、回归场景和隔离近期会话验证。

### 范围外

- 不自动扫描目录或推测工作区所属项目。
- 不放宽 128 MiB 会话安全上限，不在本变更处理超大文件分块。
- 不降低自动入库阈值，不跳过严格 Schema、证据门和冲突门。
- 不修改真实 Obsidian、全局 AGENTS、Codex 原生记忆或外部系统。

## 4. 实现范围

- 涉及模块：`project_mapping`、`codex_sessions`、capture/review services、review contracts、SQLite repository、CLI 和 AgentRetro 测试。
- 数据模型：增加映射类型、证据多来源定位、审核耗时与错误分类；通过 backup-first 加法迁移和回填保持旧数据可读。
- 接口 / 响应：新增显式 `map-workspace` 入口；mapping 列表和审核尝试输出增加稳定字段，保留现有 Git mapping 命令。
- 认证 / 鉴权 / 安全：不新增凭据；模型错误只保存稳定分类，不保存原始异常或敏感内容；项目冲突继续 fail closed。
- 迁移 / 兼容 / 回滚：版本化 runtime 切换前完成迁移与测试；代码回滚使用旧 runtime，数据回滚使用迁移前备份。

## 5. 审核问题

NONE

## 6. 可保留内容

- 四个 capability 与 proposal、design、tasks 一一对应，requirement 和 scenario 均有可观察结果。
- 任务覆盖测试先行、迁移、四项实现、全量验证、真实隔离 smoke 和独立复核。
- 父子身份链、映射冲突、自动重试和真实知识库写入边界均采用保守策略。
- `openspec validate harden-recent-session-capture --strict` 已通过。

## 7. 开发决策

- 是否可以进入开发：是。
- 进入开发前必须补什么：无需补充；先按任务 1.x 写失败回归，再进入实现。
- 可接受的后续事项：超过 128 MiB 的会话流式/分块读取保持独立后续变更。

## Appendix

### 覆盖判断

- `workspace-project-routing` -> tasks 1.2、2.1-2.3、3.1-3.3、6.1-6.4。
- `codex-session-family-capture` -> tasks 1.1、1.3、4.1、6.1-6.4。
- `retrospective-ingestion-quality` -> tasks 1.4、2.1-2.3、4.2-4.4、6.1-6.4。
- `retrospective-review-resilience` -> tasks 1.5、2.1-2.3、5.1-5.3、6.1-6.4。
