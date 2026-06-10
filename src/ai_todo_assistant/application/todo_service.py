"""
待办应用服务。

应用服务提供稳定的用例入口，避免 UI、Agent 工具或未来 API 层直接依赖
持久化实现细节。当前仍复用 TodoManager 的能力，后续切 SQLite 时只需替换仓储。
"""
from typing import Optional

from ai_todo_assistant.domain.models import Todo
from ai_todo_assistant.infrastructure.persistence.json_todo_repository import TodoManager


class TodoApplicationService:
    """面向上层接口的待办用例服务。"""

    def __init__(self, manager: Optional[TodoManager] = None):
        self.manager = manager or TodoManager()

    def create_todo(
        self,
        title: str,
        description: str = "",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        priority: str = "medium",
    ) -> Todo:
        return self.manager.add(title, description, start_time, end_time, priority)

    def update_todo(self, todo_id: str, **changes) -> Optional[Todo]:
        return self.manager.update(todo_id, **changes)

    def mark_completed(self, todo_id: str) -> Optional[Todo]:
        todo = self.manager.get_by_id(todo_id)
        if todo and not todo.completed:
            return self.manager.toggle_completed(todo_id)
        return todo

    def toggle_completed(self, todo_id: str) -> Optional[Todo]:
        return self.manager.toggle_completed(todo_id)

    def delete_todo(self, todo_id: str) -> bool:
        return self.manager.delete(todo_id)

    def list_todos(self):
        return self.manager.get_all()

    def search(self, keyword: str):
        return self.manager.search(keyword)

    def get_statistics(self) -> dict:
        return self.manager.get_statistics()

