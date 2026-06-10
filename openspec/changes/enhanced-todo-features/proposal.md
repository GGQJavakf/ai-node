## Why

当前 TodoAgent 待办管理工具功能较为基础，仅支持简单的 CRUD 操作。为了提升用户体验和学习价值，需要增强以下核心能力：(1) 时间维度筛选（今日/本周/本月）；(2) 任务优先级管理；(3) 过期和即将过期任务的视觉区分；(4) 搜索和统计功能。这些增强功能将使 TodoAgent 成为更实用的个人任务管理工具，同时为 Agent 开发学习提供更丰富的案例。

## What Changes

- **新增时间筛选功能**: `/list today`、`/list week`、`/list month` 命令
- **新增状态筛选功能**: `/list pending`、`/list completed`、`/list overdue`、`/list upcoming` 命令
- **新增优先级系统**: 支持 high/medium/low 三级优先级，添加时可指定
- **新增颜色视觉区分**: 过期任务显示红色，即将到期显示橙色，已完成显示灰色
- **新增搜索功能**: `/search <关键词>` 命令搜索任务标题和描述
- **新增统计功能**: `/stats` 命令显示任务统计和完成率
- **新增清理功能**: `/clear` 命令清除已完成任务
- **增强更新命令**: `/update` 支持更新标题、截止时间、优先级

## Capabilities

### New Capabilities
- `time-based-filtering`: 按时间维度（今日/本周/本月）筛选待办事项
- `priority-management`: 任务优先级管理（高/中/低三级）
- `visual-status-indicators`: 基于状态的颜色视觉区分（过期/即将到期/正常/已完成）
- `task-search`: 关键词搜索待办事项
- `task-statistics`: 任务统计和完成率分析
- `completed-task-cleanup`: 已完成任务批量清理

### Modified Capabilities
- `cli-interaction`: 扩展斜杠命令支持，新增多个子命令和参数

## Impact

- **todo_manager.py**: 新增 `get_today()`, `get_this_week()`, `get_this_month()`, `get_upcoming()`, `search()`, `get_by_priority()` 方法
- **agent_tools.py**: 扩展 `list_todos` 工具支持时间范围和优先级过滤，新增 `search_todos`, `clear_completed` 工具
- **todo_cli.py**: 新增 `/search`, `/stats`, `/clear` 命令，增强 `/list` 和 `/add` 命令，添加颜色输出支持
- **todo.py**: 新增 `priority` 字段支持