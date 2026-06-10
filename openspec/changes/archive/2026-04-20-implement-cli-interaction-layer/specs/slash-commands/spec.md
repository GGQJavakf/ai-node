# 斜杠命令规范

## ADDED Requirements

### Requirement: 系统级快捷命令

系统 SHALL 提供通过斜杠命令快速执行常用操作的能力。

#### Scenario:
用户在 CLI 中输入斜杠命令。

**Given** 用户在 CLI 中输入斜杠命令
**When** 系统解析命令
**Then** 执行对应操作

### Requirement: /list 命令

系统 SHALL 提供 `/list` 命令，表格化展示所有或今日待办任务。

#### Scenario:
用户输入 `/list` 命令。

**Given** 用户输入 `/list`
**When** 系统执行命令
**Then** 显示待办事项列表

### Requirement: /add 命令

系统 SHALL 提供 `/add` 命令，快速新增待办事项。

#### Scenario:
用户输入 `/add` 命令。

**Given** 用户输入 `/add 标题`
**When** 系统解析命令
**Then** 创建新的待办事项

### Requirement: /history 命令

系统 SHALL 提供 `/history` 命令，查看任务流转或会话记录。

#### Scenario:
用户输入 `/history` 命令。

**Given** 用户输入 `/history`
**When** 系统执行命令
**Then** 显示历史记录

### Requirement: /help 命令

系统 SHALL 提供 `/help` 命令，查看可用的系统快捷键。

#### Scenario:
用户输入 `/help` 命令。

**Given** 用户输入 `/help`
**When** 系统执行命令
**Then** 显示命令列表

### Requirement: /exit 命令

系统 SHALL 提供 `/exit` 命令，安全退出并保存数据。

#### Scenario:
用户输入 `/exit` 命令。

**Given** 用户输入 `/exit`
**When** 系统执行命令
**Then** 保存当前状态并退出应用