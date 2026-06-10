#!/usr/bin/env python3
"""
TODO CLI 交互层
完全参考 Claude Code 的界面设计

════════════════════════════════════════════════════
【学习重点：CLI 交互层设计】

这个模块展示了 Agent 架构中"用户界面层"的核心概念：
1. REPL 循环：Read-Eval-Print Loop，持续接收用户输入
2. 命令解析：区分斜杠命令和自然语言
3. 视觉美化：使用 rich 库进行终端美化
4. 用户体验：命令补全、历史记录、多种退出方式

关键设计原则：
- 清晰的反馈机制
- 优雅的错误处理
- 用户友好的交互方式
════════════════════════════════════════════════════
"""
import sys
import os
from datetime import datetime

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import WordCompleter, Completer, Completion
    from prompt_toolkit.styles import Style
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    PROMPT_TOOLKIT_AVAILABLE = False

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Spinner
from rich.text import Text
from rich.table import Table
from rich.prompt import Prompt

from ai_todo_assistant.infrastructure.persistence import TodoManager
from ai_todo_assistant.application.agent import AgentCore
from ai_todo_assistant.infrastructure.config import load_settings


# ─────────────────────────────────────────────────────────────────
# 【学习重点：终端颜色配置】
# 
# 使用 Rich 库实现终端颜色输出，不同状态用不同颜色区分：
# - 已完成：灰色
# - 未完成：默认颜色
# - 过期：红色
# - 即将过期：橙色
# - 高优先级：红色标记
# - 中优先级：黄色标记
# - 低优先级：绿色标记
# ─────────────────────────────────────────────────────────────────

class CommandCompleter(Completer):
    """命令自动补全器"""
    
    def __init__(self):
        self.commands = {
            '/list': '查看待办事项列表',
            '/list today': '查看今天的待办',
            '/list week': '查看本周的待办',
            '/list month': '查看本月的待办',
            '/list pending': '查看未完成的待办',
            '/list completed': '查看已完成的待办',
            '/list overdue': '查看过期的待办',
            '/list upcoming': '查看即将到期的待办',
            '/add': '添加新的待办事项',
            '/add high': '添加高优先级待办',
            '/add medium': '添加中优先级待办',
            '/add low': '添加低优先级待办',
            '/search': '搜索待办事项',
            '/toggle': '切换待办完成状态',
            '/update': '更新待办事项',
            '/delete': '删除待办事项',
            '/stats': '查看统计信息',
            '/clear': '清除已完成的待办',
            '/help': '显示帮助信息',
            '/exit': '退出应用',
            '/quit': '退出应用',
            '/history': '查看命令历史记录'
        }
        self.keywords = [
            '添加', '删除', '完成', '查看', '帮助', '退出',
            '完成任务', '删除任务', '查看任务', '添加任务',
            '搜索', '统计', '清理', '优先级'
        ]
    
    def get_completions(self, document, complete_event):
        text = document.text.lower()
        
        # 匹配斜杠命令
        if text.startswith('/'):
            for cmd, desc in self.commands.items():
                if cmd.lower().startswith(text):
                    yield Completion(cmd, start_position=-len(text), display_meta=desc)
        else:
            # 匹配关键词
            for keyword in self.keywords:
                if keyword.lower().startswith(text):
                    yield Completion(keyword, start_position=-len(text))


