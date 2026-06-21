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

from ai_todo_assistant.infrastructure.persistence import build_todo_repository, build_workflow_repository
from ai_todo_assistant.application.agent import AgentCore
from ai_todo_assistant.application.workflow import (
    CodexTaskReportService,
    ContinueService,
    DailyReviewService,
    EvidenceService,
    WorkItemService,
    WorkflowSyncService,
)
from ai_todo_assistant.domain.workflow import WorkItemStatus
from ai_todo_assistant.infrastructure.config import load_settings


PROMPT_TEXT = "TodoAgent"
PROMPT_ANSI = "\033[36mTodoAgent\033[90m > \033[0m"


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
            '/list': '查看统一任务列表',
            '/list today': '查看今天的待办',
            '/list week': '查看本周的待办',
            '/list month': '查看本月的待办',
            '/list pending': '查看未完成的待办',
            '/list completed': '查看已完成的待办',
            '/list overdue': '查看过期的待办',
            '/list upcoming': '查看即将到期的待办',
            '/today': '查看今日个人助理简报',
            '/plan day': '生成今日计划',
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
            '/preferences': '查看长期偏好',
            '/remember': '记住长期偏好',
            '/forget': '忘记长期偏好',
            '/work add': '创建工作项',
            '/work import redmine': '导入 Redmine 工作项',
            '/work status': '查看工作项状态',
            '/work conflicts': '查看需要人工处理的来源冲突',
            '/work split': '拆分误合并的来源',
            '/work rollback': '回滚误合并记录',
            '/work show': '查看工作项完整来源链',
            '/work evidence add': '记录工作证据',
            '/work evidence summary': '汇总工作证据',
            '/work evidence timeline': '按时间查看工作证据',
            '/sync': '同步 Codex 报告和当前项目上下文',
            '/sync --dry-run': '预览同步结果但不写入',
            '/sync status': '查看同步健康状态',
            '/next': '推荐下一步工作',
            '/review': '生成工作日复盘草稿',
            '/continue': '兼容命令：推荐下一步工作',
            '/start day': '生成工作日启动计划',
            '/review day': '兼容命令：生成工作日复盘草稿',
            '/codex tasks': '查看 Codex 未完成任务日报',
            '/help': '显示帮助信息',
            '/help todo': '查看 Todo 管理命令',
            '/help work': '查看工作流和证据命令',
            '/help prefs': '查看长期偏好命令',
            '/help system': '查看历史、退出和颜色说明',
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

        # 加载配置
        config = self._load_config()
        self.config = config
        self.manager = build_todo_repository(config)
        self.workflow_repository = build_workflow_repository(config)
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
                    'prompt': '#00d1b2 bold',
                    'prompt.mark': '#8a8f98',
                    'input': '#ffffff',
                })
                self.prompt_str = [
                    ("class:prompt", PROMPT_TEXT),
                    ("class:prompt.mark", " > "),
                ]
                
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
            return self._handle_list_command(subcmd, args)
        elif cmd == "/today":
            return self._handle_today_command()
        elif cmd == "/plan":
            return self._handle_plan_command(subcmd)
        elif cmd == "/add":
            return self._handle_add_command(subcmd, args)
        elif cmd == "/search":
            return self._handle_search_command(" ".join(part for part in [subcmd, args] if part).strip())
        elif cmd == "/toggle":
            return self._handle_toggle_command(subcmd)
        elif cmd == "/update":
            return self._handle_update_command(subcmd, args)
        elif cmd == "/delete":
            return self._handle_delete_command(subcmd)
        elif cmd == "/stats":
            return self._handle_stats_command()
        elif cmd == "/clear":
            return self._handle_clear_command()
        elif cmd == "/preferences":
            return self._handle_preferences_command()
        elif cmd == "/remember":
            return self._handle_remember_command(subcmd, args)
        elif cmd == "/forget":
            return self._handle_forget_command(subcmd)
        elif cmd == "/codex":
            return self._handle_codex_command(subcmd)
        elif cmd == "/work":
            return self._handle_work_command(subcmd, args)
        elif cmd == "/sync":
            return self._handle_sync_command(subcmd, args)
        elif cmd == "/next":
            return self._handle_continue_command()
        elif cmd == "/continue":
            return self._handle_continue_command()
        elif cmd == "/start":
            return self._handle_start_command(subcmd)
        elif cmd == "/review":
            return self._handle_review_command(subcmd)
        elif cmd == "/help":
            return self._handle_help_command(subcmd)
        elif cmd == "/exit" or cmd == "/quit":
            return "exit"
        elif cmd == "/history":
            return self._handle_history_command()
        else:
            return f"未知命令: {cmd}"

    def _handle_list_command(self, subcmd="", args=""):
        """处理 /list 命令，支持多种过滤条件"""
        raw_args = " ".join(part for part in [subcmd, args] if part).strip()
        source_filter = _parse_source_filter(raw_args)
        if subcmd == "--source":
            subcmd = ""
        # 根据子命令决定筛选条件
        if subcmd == "":
            return self._handle_daily_triage_list(source_filter)
        elif subcmd == "today":
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
            title = "🔘 未完成任务"
        elif subcmd == "completed":
            todos = self.manager.get_by_status(True)
            title = "✅ 已完成任务"
        elif subcmd == "overdue":
            todos = self.manager.get_overdue()
            title = "🔴 已过期的待办事项"
        elif subcmd == "upcoming":
            todos = self.manager.get_upcoming()
            title = "🟠 即将到期的待办事项"
        else:
            todos = self.manager.get_all()
            title = "📋 统一任务视图"

        if source_filter and source_filter != "todo":
            todos = []
        work_items = self._work_items_for_list(subcmd, source_filter)
        if not todos and not work_items:
            return f"{title}\n\n  暂无任务"

        # 使用 Rich Table 显示
        table = Table(title=title)
        table.add_column("ID", style="dim", width=8)
        table.add_column("来源", width=8)
        table.add_column("优先级", width=6)
        table.add_column("标题")
        table.add_column("状态", width=8)
        table.add_column("截止/下一步")

        for todo in todos:
            status_text = Text("✓ 完成", style="grey50") if todo.completed else Text("○ 未完成", style="green")
            priority_marker = self._get_priority_marker(todo.priority)
            
            due_time = todo.end_time if todo.end_time else "-"
            due_style = self._get_due_time_color(todo)
            
            table.add_row(
                todo.id[:8],
                "todo",
                priority_marker,
                Text(todo.title, style=self._get_task_status_color(todo)),
                status_text,
                Text(due_time, style=due_style)
            )
        for item in work_items:
            status_style = "yellow" if item.status == "blocked" else "grey50" if item.status == "done" else "cyan"
            priority_marker = self._get_priority_marker(item.priority)
            table.add_row(
                item.id[:8],
                item.source,
                priority_marker,
                Text(item.title, style="grey50" if item.status == "done" else "default"),
                Text(item.status, style=status_style),
                item.next_action or item.sync_summary or "-",
            )

        return table

    def _handle_daily_triage_list(self, source_filter=""):
        todos = [] if source_filter and source_filter != "todo" else [
            todo for todo in self.manager.get_all() if not todo.completed
        ]
        work_items = []
        if source_filter != "todo":
            try:
                work_items = self._workflow_repo().list_work_items(include_closed=True)
            except Exception:
                work_items = []
            if source_filter:
                work_items = [item for item in work_items if item.source == source_filter]
            work_items = _dedupe_work_items(work_items)

        rows = _daily_triage_work_item_rows(work_items)
        for todo in self._rank_tasks(todos):
            rows.append(
                {
                    "group": "todo reminders",
                    "id": todo.id[:8],
                    "source": "todo",
                    "priority": self._get_priority_marker(todo.priority),
                    "title": Text(todo.title, style=self._get_task_status_color(todo)),
                    "status": Text("○ 未完成", style="green"),
                    "reason": "todo reminder",
                    "next": Text(todo.end_time if todo.end_time else "-", style=self._get_due_time_color(todo)),
                }
            )

        if not rows:
            return "📋 每日工作分诊\n\n  暂无任务"

        table = Table(title="📋 每日工作分诊")
        table.add_column("分组", width=22)
        table.add_column("ID", style="dim", width=8)
        table.add_column("来源", width=7)
        table.add_column("优先级", width=4)
        table.add_column("标题", no_wrap=True)
        table.add_column("状态", width=7)
        table.add_column("原因", width=38, no_wrap=True)
        table.add_column("截止/下一步", width=14)

        for row in rows:
            table.add_row(
                row["group"],
                row["id"],
                row["source"],
                row["priority"],
                row["title"],
                row["status"],
                row["reason"],
                row["next"],
            )
        return table

    def _work_items_for_list(self, subcmd="", source_filter=""):
        if subcmd in {"today", "week", "month", "overdue", "upcoming"}:
            return []
        try:
            items = self._workflow_repo().list_work_items(include_closed=(subcmd == "completed"))
        except Exception:
            return []
        if source_filter and source_filter != "todo":
            items = [item for item in items if item.source == source_filter]
        elif source_filter == "todo":
            items = []
        if subcmd == "completed":
            return _dedupe_work_items([item for item in items if item.status == "done"])
        return _dedupe_work_items([item for item in items if item.status not in {"done", "archived"}])

    def _handle_add_command(self, priority, args):
        """处理 /add 命令"""
        if priority in ["high", "medium", "low"]:
            title = args
        else:
            title = " ".join(part for part in [priority, args] if part).strip()
            priority = "medium"

        if not title:
            return "请输入待办事项标题: /add [high/medium/low] <标题>"

        todo = self.manager.add(title=title.strip(), priority=priority)
        
        priority_marker = self._get_priority_marker(priority)
        return f"✅ 成功添加待办事项:\n   标题: {todo.title}\n   优先级: {priority_marker} {priority}\n   截止时间: {todo.end_time}\n   ID: {todo.id}"

    def _handle_today_command(self):
        today = self.manager.get_today()
        overdue = self.manager.get_overdue()
        upcoming = self.manager.get_upcoming()
        high_priority = [
            todo for todo in self.manager.get_by_priority("high") if not todo.completed
        ]

        output = "今日简报\n"
        output += "─" * 80 + "\n"
        output += f"  今日相关: {len(today)} 条\n"
        output += f"  已过期: {len(overdue)} 条\n"
        output += f"  即将到期: {len(upcoming)} 条\n"
        output += f"  高优先级未完成: {len(high_priority)} 条\n"
        output += "\n优先处理:\n"
        focus = self._rank_tasks({todo.id: todo for todo in overdue + high_priority + today + upcoming}.values())
        if not focus:
            output += "  暂无需要立即处理的任务\n"
        else:
            for index, todo in enumerate(focus[:8], 1):
                output += f"  {index}. {self._format_task_line(todo)}\n"
        output += "─" * 80
        return output

    def _handle_plan_command(self, subcmd):
        if subcmd not in {"day", "today"}:
            return "用法: /plan day"

        candidates = [todo for todo in self.manager.get_all() if not todo.completed]
        planned = self._rank_tasks(candidates)
        output = "今日计划\n"
        output += "─" * 80 + "\n"
        if not planned:
            output += "  暂无未完成任务，可以安排复盘或学习。\n"
        else:
            for index, todo in enumerate(planned[:10], 1):
                output += f"  {index}. {self._format_task_line(todo)}\n"
        output += "─" * 80
        return output

    def _rank_tasks(self, todos):
        priority_rank = {"high": 0, "medium": 1, "low": 2}

        def sort_key(todo):
            due = self._parse_datetime(todo.end_time)
            due_key = due or datetime.max
            return (
                0 if todo.is_overdue() else 1,
                priority_rank.get(todo.priority, 1),
                due_key,
                todo.created_at,
            )

        return sorted(todos, key=sort_key)

    def _format_task_line(self, todo):
        due = f" 截止:{todo.end_time}" if todo.end_time else ""
        status = "已过期" if todo.is_overdue() else "待处理"
        return f"{self._get_priority_marker(todo.priority)} {todo.title} [{status}]{due} ID:{todo.id[:8]}"

    @staticmethod
    def _parse_datetime(value):
        if not value:
            return None
        try:
            fmt = "%Y-%m-%d %H:%M:%S" if len(value) > 16 else "%Y-%m-%d %H:%M" if ":" in value else "%Y-%m-%d"
            return datetime.strptime(value, fmt)
        except ValueError:
            return None

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

    def _handle_preferences_command(self):
        preferences = self.manager.list_preferences()
        if not preferences:
            return "当前还没有记住任何长期偏好"
        output = "长期偏好\n"
        output += "─" * 80 + "\n"
        for key, value in preferences.items():
            output += f"  {key}: {value}\n"
        output += "─" * 80
        return output

    def _handle_remember_command(self, key, value):
        if not key or not value:
            return "用法: /remember <偏好名> <偏好内容>"
        self.manager.remember_preference(key, value)
        return f"已记住偏好：{key} = {value}"

    def _handle_forget_command(self, key):
        if not key:
            return "用法: /forget <偏好名>"
        if self.manager.forget_preference(key):
            return f"已忘记偏好：{key}"
        return f"未找到偏好：{key}"

    def _handle_codex_command(self, subcmd):
        if subcmd not in {"tasks", "unfinished"}:
            return "用法: /codex tasks"

        report, imported, report_dir = self._import_latest_codex_report()
        if not report:
            return f"Codex 未完成任务日报\n\n  暂无快照文件: {report_dir}"

        output = "Codex 未完成任务日报\n"
        output += "─" * 80 + "\n"
        output += f"  生成时间: {report.generated_at}\n"
        output += f"  未完成/阻塞: {report.total_unfinished} 项\n"
        output += f"  最近完成: {len(report.completed)} 项\n"
        output += f"  已同步工作项: {len(imported)} 项\n"
        if report.summary_path:
            output += f"  每日总结: {report.summary_path}\n"
        if report.summary:
            output += f"  摘要: {report.summary}\n"

        items = report.unfinished + report.blocked
        if not items:
            output += "\n  当前快照没有未完成任务\n"
        else:
            output += "\n优先跟进:\n"
            for index, item in enumerate(items[:10], 1):
                title = item.get("title") or item.get("name") or item.get("thread_id") or "未命名任务"
                status = item.get("status") or item.get("state") or "unknown"
                source = item.get("source") or item.get("thread_id") or item.get("cwd") or ""
                next_action = item.get("next_action") or item.get("next") or ""
                suffix = f" | {source}" if source else ""
                output += f"  {index}. [{status}] {title}{suffix}\n"
                if next_action:
                    output += f"     下一步: {next_action}\n"
        if report.completed:
            output += "\n最近完成:\n"
            for index, item in enumerate(report.completed[:5], 1):
                title = item.get("title") or item.get("name") or item.get("thread_id") or "未命名任务"
                source = item.get("source") or item.get("thread_id") or item.get("cwd") or ""
                signals = item.get("completion_signals") or item.get("evidence") or []
                if isinstance(signals, list):
                    signal_text = "；".join(str(signal) for signal in signals[:3])
                else:
                    signal_text = str(signals)
                suffix = f" | {source}" if source else ""
                output += f"  {index}. {title}{suffix}\n"
                if signal_text:
                    output += f"     完成证据: {signal_text}\n"
        output += "─" * 80
        return output

    def _import_latest_codex_report(self):
        report, report_dir = self._latest_codex_report()
        imported = WorkItemService(self._workflow_repo()).import_codex_report(report) if report else []
        return report, imported, report_dir

    def _preview_latest_codex_report(self):
        report, report_dir = self._latest_codex_report()
        imported = WorkItemService(self._workflow_repo()).preview_codex_report(report) if report else []
        return report, imported, report_dir

    def _latest_codex_report(self):
        config = getattr(self, "config", None) or self._load_config()
        report_dir = config.get("codex_task_report_dir", "data/codex-task-reports")
        if not os.path.isabs(report_dir):
            report_dir = os.path.join(config.get("project_root", os.getcwd()), report_dir)
        report = CodexTaskReportService(report_dir).latest_report()
        return report, report_dir

    def _workflow_repo(self):
        repo = getattr(self, "workflow_repository", None)
        if repo is None:
            repo = build_workflow_repository(getattr(self, "config", None) or self._load_config())
            self.workflow_repository = repo
        return repo

    def _handle_work_command(self, subcmd, args):
        repo = self._workflow_repo()
        service = WorkItemService(repo)
        if subcmd == "add":
            title = args.strip()
            if not title:
                return "用法: /work add <title>"
            item = service.create_manual(title, project_path=os.getcwd())
            return f"已创建工作项: {item.title} ID:{item.id}"
        if subcmd == "status":
            return service.status_summary()
        if subcmd == "conflicts":
            return service.conflict_summary()
        if subcmd == "show":
            work_item_id = args.strip()
            if not work_item_id:
                return "用法: /work show <work-id>"
            return self._show_work_item(work_item_id)
        if subcmd == "rollback":
            parts = args.split()
            if len(parts) < 2:
                return "用法: /work rollback <work-id> <audit-id>"
            try:
                item = service.rollback_merge(parts[0], parts[1])
            except ValueError as exc:
                return str(exc)
            return f"已回滚合并: {item.title} | {item.source}:{item.source_ref} ID:{item.id}"
        if subcmd == "import":
            parts = args.split()
            if len(parts) >= 2 and parts[0] == "redmine":
                try:
                    item = WorkflowSyncService(repo).import_redmine(os.getcwd(), parts[1])
                except RuntimeError as exc:
                    return f"Redmine 工作项导入失败: {exc}"
                return f"已导入 Redmine 工作项: {item.title} ID:{item.id}"
            return "用法: /work import redmine <id>"
        if subcmd == "split":
            parts = args.split(" ", 3)
            if len(parts) < 3:
                return "用法: /work split <work-id> <source> <source-ref> [title]"
            work_item_id, source, source_ref = parts[0], parts[1], parts[2]
            title = parts[3] if len(parts) > 3 else ""
            try:
                item = service.split_source_ref(work_item_id, source, source_ref, title=title)
            except ValueError as exc:
                return str(exc)
            return f"已拆分工作项: {item.title} | {item.source}:{item.source_ref} ID:{item.id}"
        if subcmd == "evidence":
            return self._handle_work_evidence_command(args)
        return "用法: /work [add|import|split|rollback|show|status|evidence]"

    def _handle_work_evidence_command(self, args):
        parts = args.split(" ", 2)
        if len(parts) < 2:
            return "用法: /work evidence [add|summary] <work-id> [summary]"
        action, work_item_id = parts[0], parts[1]
        evidence_service = EvidenceService(self._workflow_repo())
        if action == "add":
            summary = parts[2].strip() if len(parts) > 2 else ""
            if not summary:
                return "用法: /work evidence add <work-id> <summary>"
            try:
                evidence = evidence_service.record(work_item_id, "note", summary)
            except ValueError as exc:
                return str(exc)
            return f"已记录证据: {evidence.summary}"
        if action == "summary":
            return evidence_service.summarize(work_item_id)
        if action == "timeline":
            return evidence_service.timeline(work_item_id)
        return "用法: /work evidence [add|summary|timeline] <work-id> [summary]"

    def _handle_sync_command(self, subcmd, args):
        options = _parse_sync_options(subcmd, args)
        if options["status"]:
            return self._sync_status()
        path = options["path"] or os.getcwd()
        if options["dry_run"]:
            report, imported, report_dir = self._preview_latest_codex_report()
            lines = ["同步结果 [DRY-RUN]", "─" * 80]
            if report:
                lines.append(
                    f"  [DRY-RUN] codex: 预计导入/刷新 {len(imported)} 项，不会写入 "
                    f"({imported.summary_text()})"
                )
                for detail in imported.details[:10]:
                    lines.append(f"     {detail}")
            else:
                lines.append(f"  [UNAVAILABLE] codex: 暂无快照文件 {report_dir}")
            lines.append(f"  [SKIP] project: dry-run 不会同步项目上下文 {path}")
            lines.append("─" * 80)
            return "\n".join(lines)
        report, imported, report_dir = self._import_latest_codex_report()
        snapshots = []
        path_error = ""
        try:
            snapshots = WorkflowSyncService(self._workflow_repo()).sync_project(path)
        except (OSError, RuntimeError) as exc:
            path_error = f"项目路径不可用，已跳过项目上下文同步: {path}"
            if str(exc):
                path_error = f"{path_error} ({exc})"
        lines = ["同步结果", "─" * 80]
        if report:
            lines.append(
                f"  [OK] codex: 已导入/刷新 {len(imported)} 项 "
                f"({imported.summary_text()})"
            )
            for detail in imported.details[:10]:
                lines.append(f"     {detail}")
        else:
            lines.append(f"  [UNAVAILABLE] codex: 暂无快照文件 {report_dir}")
        if path_error:
            lines.append(f"  [UNAVAILABLE] project: {path_error}")
        for snapshot in snapshots:
            status = "OK" if snapshot.success else "UNAVAILABLE"
            lines.append(f"  [{status}] {snapshot.source}: {snapshot.summary}")
            if snapshot.error:
                lines.append(f"     {snapshot.error}")
        lines.append("─" * 80)
        return "\n".join(lines)

    def _sync_status(self):
        report, report_dir = self._latest_codex_report()
        items = self._workflow_repo().list_work_items(include_closed=True)
        counts = {
            WorkItemStatus.ACTIVE.value: 0,
            WorkItemStatus.BLOCKED.value: 0,
            WorkItemStatus.DONE.value: 0,
            WorkItemStatus.ARCHIVED.value: 0,
        }
        latest_sync = ""
        for item in items:
            if item.status in counts:
                counts[item.status] += 1
            if item.last_synced_at and item.last_synced_at > latest_sync:
                latest_sync = item.last_synced_at
        lines = ["同步状态", "─" * 80]
        if report:
            lines.append(f"  最新 Codex report: {getattr(report, 'path', '')}")
            lines.append(f"  report generated_at: {getattr(report, 'generated_at', '')}")
            lines.append(
                f"  report buckets: unfinished={len(getattr(report, 'unfinished', []))}, "
                f"blocked={len(getattr(report, 'blocked', []))}, completed={len(getattr(report, 'completed', []))}"
            )
        else:
            lines.append(f"  最新 Codex report: 暂无 ({report_dir})")
        lines.append(
            f"  WorkItems: active={counts[WorkItemStatus.ACTIVE.value]}, "
            f"blocked={counts[WorkItemStatus.BLOCKED.value]}, "
            f"done={counts[WorkItemStatus.DONE.value]}, "
            f"archived={counts[WorkItemStatus.ARCHIVED.value]}"
        )
        lines.append(f"  最近 WorkItem 同步: {latest_sync or '-'}")
        lines.append("─" * 80)
        return "\n".join(lines)

    def _show_work_item(self, work_item_id):
        item = self._workflow_repo().get_work_item(work_item_id)
        if not item:
            return f"未知工作项: {work_item_id}"
        lines = ["工作项详情", "─" * 80]
        lines.append(f"  标题: {item.title}")
        lines.append(f"  状态: {item.status} / {item.priority}")
        lines.append(f"  主来源: {item.source}:{item.source_ref}" if item.source_ref else f"  主来源: {item.source}")
        if item.source_refs:
            lines.append("  来源链:")
            for ref in item.source_refs:
                label = f" | {ref.get('label')}" if ref.get("label") else ""
                lines.append(f"    - {ref.get('source')}:{ref.get('source_ref')}{label}")
        if item.source_identities:
            lines.append("  稳定身份:")
            for identity in item.source_identities:
                lines.append(f"    - {identity}")
        if item.merge_audit:
            lines.append("  合并审计:")
            for audit in item.merge_audit:
                lines.append(
                    f"    - {audit.get('id', '-')}: {audit.get('source')}:{audit.get('source_ref')} "
                    f"{audit.get('reason', '')} {audit.get('merged_at', '')}"
                )
        if item.merge_conflicts:
            lines.append("  冲突:")
            for conflict in item.merge_conflicts:
                lines.append(f"    - {conflict}")
        evidence = self._workflow_repo().list_evidence(item.id)
        if evidence:
            lines.append("  证据:")
            for entry in evidence[:10]:
                lines.append(f"    - [{entry.evidence_type}/{entry.source}] {entry.summary}")
        lines.append("─" * 80)
        return "\n".join(lines)

    def _handle_continue_command(self):
        return ContinueService(self._workflow_repo()).recommend()

    def _handle_start_command(self, subcmd):
        if subcmd != "day":
            return "用法: /start day"
        return DailyReviewService(self._workflow_repo()).start_day()

    def _handle_review_command(self, subcmd):
        if subcmd == "":
            return DailyReviewService(self._workflow_repo()).review_day()
        if subcmd != "day":
            return "用法: /review day"
        return DailyReviewService(self._workflow_repo()).review_day()

    def _handle_help_command(self, topic=""):
        """处理 /help 命令"""
        topic = topic.strip().lower()
        if topic in ("", "main"):
            return "\n".join([
                "📖 可用命令",
                "─" * 80,
                "日常主命令:",
                "  /list    统一任务视图",
                "  /sync    同步最新工作上下文",
                "  /next    推荐下一步",
                "  /review  生成今日复盘",
                "  /help    查看帮助",
                "",
                "分类帮助:",
                "  /help todo    Todo 管理命令",
                "  /help work    工作流、证据和兼容命令",
                "  /help prefs   长期偏好命令",
                "  /help system  历史、退出和颜色说明",
                "─" * 80,
                "💡 你也可以直接输入自然语言，让 AI 助手帮你管理待办事项",
            ])
        if topic == "todo":
            return "\n".join([
                "📖 Todo 管理",
                "─" * 80,
                "  /list [today|week|month|pending|completed|overdue|upcoming]",
                "  /add [high|medium|low] <标题>",
                "  /today",
                "  /plan day",
                "  /search <关键词>",
                "  /toggle <ID>",
                "  /update <ID> [title|end_time|priority] <值>",
                "  /delete <ID>",
                "  /stats",
                "  /clear",
            ])
        if topic == "work":
            return "\n".join([
                "📖 工作流 / 证据",
                "─" * 80,
                "  /sync [path]",
                "  /sync --dry-run [path]",
                "  /sync status",
                "  /work status",
                "  /work conflicts",
                "  /work add <标题>",
                "  /work import redmine <id>",
                "  /work split <work-id> <source> <source-ref> [title]",
                "  /work rollback <work-id> <audit-id>",
                "  /work show <work-id>",
                "  /work evidence add <work-id> <摘要>",
                "  /work evidence summary <work-id>",
                "  /work evidence timeline <work-id>",
                "  /codex tasks",
                "  /next",
                "  /review",
                "",
                "兼容命令:",
                "  /continue    等同 /next",
                "  /review day  等同 /review",
                "  /start day",
            ])
        if topic in ("prefs", "preference", "preferences"):
            return "\n".join([
                "📖 长期偏好",
                "─" * 80,
                "  /preferences",
                "  /remember <偏好名> <偏好内容>",
                "  /forget <偏好名>",
            ])
        if topic == "system":
            return "\n".join([
                "📖 系统 / 历史",
                "─" * 80,
                "  /history",
                "  /exit 或 /quit",
                "",
                "退出方式:",
                "  - 输入 /exit 或 /quit",
                "  - 按两次 Ctrl+C",
                "  - 按 Ctrl+D (EOF)",
                "",
                "颜色含义:",
                "  🔴 红色: 高优先级 / 已过期",
                "  🟠 橙色: 即将到期（2天内）",
                "  🟡 黄色: 中优先级",
                "  🟢 绿色: 低优先级 / 正常",
                "  灰色: 已完成",
            ])
        return "用法: /help [todo|work|prefs|system]"

    def _startup_panel_text(self):
        return """
TodoAgent CLI

日常主命令
/list    统一任务视图
/sync    同步最新工作上下文
/next    推荐下一步
/review  生成今日复盘
/help    查看帮助

分类帮助
/help todo    Todo 管理命令
/help work    工作流、证据和兼容命令
/help prefs   长期偏好命令
/help system  历史、退出和颜色说明

也可以直接输入自然语言。
"""

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
        with self.console.status("[cyan]Thinking...[/cyan]") as status:
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
                response = self.agent.chat(text, stream=True, on_stream_chunk=on_stream_chunk)
                if response and not full_response:
                    sys.stdout.write(response)
                    full_response.append(response)
                sys.stdout.write("\n")
                sys.stdout.flush()
                return ""
            except Exception as e:
                error_msg = f"处理请求时出错: {e}"
                self.console.print(error_msg)
                return ""

    def _display_response(self, response):
        """显示响应"""
        if response == "exit":
            return False

        # 对于非空响应，需要显示
        if response:
            if not isinstance(response, str):
                self.console.print(response)
                return True

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
            return input(PROMPT_ANSI)

        try:
            return self.session.prompt(self.prompt_str)
        except Exception as e:
            self.console.print(f"[yellow]切换到简化输入模式: {e}[/yellow]")
            self.use_simple_input = True
            return input(PROMPT_ANSI)

    def run(self):
        """运行 CLI"""
        self.console.print(Panel(self._startup_panel_text(), title="[bold cyan]TodoAgent[/bold cyan]", style="grey50", border_style="grey50"))

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


