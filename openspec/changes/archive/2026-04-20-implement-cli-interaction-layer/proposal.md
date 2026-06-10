## Why

当前AI待办管家工具缺少用户友好的命令行界面，无法提供会话式体验和流式输出，影响用户交互体验和开发学习效果。实现CLI交互层是项目阶段一的核心目标，完全参考Claude Code的界面设计。

## What Changes

- 引入 `prompt_toolkit` 库实现会话式REPL和基本命令交互
- 引入 `rich` 库实现Markdown渲染、语法高亮和美化终端输出
- 实现流式输出和Thinking状态动画，提供更好的用户体验
- 添加斜杠命令支持：`/list`、`/add`、`/help`、`/exit`
- 统一Agent实现，以 `agent_core.py` 为唯一入口
- 更新 `requirements.txt` 添加必要依赖

## Capabilities

### New Capabilities
- `cli-interaction`: 会话式命令行交互，参考Claude Code界面
- `terminal-ui`: 美化终端输出，包括Markdown渲染和状态动画
- `slash-commands`: 系统级快捷命令支持
- `streaming-output`: AI思考和生成的流式输出

### Modified Capabilities
- `agent-core`: 集成CLI交互层，提供更友好的用户接口

## Impact

- **文件影响**: 
  - 新增 `todo_cli.py` 作为CLI交互层入口
  - 更新 `requirements.txt` 添加依赖
  - 优化 `agent_core.py` 以支持流式输出
- **依赖影响**: 
  - 添加 `prompt_toolkit>=3.0.0`
  - 添加 `rich>=13.0.0`
- **用户体验**: 提供Claude Code级别的命令行交互体验，增强学习和使用体验

## Notes

- 自定义配置、多语言支持暂时不考虑
- 完全参考Claude Code的界面设计和交互方式