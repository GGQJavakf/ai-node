"""
领域模型。

DDD 中领域层应该尽量保持纯粹：这里的 Todo 只负责表达待办事项本身的
业务状态和基础规则，不直接读写文件，也不调用 UI 或 LLM。
"""
from datetime import datetime, timedelta
from typing import Optional
import uuid


class Todo:
    """待办事项领域实体。"""

    def __init__(
        self,
        title: str,
        description: str = "",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        completed: bool = False,
        todo_id: Optional[str] = None,
        created_at: Optional[str] = None,
        due_date: Optional[str] = None,
        priority: str = "medium",
    ):
        self.id = todo_id or str(uuid.uuid4())
        self.title = title.strip()
        self.description = description.strip()

        # 兼容旧调用：历史版本把 due_date 当作截止时间，也允许把 start_time
        # 单独传入作为日期字段。这里集中兼容，避免上层散落同样判断。
        if start_time and end_time is None and due_date is None:
            due_date = start_time
            start_time = None
        self.start_time = start_time
        self.end_time = end_time or due_date
        self.priority = priority if priority in ["high", "medium", "low"] else "medium"
        self.completed = completed
        self.created_at = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not self.title:
            raise ValueError("待办事项标题不能为空")

        if self.start_time:
            self._validate_datetime(self.start_time)
        if self.end_time:
            self._validate_datetime(self.end_time)

    @staticmethod
    def _validate_datetime(dt_str: str) -> None:
        """验证支持的日期时间格式。"""
        try:
            if len(dt_str) <= 10:
                datetime.strptime(dt_str, "%Y-%m-%d")
            elif len(dt_str) > 16:
                datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            else:
                datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        except ValueError:
            raise ValueError(
                f"时间格式错误: {dt_str}, 应为 YYYY-MM-DD、YYYY-MM-DD HH:MM 或 YYYY-MM-DD HH:MM:SS"
            )

    def to_dict(self) -> dict:
        """转换为 JSON 可序列化字典。"""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "due_date": self.end_time,
            "priority": self.priority,
            "completed": self.completed,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Todo":
        """从持久化数据恢复领域实体。"""
        return cls(
            title=data["title"],
            description=data.get("description", ""),
            start_time=data.get("start_time"),
            end_time=data.get("end_time") or data.get("due_date"),
            completed=data.get("completed", False),
            todo_id=data.get("id"),
            created_at=data.get("created_at"),
            priority=data.get("priority", "medium"),
        )

    @property
    def due_date(self) -> Optional[str]:
        """旧版字段别名，等价于 end_time。"""
        return self.end_time

    @due_date.setter
    def due_date(self, value: Optional[str]) -> None:
        if value:
            self._validate_datetime(value)
        self.end_time = value

    def toggle_completed(self) -> None:
        """切换完成状态。"""
        self.completed = not self.completed

    def is_overdue(self) -> bool:
        """检查是否已过期且未完成。"""
        if not self.end_time or self.completed:
            return False

        try:
            fmt = "%Y-%m-%d %H:%M:%S" if len(self.end_time) > 16 else "%Y-%m-%d %H:%M" if ":" in self.end_time else "%Y-%m-%d"
            due = datetime.strptime(self.end_time, fmt)
            return due < datetime.now()
        except ValueError:
            return False

    def is_urgent(self) -> bool:
        """检查是否在 24 小时内到期且未完成。"""
        if not self.end_time or self.completed:
            return False

        try:
            fmt = "%Y-%m-%d %H:%M:%S" if len(self.end_time) > 16 else "%Y-%m-%d %H:%M" if ":" in self.end_time else "%Y-%m-%d"
            due = datetime.strptime(self.end_time, fmt)
            diff = due - datetime.now()
            return timedelta(0) < diff <= timedelta(hours=24)
        except ValueError:
            return False

    def __str__(self) -> str:
        status = "✓" if self.completed else "✗"
        due_info = f" (截止: {self.end_time})" if self.end_time else ""
        overdue = " [已过期]" if self.is_overdue() else ""
        urgent = " [即将到期]" if self.is_urgent() else ""
        return f"[{status}] {self.title}{due_info}{overdue}{urgent}"

    def __repr__(self) -> str:
        return f"Todo(id={self.id}, title='{self.title}', completed={self.completed})"