class TodoCLI:
    """TODO CLI 交互层"""

    def __init__(self):
        # 初始化组件
        self.console = Console()
        self.manager = TodoManager()

        # 加载配置
        config = self._load_config()
        self.agent = AgentCore(self.manager, config)

        # 初始化 prompt_toolkit
        self.use_simple_input = True
        self.session = None
        self.ctrl_c_count = 0
        
        # 命令历史记录（用于 /history 命令）
        self.command_history = []

        # 只有在 prompt_toolkit 可用时才初始化
        if PROMPT_TOOLKIT_AVAILABLE:
            try:
                self.history = InMemoryHistory()
                self.completer = CommandCompleter()
                self.style = Style.from_dict({
                    'prompt': '#61afef',
                    'input': '#ffffff',
                })
                # 使用简单的字符串作为 prompt，避免 Text 类的兼容性问题
                self.prompt_str = "TodoAgent > "
                
                # 尝试创建 PromptSession
                self.session = PromptSession(
                    history=self.history,
                    auto_suggest=AutoSuggestFromHistory(),
                    completer=self.completer,
                    style=self.style,
                    complete_in_thread=True,
                    mouse_support=False
                )
                self.use_simple_input = False
                self.console.print("[green]已启用高级输入模式（支持命令补全和历史记录）[/green]")
            except Exception as e:
                self.console.print(f"[yellow]切换到简化输入模式: {e}[/yellow]")
                self.use_simple_input = True
        else:
            self.console.print("[yellow]prompt_toolkit 不可用，使用简化输入模式[/yellow]")

    def _load_config(self):
        """加载配置"""
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        # 统一配置优先级：默认值 < config/settings.json < 环境变量。
        return load_settings(project_root)

    def _get_task_status_color(self, todo):
        """获取任务状态对应的颜色"""
        if todo.completed:
            return "grey50"
        elif todo.is_overdue():
            return "red"
        else:
            return "default"

    def _get_due_time_color(self, todo):
        """获取截止时间的颜色"""
        if todo.completed:
            return "grey50"
        elif todo.is_overdue():
            return "red"
        else:
            # 检查是否即将到期（2天内）
            return "orange" if self._is_upcoming(todo) else "default"

    def _is_upcoming(self, todo, days=2):
        """检查任务是否即将到期"""
        from datetime import timedelta
        if not todo.end_time:
            return False
        
        now = datetime.now()
        try:
            fmt = "%Y-%m-%d %H:%M:%S" if len(todo.end_time) > 16 else "%Y-%m-%d %H:%M" if ":" in todo.end_time else "%Y-%m-%d"
            end_dt = datetime.strptime(todo.end_time, fmt)
            deadline = now + timedelta(days=days)
            return now < end_dt <= deadline
        except ValueError:
            return False

    def _get_priority_marker(self, priority):
        """获取优先级标记"""
        markers = {
            "high": "🔴",
            "medium": "🟡",
            "low": "🟢"
        }
        return markers.get(priority, "")

    def _get_priority_color(self, priority):
        """获取优先级颜色"""
        colors = {
            "high": "red",
            "medium": "yellow",
            "low": "green"
        }
        return colors.get(priority, "default")

    def _handle_slash_command(self, command):
        """处理斜杠命令"""
        parts = command.split(' ', 2)
        cmd = parts[0]
        subcmd = parts[1] if len(parts) > 1 else ""
        args = parts[2] if len(parts) > 2 else ""

        if cmd == "/list":
            return self._handle_list_command(subcmd)
        elif cmd == "/add":
            return self._handle_add_command(subcmd, args)
        elif cmd == "/search":
            return self._handle_search_command(args)
        elif cmd == "/toggle":
            return self._handle_toggle_command(args)
        elif cmd == "/update":
            return self._handle_update_command(subcmd, args)
        elif cmd == "/delete":
            return self._handle_delete_command(args)
        elif cmd == "/stats":
            return self._handle_stats_command()
        elif cmd == "/clear":
            return self._handle_clear_command()
        elif cmd == "/help":
            return self._handle_help_command()
        elif cmd == "/exit" or cmd == "/quit":
            return "exit"
        elif cmd == "/history":
            return self._handle_history_command()
        else:
            return f"未知命令: {cmd}"

    def _handle_list_command(self, subcmd=""):
        """处理 /list 命令，支持多种过滤条件"""
        # 根据子命令决定筛选条件
        if subcmd == "today":
            todos = self.manager.get_today()
            title = "📅 今天的待办事项"
        elif subcmd == "week":
            todos = self.manager.get_this_week()
            title = "📆 本周的待办事项"
        elif subcmd == "month":
            todos = self.manager.get_this_month()
            title = "📋 本月的待办事项"
        elif subcmd == "pending":
            todos = self.manager.get_by_status(False)
            title = "🔘 未完成的待办事项"
        elif subcmd == "completed":
            todos = self.manager.get_by_status(True)
            title = "✅ 已完成的待办事项"
        elif subcmd == "overdue":
            todos = self.manager.get_overdue()
            title = "🔴 已过期的待办事项"
        elif subcmd == "upcoming":
            todos = self.manager.get_upcoming()
            title = "🟠 即将到期的待办事项"
        else:
            todos = self.manager.get_all()
            title = "📋 所有待办事项"

        if not todos:
            return f"{title}\n\n  暂无待办事项"

        # 使用 Rich Table 显示
        table = Table(title=title)
        table.add_column("ID", style="dim", width=8)
        table.add_column("优先级", width=6)
        table.add_column("标题")
        table.add_column("状态", width=8)
        table.add_column("截止时间")

        for todo in todos:
            status_text = Text("✓ 完成", style="grey50") if todo.completed else Text("○ 未完成", style="green")
            priority_marker = self._get_priority_marker(todo.priority)
            
            due_time = todo.end_time if todo.end_time else "-"
            due_style = self._get_due_time_color(todo)
            
            table.add_row(
                todo.id[:8],
                priority_marker,
                Text(todo.title, style=self._get_task_status_color(todo)),
                status_text,
                Text(due_time, style=due_style)
            )

        # 返回表格的字符串表示
        output = "\n"
        output += "─" * 80 + "\n"
        for todo in todos:
            status = "[grey50]✓ 完成[/grey50]" if todo.completed else "[green]○ 未完成[/green]"
            priority = self._get_priority_marker(todo.priority)
            due_time = todo.end_time if todo.end_time else "-"
            
            # 根据状态设置截止时间颜色
            if todo.completed:
                due_color = "grey50"
            elif todo.is_overdue():
                due_color = "red"
            elif self._is_upcoming(todo):
                due_color = "orange"
            else:
                due_color = "default"
            
            title_color = "grey50" if todo.completed else "default"
            output += f"  {todo.id[:8]}  {priority} [{status}] [{title_color}]{todo.title}[/{title_color}]  [{due_color}]{due_time}[/{due_color}]\n"
        output += "─" * 80
        
        return output

    def _handle_add_command(self, priority, args):
        """处理 /add 命令"""
        if not args:
            return "请输入待办事项标题: /add [high/medium/low] <标题>"

        # 确定优先级
        if priority in ["high", "medium", "low"]:
            title = args
        else:
            priority = "medium"
            title = f"{priority} {args}" if priority else args

        todo = self.manager.add(title=title.strip(), priority=priority)
        
        priority_marker = self._get_priority_marker(priority)
        return f"✅ 成功添加待办事项:\n   标题: {todo.title}\n   优先级: {priority_marker} {priority}\n   截止时间: {todo.end_time}\n   ID: {todo.id}"

    def _handle_search_command(self, keyword):
        """处理 /search 命令"""
        if not keyword:
            return "请输入搜索关键词: /search <关键词>"

        todos = self.manager.search(keyword)
        if not todos:
            return f"🔍 未找到包含「{keyword}」的待办事项"

        output = f"\n🔍 搜索结果（包含「{keyword}」）:\n"
        output += "─" * 80 + "\n"
        for todo in todos:
            status = "[grey50]✓ 完成[/grey50]" if todo.completed else "[green]○ 未完成[/green]"
            priority = self._get_priority_marker(todo.priority)
            due_time = todo.end_time if todo.end_time else "-"
            
            if todo.completed:
                due_color = "grey50"
            elif todo.is_overdue():
                due_color = "red"
            elif self._is_upcoming(todo):
                due_color = "orange"
            else:
                due_color = "default"
            
            title_color = "grey50" if todo.completed else "default"
            output += f"  {todo.id[:8]}  {priority} [{status}] [{title_color}]{todo.title}[/{title_color}]  [{due_color}]{due_time}[/{due_color}]\n"
        output += "─" * 80
        
        return output

    def _handle_toggle_command(self, todo_id):
        """处理 /toggle 命令"""
        if not todo_id:
            return "请输入待办事项ID: /toggle <ID>"

        todo = self.manager.toggle_completed(todo_id)
        if not todo:
            return f"❌ 未找到 ID 为 {todo_id} 的待办事项"
        
        status = "已完成" if todo.completed else "未完成"
        status_color = "green" if todo.completed else "yellow"
        return f"✓ 已将「{todo.title}」标记为 [{status_color}]{status}[/{status_color}]"

    def _handle_update_command(self, subcmd, args):
        """处理 /update 命令"""
        if not subcmd:
            return "用法: /update <ID> [title|end_time|priority] <值>\n例如: /update abc123 title 新标题"
        
        parts = args.split(' ', 1)
        if len(parts) < 2:
            return "请提供完整参数: /update <ID> <field> <value>"
        
        todo_id = subcmd
        field = parts[0]
        value = parts[1]
        
        update_params = {}
        if field == "title":
            update_params["title"] = value
        elif field == "end_time" or field == "deadline":
            update_params["end_time"] = value
        elif field == "priority":
            if value not in ["high", "medium", "low"]:
                return "优先级必须是 high、medium 或 low"
            update_params["priority"] = value
        elif field == "desc" or field == "description":
            update_params["description"] = value
        else:
            return f"未知字段: {field}，支持的字段: title, end_time, priority, desc"
        
        todo = self.manager.update(todo_id, **update_params)
        if not todo:
            return f"❌ 未找到 ID 为 {todo_id} 的待办事项"
        
        return f"✓ 已更新「{todo.title}」的 {field}"

    def _handle_delete_command(self, todo_id):
        """处理 /delete 命令"""
        if not todo_id:
            return "请输入待办事项ID: /delete <ID>"

        if self.manager.delete(todo_id):
            return f"🗑️ 已删除 ID 为 {todo_id} 的待办事项"
        else:
            return f"❌ 未找到 ID 为 {todo_id} 的待办事项"

    def _handle_stats_command(self):
        """处理 /stats 命令"""
        stats = self.manager.get_statistics()
        
        output = "📊 待办事项统计\n"
        output += "─" * 80 + "\n"
        output += f"  总任务数: {stats['total']}\n"
        output += f"  ✅ 已完成: {stats['completed']}\n"
        output += f"  🔘 未完成: {stats['pending']}\n"
        output += f"  🔴 已过期: {stats['overdue']}\n"
        output += f"  🟠 即将到期: {stats['upcoming']}\n"
        output += f"  📈 完成率: {stats['completion_rate']}\n"
        output += "─" * 80
        
        return output

    def _handle_clear_command(self):
        """处理 /clear 命令"""
        count = self.manager.clear_completed()
        if count > 0:
            return f"🗑️ 已清除 {count} 条已完成的待办事项"
        else:
            return "ℹ️ 没有已完成的待办事项可清除"

    def _handle_help_command(self):
        """处理 /help 命令"""
        help_text = "📖 可用命令:\n"
        help_text += "─" * 80 + "\n"
        help_text += "  [bold]/list[/bold] [today|week|month|pending|completed|overdue|upcoming]\n"
        help_text += "      查看待办事项列表\n"
        help_text += "  [bold]/add[/bold] [high|medium|low] <标题>\n"
        help_text += "      添加新的待办事项\n"
        help_text += "  [bold]/search[/bold] <关键词>\n"
        help_text += "      搜索待办事项\n"
        help_text += "  [bold]/toggle[/bold] <ID>\n"
        help_text += "      切换待办完成状态\n"
        help_text += "  [bold]/update[/bold] <ID> [title|end_time|priority] <值>\n"
        help_text += "      更新待办事项\n"
        help_text += "  [bold]/delete[/bold] <ID>\n"
        help_text += "      删除待办事项\n"
        help_text += "  [bold]/stats[/bold]\n"
        help_text += "      查看统计信息\n"
        help_text += "  [bold]/clear[/bold]\n"
        help_text += "      清除已完成的待办\n"
        help_text += "  [bold]/history[/bold]\n"
        help_text += "      查看命令历史记录\n"
        help_text += "  [bold]/help[/bold]\n"
        help_text += "      显示帮助信息\n"
        help_text += "  [bold]/exit[/bold] 或 [bold]/quit[/bold]\n"
        help_text += "      退出应用\n"
        help_text += "─" * 80 + "\n"
        help_text += "💡 你也可以直接输入自然语言，让 AI 助手帮你管理待办事项\n"
        help_text += "\n🚪 退出方式:\n"
        help_text += "  - 输入 /exit 或 /quit\n"
        help_text += "  - 按两次 Ctrl+C\n"
        help_text += "  - 按 Ctrl+D (EOF)\n"
        help_text += "\n🎨 颜色含义:\n"
        help_text += "  🔴 红色: 高优先级 / 已过期\n"
        help_text += "  🟠 橙色: 即将到期（2天内）\n"
        help_text += "  🟡 黄色: 中优先级\n"
        help_text += "  🟢 绿色: 低优先级 / 正常\n"
        help_text += "  灰色: 已完成"
        return help_text

    def _handle_history_command(self):
        """处理 /history 命令"""
        if not self.command_history:
            return "📜 暂无命令历史记录"

        result = "📜 命令历史记录:\n"
        result += "─" * 80 + "\n"
        for i, (timestamp, cmd) in enumerate(reversed(self.command_history[-20:]), 1):
            result += f"  {i}. [{timestamp}] {cmd}\n"
        
        if len(self.command_history) > 20:
            result += f"\n... 还有 {len(self.command_history) - 20} 条历史记录未显示"
        
        return result

    def _handle_natural_language(self, text):
        """处理自然语言命令 - 支持流式输出"""
        # 显示 Thinking 状态
        with self.console.status("Thinking...") as status:
            try:
                # 准备流式输出
                full_response = []
                
                def on_stream_chunk(chunk):
                    full_response.append(chunk)
                    # 使用打字机效果逐字显示
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
                
                # 调用 Agent 的 chat 方法，启用流式输出
                sys.stdout.write("\n")
                sys.stdout.flush()
                self.agent.chat(text, stream=True, on_stream_chunk=on_stream_chunk)
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(full_response)
            except Exception as e:
                error_msg = f"处理请求时出错: {e}"
                self.console.print(error_msg)
                return error_msg

    def _display_response(self, response):
        """显示响应"""
        if response == "exit":
            return False

        # 对于非空响应，需要显示
        if response:
            # 尝试作为 Markdown 渲染
            try:
                markdown = Markdown(response)
                self.console.print(markdown)
            except:
                # 如果不是 Markdown，直接打印
                self.console.print(response)

        return True

    def _get_input(self):
        """获取用户输入，优先使用 prompt_toolkit，失败则使用简化输入"""
        if self.use_simple_input or not self.session:
            return input("TodoAgent > ")

        try:
            return self.session.prompt(self.prompt_str)
        except Exception as e:
            self.console.print(f"[yellow]切换到简化输入模式: {e}[/yellow]")
            self.use_simple_input = True
            return input("TodoAgent > ")

    def run(self):
        """运行 CLI"""
        self.console.print(Panel("""
TodoAgent CLI

完全参考 Claude Code 界面设计

【命令列表】
/list [today|week|month|pending|completed|overdue|upcoming]
/add [high|medium|low] <标题>
/search <关键词>
/toggle <ID>
/update <ID> <field> <value>
/delete <ID>
/stats
/clear
/history
/help

【颜色含义】
🔴 红色: 高优先级 / 已过期
🟠 橙色: 即将到期（2天内）
🟡 黄色: 中优先级
🟢 绿色: 低优先级 / 正常
灰色: 已完成

【退出方式】
- 输入 /exit 或 /quit
- 按两次 Ctrl+C
- 按 Ctrl+D (EOF)
""", title="欢迎使用 TodoAgent", style="blue"))

        while True:
            try:
                # 获取用户输入
                text = self._get_input()
                text = text.strip()

                if not text:
                    continue

                # 记录命令历史
                self.command_history.append((datetime.now().strftime("%H:%M:%S"), text))

                # 处理命令
                if text.startswith('/'):
                    response = self._handle_slash_command(text)
                else:
                    response = self._handle_natural_language(text)

                # 显示响应
                if not self._display_response(response):
                    break

                # 重置 Ctrl+C 计数
                self.ctrl_c_count = 0

            except KeyboardInterrupt:
                self.ctrl_c_count += 1
                if self.ctrl_c_count == 1:
                    self.console.print("\n[yellow]再次按 Ctrl+C 退出[/yellow]")
                    continue
                elif self.ctrl_c_count >= 2:
                    self.console.print("\n[yellow]快速退出[/yellow]")
                    break
            except EOFError:
                self.console.print("\n[yellow]EOF 退出[/yellow]")
                break

        self.console.print("\n👋 Goodbye!")


def main():
    """命令行入口函数，供 pyproject console script 调用。"""
    cli = TodoCLI()
    cli.run()


if __name__ == "__main__":
    main()