def _dedupe_work_items(items):
    seen_identities = set()
    deduped = []
    for item in items:
        identities = [identity for identity in getattr(item, "source_identities", []) if identity]
        if identities and any(identity in seen_identities for identity in identities):
            continue
        deduped.append(item)
        seen_identities.update(identities)
    return deduped


def _daily_triage_work_item_rows(items):
    grouped = {name: [] for name in _DAILY_TRIAGE_GROUPS}
    for item in items:
        group = _daily_triage_group(item)
        if not group:
            continue
        grouped[group].append(item)

    rows = []
    for group in _DAILY_TRIAGE_GROUPS:
        limit = 5 if group == "recently completed" else None
        candidates = _sort_work_items_for_triage(grouped[group])
        if limit:
            candidates = candidates[:limit]
        for item in candidates:
            reason = _work_item_triage_reason(item)
            stale = _is_work_item_stale_today(item)
            reason_text = f"{reason} [stale]" if stale and item.status != WorkItemStatus.DONE.value else reason
            status_style = "yellow" if item.status == "blocked" else "grey50" if item.status == "done" else "cyan"
            rows.append(
                {
                    "group": group,
                    "id": item.id[:8],
                    "source": item.source,
                    "priority": _priority_marker(item.priority),
                    "title": Text(item.title, style="grey50" if item.status == "done" else "default"),
                    "status": Text(item.status, style=status_style),
                    "reason": Text(reason_text),
                    "next": item.next_action or item.sync_summary or "-",
                }
            )
    return rows


