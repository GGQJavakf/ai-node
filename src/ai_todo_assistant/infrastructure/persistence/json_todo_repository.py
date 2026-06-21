"""
JSON 持久化适配器。

默认版本已使用 SQLite。这个 JSON 仓储保留历史名称 `TodoManager`，
方便旧代码、测试和迁移场景兼容；从 DDD 视角看，它承担的是可替换的
仓储实现和查询服务职责。
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from ai_todo_assistant.domain.models import Todo


class TodoManager:
    """待办事项 JSON 仓储与查询服务。"""

    def __init__(self, data_file: str = "todos.json"):
        self.data_file = data_file
        self.preferences_file = self._preferences_file_for(data_file)
        self.todos: List[Todo] = []
        self.load()

    def add(
        self,
        title: str,
        description: str = "",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        priority: str = "medium",
        due_date: Optional[str] = None,
    ) -> Todo:
        """新增待办事项。"""
        if start_time and end_time is None and due_date is None:
            due_date = start_time
            start_time = None

        if end_time is None and due_date is not None:
            end_time = due_date

        if end_time is None:
            today = datetime.now().strftime("%Y-%m-%d")
            end_time = f"{today} 23:59:59"

        todo = Todo(
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            priority=priority,
        )
        self.todos.append(todo)
        self.save()
        return todo

    def delete(self, todo_id: str) -> bool:
        """按 ID 删除待办事项。"""
        for i, todo in enumerate(self.todos):
            if todo.id == todo_id:
                self.todos.pop(i)
                self.save()
                return True
        return False

    def update(
        self,
        todo_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> Optional[Todo]:
        """更新待办事项，未传入的字段保持不变。"""
        todo = self.get_by_id(todo_id)
        if not todo:
            return None

        if title is not None:
            if not title.strip():
                raise ValueError("标题不能为空")
            todo.title = title.strip()

        if description is not None:
            todo.description = description.strip()

        if start_time is not None:
            if start_time:
                Todo._validate_datetime(start_time)
            todo.start_time = start_time

        if end_time is not None:
            if end_time:
                Todo._validate_datetime(end_time)
            todo.end_time = end_time

        if priority is not None and priority in ["high", "medium", "low"]:
            todo.priority = priority

        self.save()
        return todo

    def toggle_completed(self, todo_id: str) -> Optional[Todo]:
        """切换完成状态。"""
        todo = self.get_by_id(todo_id)
        if todo:
            todo.toggle_completed()
            self.save()
        return todo

    def get_by_id(self, todo_id: str) -> Optional[Todo]:
        """根据 ID 获取待办事项。"""
        for todo in self.todos:
            if todo.id == todo_id:
                return todo
        return None

    def get_all(self) -> List[Todo]:
        """返回所有待办事项副本，避免调用方直接替换内部列表。"""
        return self.todos.copy()

    def get_by_date(self, date: str) -> List[Todo]:
        """获取指定日期截止的待办事项。"""
        return [todo for todo in self.todos if todo.end_time and todo.end_time.startswith(date)]

    def get_tasks_on_date(self, date_str: str) -> List[Todo]:
        """获取指定日期开始、截止或正在进行中的任务。"""
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return []

        result = []
        for todo in self.todos:
            start_date = self._date_part(todo.start_time)
            end_date = self._date_part(todo.end_time)

            if (start_date and start_date == target_date) or (end_date and end_date == target_date):
                result.append(todo)
            elif start_date and end_date and start_date < target_date < end_date:
                result.append(todo)
        return result

    def get_created_on(self, date: str) -> List[Todo]:
        return [todo for todo in self.todos if todo.created_at.startswith(date)]

    def get_due_on(self, date: str) -> List[Todo]:
        return [todo for todo in self.todos if todo.end_time and todo.end_time.startswith(date)]

    def get_by_status(self, completed: bool) -> List[Todo]:
        return [todo for todo in self.todos if todo.completed == completed]

    def get_overdue(self) -> List[Todo]:
        return [todo for todo in self.todos if todo.is_overdue()]

    def get_upcoming(self, days: int = 2) -> List[Todo]:
        now = datetime.now()
        deadline = now + timedelta(days=days)
        result = []

        for todo in self.todos:
            if todo.completed or not todo.end_time:
                continue
            end_dt = self._parse_datetime(todo.end_time)
            if end_dt and now < end_dt <= deadline:
                result.append(todo)
        return result

    def get_today(self) -> List[Todo]:
        today = datetime.now().strftime("%Y-%m-%d")
        return self.get_tasks_on_date(today)

    def get_this_week(self) -> List[Todo]:
        now = datetime.now()
        start_of_week = now - timedelta(days=now.weekday())
        end_of_week = start_of_week + timedelta(days=6)

        result = []
        for todo in self.todos:
            end_dt = self._parse_datetime(todo.end_time) if todo.end_time else None
            if end_dt and start_of_week.date() <= end_dt.date() <= end_of_week.date():
                result.append(todo)
        return result

    def get_this_month(self) -> List[Todo]:
        now = datetime.now()
        return [
            todo for todo in self.todos
            if todo.end_time and todo.end_time.startswith(f"{now.year}-{now.month:02d}")
        ]

    def get_by_month(self, year: int, month: int) -> Dict[str, List[Todo]]:
        import calendar

        _, num_days = calendar.monthrange(year, month)
        result = {}
        for day in range(1, num_days + 1):
            date_str = f"{year:04d}-{month:02d}-{day:02d}"
            tasks = self.get_tasks_on_date(date_str)
            if tasks:
                result[date_str] = tasks
        return result

    def search(self, keyword: str) -> List[Todo]:
        keyword = keyword.lower()
        return [
            todo for todo in self.todos
            if keyword in todo.title.lower() or (todo.description and keyword in todo.description.lower())
        ]

    def get_by_priority(self, priority: str) -> List[Todo]:
        return [todo for todo in self.todos if todo.priority == priority]

    def get_statistics(self) -> dict:
        total = len(self.todos)
        completed = len(self.get_by_status(True))
        pending = len(self.get_by_status(False))
        overdue = len(self.get_overdue())
        upcoming = len(self.get_upcoming())

        return {
            "total": total,
            "completed": completed,
            "pending": pending,
            "overdue": overdue,
            "upcoming": upcoming,
            "completion_rate": f"{(completed / total * 100):.1f}%" if total > 0 else "0%",
        }

    def save(self) -> None:
        """保存到 JSON 文件。仅用于兼容旧版存储后端。"""
        data = [todo.to_dict() for todo in self.todos]
        with open(self.data_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self) -> None:
        """从 JSON 文件加载数据。"""
        if not os.path.exists(self.data_file):
            self.todos = []
            return

        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.todos = [Todo.from_dict(item) for item in data]
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"警告: 加载数据文件失败: {e}")
            self.todos = []

    def clear_completed(self) -> int:
        original_count = len(self.todos)
        self.todos = [todo for todo in self.todos if not todo.completed]
        cleared_count = original_count - len(self.todos)
        if cleared_count > 0:
            self.save()
        return cleared_count

    def remember_preference(self, key: str, value: str) -> None:
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError("偏好名称不能为空")
        if not value:
            raise ValueError("偏好内容不能为空")
        preferences = self.list_preferences()
        preferences[key] = value
        self._save_preferences(preferences)

    def list_preferences(self) -> Dict[str, str]:
        if not os.path.exists(self.preferences_file):
            return {}
        try:
            with open(self.preferences_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return {
                str(key): str(value)
                for key, value in data.items()
                if str(key).strip() and str(value).strip()
            }
        except (OSError, json.JSONDecodeError):
            return {}

    def forget_preference(self, key: str) -> bool:
        preferences = self.list_preferences()
        removed = preferences.pop(key.strip(), None) is not None
        if removed:
            self._save_preferences(preferences)
        return removed

    def _save_preferences(self, preferences: Dict[str, str]) -> None:
        directory = os.path.dirname(os.path.abspath(self.preferences_file))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.preferences_file, "w", encoding="utf-8") as f:
            json.dump(preferences, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _preferences_file_for(data_file: str) -> str:
        base, _ = os.path.splitext(data_file)
        return f"{base}.preferences.json"

    @staticmethod
    def _parse_datetime(value: str) -> Optional[datetime]:
        """集中解析日期时间，减少各查询方法重复判断格式。"""
        if not value:
            return None
        try:
            fmt = "%Y-%m-%d %H:%M:%S" if len(value) > 16 else "%Y-%m-%d %H:%M" if ":" in value else "%Y-%m-%d"
            return datetime.strptime(value, fmt)
        except ValueError:
            return None

    @classmethod
    def _date_part(cls, value: Optional[str]):
        parsed = cls._parse_datetime(value) if value else None
        return parsed.date() if parsed else None


JsonTodoRepository = TodoManager

