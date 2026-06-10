# 终端 UI 规范

## ADDED Requirements

### Requirement: Markdown 渲染

系统 SHALL 在终端中渲染 Markdown 格式的内容。

#### Scenario:
用户请求显示格式化内容。

**Given** 用户请求显示格式化内容
**When** 系统生成 Markdown 内容
**Then** 终端中正确渲染 Markdown 格式

### Requirement: 美化终端输出

系统 SHALL 使用 rich 库美化终端输出，包括颜色、样式和布局。

#### Scenario:
系统需要显示待办事项列表。

**Given** 系统需要显示待办事项列表
**When** 系统生成输出
**Then** 显示彩色的状态标识

### Requirement: Thinking 状态动画

系统 SHALL 在 AI 思考或请求大模型 API 时，显示动态加载动画。

#### Scenario:
用户输入需要 AI 处理的命令。

**Given** 用户输入需要 AI 处理的命令
**When** 系统调用 AI 服务
**Then** 显示加载动画