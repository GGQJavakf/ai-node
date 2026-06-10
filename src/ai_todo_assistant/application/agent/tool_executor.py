"""Agent 工具执行器。"""
from typing import Any

from ai_todo_assistant.infrastructure.persistence.json_todo_repository import TodoManager


class ToolExecutor:
    """
    将 LLM 返回的工具调用映射到本地用例。

    这一层是 Agent 与业务能力的边界：LLM 只能看到工具名和参数，
    真正的数据变更仍由本地应用代码执行。
    """

    def __init__(self, manager: TodoManager):
        self.manager = manager
        self._dispatch: dict[str, Any] = {
            "list_todos": self._list_todos,
            "add_todo": self._add_todo,
            "delete_todos": self._delete_todos,
            "toggle_todo": self._toggle_todo,
            "update_todo": self._update_todo,
            "search_todos": self._search_todos,
            "get_statistics": self._get_statistics,
            "clear_completed": self._clear_completed,
        }

    def execute(self, tool_name: str, tool_args: dict) -> str:
        """执行工具调用，统一把结果返回为 LLM 可理解的字符串。"""
        handler = self._dispatch.get(tool_name)
        if not handler:
            return f"[错误] 未知工具: {tool_name}"
        try:
            return handler(**tool_args)
        except TypeError as e:
            return f"[参数错误] 调用 {tool_name} 失败: {e}"
        except Exception as e:
            return f"[执行错误] {tool_name} 执行异常: {e}"

    def _list_todos(self, filter: str = "all", time_range: str = "all", priority: str = "all") -> str:
        if time_range == "today":
            todos = self.manager.get_today()
        elif time_range == "week":
            todos = self.manager.get_this_week()
        elif time_range == "month":
            todos = self.manager.get_this_month()
        else:
            todos = self.manager.get_all()

        if filter == "pending":
            todos = [t for t in todos if not t.completed]
        elif filter == "completed":
            todos = [t for t in todos if t.completed]
        elif filter == "overdue":
            todos = [t for t in todos if t.is_overdue()]
        elif filter == "upcoming":
            todos = self.manager.get_upcoming()

        if priority != "all":
            todos = [t for t in todos if t.priority == priority]

        if not todos:
            return "当前没有符合条件的待办事项。"

        lines = []
        for i, t in enumerate(todos, 1):
            status = "✓已完成" if t.completed else "○未完成"
            priority_marker = {
                "high": "🔴",
                "medium": "🟡",
                "low": "🟢",
            }.get(t.priority, "")
            due = f" | 截止:{t.end_time}" if t.end_time else ""
            lines.append(f"{i}. [{status}] {priority_marker} {t.title}{due} (ID:{t.id})")
        return "\n".join(lines)

    def _add_todo(
        self,
        title: str,
        description: str = "",
        start_time: str = None,
        end_time: str = None,
        priority: str = "medium",
    ) -> str:
        todo = self.manager.add(
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            priority=priority,
        )
        return f"成功新增待办事项：「{todo.title}」(ID:{todo.id})"

    def _delete_todos(self, ids: list) -> str:
        results = []
        for tid in ids:
            if self.manager.delete(tid):
                results.append(f"  ✓ 已删除 ID:{tid}")
            else:
                results.append(f"  ✗ 未找到 ID:{tid}")
        return "删除操作完成：\n" + "\n".join(results)

    def _toggle_todo(self, id: str) -> str:
        todo = self.manager.toggle_completed(id)
        if not todo:
            return f"未找到 ID 为 {id} 的待办事项"
        status = "已完成" if todo.completed else "未完成"
        return f"已将「{todo.title}」标记为【{status}】"

    def _update_todo(
        self,
        id: str,
        title: str = None,
        description: str = None,
        start_time: str = None,
        end_time: str = None,
        priority: str = None,
    ) -> str:
        todo = self.manager.update(
            todo_id=id,
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            priority=priority,
        )
        if not todo:
            return f"未找到 ID 为 {id} 的待办事项"
        return f"已成功更新「{todo.title}」"

    def _search_todos(self, keyword: str) -> str:
        todos = self.manager.search(keyword)
        if not todos:
            return f"未找到包含「{keyword}」的待办事项。"

        lines = []
        for i, t in enumerate(todos, 1):
            status = "✓已完成" if t.completed else "○未完成"
            due = f" | 截止:{t.end_time}" if t.end_time else ""
            lines.append(f"{i}. [{status}] {t.title}{due} (ID:{t.id})")
        return "\n".join(lines)

    def _get_statistics(self) -> str:
        s = self.manager.get_statistics()
        return (
            f"当前待办统计：\n"
            f"  总计：{s['total']} 条\n"
            f"  已完成：{s['completed']} 条\n"
            f"  未完成：{s['pending']} 条\n"
            f"  已过期：{s['overdue']} 条\n"
            f"  即将到期：{s['upcoming']} 条\n"
            f"  完成率：{s['completion_rate']}"
        )

    def _clear_completed(self) -> str:
        count = self.manager.clear_completed()
        return f"已清除 {count} 条已完成的待办事项。"