_DAILY_TRIAGE_GROUPS = [
    "blocked",
    "active needs action",
    "waiting closeout",
    "stale sync",
    "recently completed",
    "todo reminders",
]


def _daily_triage_group(item):
    if item.status == WorkItemStatus.ARCHIVED.value:
        return ""
    if item.status == WorkItemStatus.DONE.value:
        return "recently completed"
    reason = _work_item_triage_reason(item)
    stale = _is_work_item_stale_today(item)
    if item.status == WorkItemStatus.BLOCKED.value:
        return "blocked"
    if reason in {
        "MR merged but closeout missing",
        "Redmine closeout missing",
        "OpenSpec closeout missing",
    }:
        return "waiting closeout"
    if item.next_action or item.merge_conflicts or reason in {
        "needs validation",
        "merge conflict needs manual resolution",
    }:
        return "active needs action"
    if stale:
        return "stale sync"
    if reason == "Codex thread still active":
        return "active needs action"
    return "active needs action" if item.status == WorkItemStatus.ACTIVE.value else ""


def _work_item_triage_reason(item):
    if item.status == WorkItemStatus.DONE.value:
        return "recently completed"
    text = _work_item_context_text(item)
    if item.merge_conflicts:
        return "merge conflict needs manual resolution"
    if item.status == WorkItemStatus.BLOCKED.value and _mentions(text, "redmine"):
        return "blocked by Redmine"
    if item.status == WorkItemStatus.BLOCKED.value and _mentions(text, "mr", "gitlab", "merge_request"):
        return "blocked by MR"
    if item.status == WorkItemStatus.BLOCKED.value and _mentions(text, "openspec"):
        return "blocked by OpenSpec"
    if _mentions(text, "mr", "gitlab", "!") and _mentions(text, "merged") and _mentions(text, "closeout", "missing"):
        return "MR merged but closeout missing"
    if _mentions(text, "redmine") and _mentions(text, "closeout", "closed_loop", "resolution", "missing"):
        return "Redmine closeout missing"
    if _mentions(text, "openspec") and _mentions(text, "archive", "validate", "tasks", "closeout", "missing"):
        return "OpenSpec closeout missing"
    if _mentions(text, "validation", "validate", "verify", "test", "unittest", "review", "acceptance"):
        return "needs validation"
    if item.source == "codex" or any(identity.startswith("codex-thread:") for identity in item.source_identities):
        if item.status == WorkItemStatus.ACTIVE.value:
            return "Codex thread still active"
    if _is_work_item_stale_today(item):
        return "sync stale"
    return "blocked" if item.status == WorkItemStatus.BLOCKED.value else "needs action"


