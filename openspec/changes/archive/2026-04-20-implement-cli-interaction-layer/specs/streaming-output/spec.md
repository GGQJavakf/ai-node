# 流式输出规范

## ADDED Requirements

### Requirement: 文本流式生成

系统 SHALL 在 AI 生成文本时，采用打字机效果的流式输出。

#### Scenario:
AI 需要生成文本响应。

**Given** AI 需要生成文本响应
**When** AI 开始生成内容
**Then** 文本逐字显示

### Requirement: 流式 API 调用

系统 SHALL 使用流式 API 调用大模型，实现实时响应。

#### Scenario:
用户输入需要 AI 处理的请求。

**Given** 用户输入需要 AI 处理的请求
**When** 系统调用大模型 API
**Then** 使用流式请求模式