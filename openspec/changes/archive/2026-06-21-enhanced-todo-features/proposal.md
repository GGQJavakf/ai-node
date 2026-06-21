## Why

当前 TodoAgent 待办管理工具功能较为基础，仅支持简单的 CRUD 操作。为了提升用户体验和学习价值，需要增强以下核心能力：(1) 时间维度筛选（今日/本周/本月）；(2) 任务优先级管理；(3) 过期和即将过期任务的视觉区分；(4) 搜索和统计功能；(5) 今日个人助理简报与日计划；(6) 可持久化的用户长期偏好记忆。这些增强功能将使 TodoAgent 从被动待办工具演进为更实用的个人 AI 助手，同时为 Agent 开发学习提供更丰富的案例。

## What Changes

- **新增时间筛选功能**: `/list today`、`/list week`、`/list month` 命令
- **新增状态筛选功能**: `/list pending`、`/list completed`、`/list overdue`、`/list upcoming` 命令
- **新增优先级系统**: 支持 high/medium/low 三级优先级，添加时可指定
- **新增颜色视觉区分**: 过期任务显示红色，即将到期显示橙色，已完成显示灰色
- **新增搜索功能**: `/search <关键词>` 命令搜索任务标题和描述
- **新增统计功能**: `/stats` 命令显示任务统计和完成率
- **新增清理功能**: `/clear` 命令清除已完成任务
- **增强更新命令**: `/update` 支持更新标题、截止时间、优先级
- **新增今日简报**: `/today` 聚合今日任务、过期任务、即将到期任务和高优先级任务
- **新增日计划**: `/plan day` 按过期状态、优先级和截止时间生成今日计划
- **新增长期偏好记忆**: `/preferences`、`/remember`、`/forget` 管理用户偏好，Agent 可通过工具读写这些偏好
- **修复单参数命令解析**: `/add <标题>`、`/search <关键词>`、`/toggle <ID>`、`/delete <ID>` 正确读取首个参数

## Capabilities

### New Capabilities
- `time-based-filtering`: 按时间维度（今日/本周/本月）筛选待办事项
- `priority-management`: 任务优先级管理（高/中/低三级）
- `visual-status-indicators`: 基于状态的颜色视觉区分（过期/即将到期/正常/已完成）
- `task-search`: 关键词搜索待办事项
- `task-statistics`: 任务统计和完成率分析
- `completed-task-cleanup`: 已完成任务批量清理
- `personal-assistant-planning`: 今日个人助理简报与日计划
- `persistent-preferences`: 用户长期偏好记忆

### Modified Capabilities
- `cli-interaction`: 扩展斜杠命令支持，新增多个子命令和参数

## Impact

- **domain/models.py**: 新增 `priority` 字段与过期判断能力
- **application/ports/todo_repository.py**: 明确仓储端口，包含待办查询和长期偏好读写方法
- **infrastructure/persistence/sqlite_todo_repository.py**: 默认 SQLite 存储，新增待办查询、统计、清理和 `assistant_preferences` 表
- **infrastructure/persistence/json_todo_repository.py**: 保留 JSON 兼容后端，偏好写入 sidecar `*.preferences.json`
- **application/agent/tool_models.py / tool_definitions.py / tool_executor.py**: 扩展工具 schema、工具定义和执行器，新增偏好记忆工具
- **application/agent/core.py**: 系统提示注入当前待办和长期偏好
- **presentation/cli.py**: 新增 `/today`, `/plan day`, `/preferences`, `/remember`, `/forget`，修复单参数命令解析
- **tests/test_personal_assistant_features.py**: 覆盖本轮个人助手能力和 CLI 参数解析回归