def _work_item_context_text(item):
    refs = [
        f"{ref.get('source', '')}:{ref.get('source_ref', '')}"
        for ref in item.source_refs
        if isinstance(ref, dict)
    ]
    parts = [
        item.source,
        item.source_ref,
        item.title,
        item.next_action,
        item.sync_summary,
        *item.source_identities,
        *refs,
        *item.merge_conflicts,
    ]
    return " ".join(str(part) for part in parts if part).lower()


def _mentions(text, *needles):
    return any(needle.lower() in text for needle in needles)


def _is_work_item_stale_today(item):
    if item.status not in {WorkItemStatus.ACTIVE.value, WorkItemStatus.BLOCKED.value}:
        return False
    if not item.last_synced_at:
        return True
    parsed = _parse_work_item_datetime(item.last_synced_at)
    if not parsed:
        return True
    return parsed.date() < datetime.now().date()


def _sort_work_items_for_triage(items):
    return sorted(items, key=_work_item_sort_key)


def _work_item_sort_key(item):
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    status_rank = {WorkItemStatus.BLOCKED.value: 0, WorkItemStatus.ACTIVE.value: 1, WorkItemStatus.DONE.value: 2}
    parsed = _parse_work_item_datetime(item.updated_at) or datetime(1970, 1, 1)
    recency = -(parsed - datetime(1970, 1, 1)).total_seconds()
    return (
        priority_rank.get(item.priority, 1),
        status_rank.get(item.status, 3),
        recency,
    )


def _parse_work_item_datetime(value):
    if not value:
        return None
    text = str(value).strip()
    formats = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]
    for fmt in formats:
        try:
            return datetime.strptime(text[:19] if fmt.endswith("%S") else text[:16] if fmt.endswith("%M") else text[:10], fmt)
        except ValueError:
            continue
    return None


def _priority_marker(priority):
    return {
        "high": "🔴",
        "medium": "🟡",
        "low": "🟢",
    }.get(priority, "")


def _parse_source_filter(args):
    tokens = args.split()
    if "--source" not in tokens:
        return ""
    index = tokens.index("--source")
    if index + 1 >= len(tokens):
        return ""
    return tokens[index + 1].strip().lower()


def _parse_sync_options(subcmd, args):
    tokens = [part for part in [subcmd, *args.split()] if part]
    dry_run = False
    status = False
    path_parts = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"--dry-run", "-n"}:
            dry_run = True
        elif token == "status":
            status = True
        else:
            path_parts.append(token)
        index += 1
    return {
        "dry_run": dry_run,
        "status": status,
        "path": " ".join(path_parts).strip(),
    }


if __name__ == "__main__":
    main()

