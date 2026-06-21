"""SQLite 待办事项仓储。"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from ai_todo_assistant.domain.models import Todo


class SQLiteTodoRepository:
    """使用 SQLite 持久化待办事项。"""

    def __init__(self, db_path: str = "data/todos.db"):
        self.db_path = db_path
        db_dir = os.path.dirname(os.path.abspath(db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._init_schema()

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
        self._insert(todo)
        return todo

    def add_existing(self, todo: Todo) -> bool:
        """迁移数据时按原 ID 写入，已存在则跳过。"""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO todos (
                    id, title, description, start_time, end_time, priority,
                    completed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._todo_params(todo, updated_at=None),
            )
            return cursor.rowcount > 0

    def delete(self, todo_id: str) -> bool:
        """按 ID 删除待办事项。"""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
            return cursor.rowcount > 0

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

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE todos
                   SET title = ?,
                       description = ?,
                       start_time = ?,
                       end_time = ?,
                       priority = ?,
                       completed = ?,
                       created_at = ?,
                       updated_at = ?
                 WHERE id = ?
                """,
                (
                    todo.title,
                    todo.description,
                    todo.start_time,
                    todo.end_time,
                    todo.priority,
                    int(todo.completed),
                    todo.created_at,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    todo.id,
                ),
            )
        return todo

    def toggle_completed(self, todo_id: str) -> Optional[Todo]:
        """切换完成状态。"""
        todo = self.get_by_id(todo_id)
        if not todo:
            return None
        todo.toggle_completed()
        with self._connect() as conn:
            conn.execute(
                "UPDATE todos SET completed = ?, updated_at = ? WHERE id = ?",
                (int(todo.completed), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), todo.id),
            )
        return todo

    def get_by_id(self, todo_id: str) -> Optional[Todo]:
        """根据 ID 获取待办事项。"""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        return self._row_to_todo(row) if row else None

    def get_all(self) -> List[Todo]:
        """返回所有待办事项。"""
        return self._query("SELECT * FROM todos ORDER BY created_at ASC, id ASC")

    def get_by_date(self, date: str) -> List[Todo]:
        """获取指定日期截止的待办事项。"""
        return self._query("SELECT * FROM todos WHERE end_time LIKE ? ORDER BY end_time ASC", (f"{date}%",))

    def get_tasks_on_date(self, date_str: str) -> List[Todo]:
        """获取指定日期开始、截止或正在进行中的任务。"""
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return []

        result = []
        for todo in self.get_all():
            start_date = self._date_part(todo.start_time)
            end_date = self._date_part(todo.end_time)
            if (start_date and start_date == target_date) or (end_date and end_date == target_date):
                result.append(todo)
            elif start_date and end_date and start_date < target_date < end_date:
                result.append(todo)
        return result

    def get_created_on(self, date: str) -> List[Todo]:
        return self._query("SELECT * FROM todos WHERE created_at LIKE ? ORDER BY created_at ASC", (f"{date}%",))

    def get_due_on(self, date: str) -> List[Todo]:
        return self.get_by_date(date)

    def get_by_status(self, completed: bool) -> List[Todo]:
        return self._query("SELECT * FROM todos WHERE completed = ? ORDER BY created_at ASC", (int(completed),))

    def get_overdue(self) -> List[Todo]:
        return [todo for todo in self.get_all() if todo.is_overdue()]

    def get_upcoming(self, days: int = 2) -> List[Todo]:
        now = datetime.now()
        deadline = now + timedelta(days=days)
        result = []
        for todo in self.get_all():
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
        for todo in self.get_all():
            end_dt = self._parse_datetime(todo.end_time) if todo.end_time else None
            if end_dt and start_of_week.date() <= end_dt.date() <= end_of_week.date():
                result.append(todo)
        return result

    def get_this_month(self) -> List[Todo]:
        now = datetime.now()
        return self._query(
            "SELECT * FROM todos WHERE end_time LIKE ? ORDER BY end_time ASC",
            (f"{now.year}-{now.month:02d}%",),
        )

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
        pattern = f"%{keyword.lower()}%"
        return self._query(
            """
            SELECT * FROM todos
             WHERE lower(title) LIKE ? OR lower(description) LIKE ?
             ORDER BY created_at ASC
            """,
            (pattern, pattern),
        )

    def get_by_priority(self, priority: str) -> List[Todo]:
        return self._query("SELECT * FROM todos WHERE priority = ? ORDER BY created_at ASC", (priority,))

    def get_statistics(self) -> dict:
        total = len(self.get_all())
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

    def clear_completed(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM todos WHERE completed = 1")
            return cursor.rowcount

    def remember_preference(self, key: str, value: str) -> None:
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError("偏好名称不能为空")
        if not value:
            raise ValueError("偏好内容不能为空")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO assistant_preferences (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )

    def list_preferences(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key, value FROM assistant_preferences ORDER BY key ASC"
            ).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def forget_preference(self, key: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM assistant_preferences WHERE key = ?", (key.strip(),))
            return cursor.rowcount > 0

    def is_empty(self) -> bool:
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM todos").fetchone()[0]
        return count == 0

    def _insert(self, todo: Todo) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO todos (
                    id, title, description, start_time, end_time, priority,
                    completed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._todo_params(todo, updated_at=None),
            )

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS todos (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    start_time TEXT,
                    end_time TEXT,
                    priority TEXT NOT NULL DEFAULT 'medium',
                    completed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_todos_completed ON todos(completed)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_todos_end_time ON todos(end_time)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_todos_priority ON todos(priority)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_todos_created_at ON todos(created_at)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS assistant_preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def _query(self, sql: str, params: tuple = ()) -> List[Todo]:
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_todo(row) for row in rows]

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _todo_params(todo: Todo, updated_at: Optional[str]) -> tuple:
        return (
            todo.id,
            todo.title,
            todo.description,
            todo.start_time,
            todo.end_time,
            todo.priority,
            int(todo.completed),
            todo.created_at,
            updated_at,
        )

    @staticmethod
    def _row_to_todo(row: sqlite3.Row) -> Todo:
        return Todo(
            title=row["title"],
            description=row["description"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            completed=bool(row["completed"]),
            todo_id=row["id"],
            created_at=row["created_at"],
            priority=row["priority"],
        )

    @staticmethod
    def _parse_datetime(value: str) -> Optional[datetime]:
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
