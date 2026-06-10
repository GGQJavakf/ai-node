"""
日历视图模块
提供月历显示和日期导航功能
"""
import calendar
from datetime import datetime
from typing import Dict, List
from ai_todo_assistant.domain.models import Todo


class CalendarView:
    """日历视图类"""
    
    def __init__(self):
        """初始化日历视图"""
        self.calendar = calendar.TextCalendar(calendar.MONDAY)
    
    def format_month(
        self,
        year: int,
        month: int,
        todos_by_date: Dict[str, List[Todo]]
    ) -> str:
        """
        格式化月历,标注有待办事项的日期
        
        Args:
            year: 年份
            month: 月份
            todos_by_date: 按日期分组的待办事项字典
            
        Returns:
            格式化的月历字符串
        """
        # 获取月历
        month_calendar = self.calendar.monthdayscalendar(year, month)
        month_name = f"{year}年{month}月"
        
        # 构建表头
        lines = []
        lines.append("=" * 50)
        lines.append(month_name.center(50))
        lines.append("=" * 50)
        lines.append("  一   二   三   四   五   六   日")
        lines.append("-" * 50)
        
        # 构建日历主体
        for week in month_calendar:
            week_str = ""
            for day in week:
                if day == 0:
                    week_str += "    "
                else:
                    date_str = f"{year:04d}-{month:02d}-{day:02d}"
                    # 检查该日期是否有待办事项
                    if date_str in todos_by_date:
                        # 用*标记有待办事项的日期
                        week_str += f"{day:2d}* "
                    else:
                        week_str += f"{day:2d}  "
            lines.append(week_str)
        
        lines.append("=" * 50)
        lines.append("提示: 带*的日期有待办事项")
        
        return "\n".join(lines)
    
    def show_todos_for_date(self, date: str, todos: List[Todo]) -> str:
        """
        显示指定日期的待办事项
        
        Args:
            date: 日期字符串
            todos: 待办事项列表
            
        Returns:
            格式化的待办事项列表
        """
        if not todos:
            return f"\n{date} 没有待办事项\n"
        
        lines = []
        lines.append(f"\n{date} 的待办事项:")
        lines.append("-" * 50)
        
        for i, todo in enumerate(todos, 1):
            status = "✓" if todo.completed else "✗"
            lines.append(f"{i}. [{status}] {todo.title}")
            if todo.description:
                lines.append(f"   描述: {todo.description}")
        
        lines.append("-" * 50)
        return "\n".join(lines)
    
    @staticmethod
    def get_current_month() -> tuple:
        """获取当前年月"""
        now = datetime.now()
        return now.year, now.month
    
    @staticmethod
    def get_next_month(year: int, month: int) -> tuple:
        """获取下一个月"""
        if month == 12:
            return year + 1, 1
        return year, month + 1
    
    @staticmethod
    def get_prev_month(year: int, month: int) -> tuple:
        """获取上一个月"""
        if month == 1:
            return year - 1, 12
        return year, month - 1
    
    def show_month_summary(
        self,
        year: int,
        month: int,
        todos_by_date: Dict[str, List[Todo]]
    ) -> str:
        """
        显示月度摘要
        
        Args:
            year: 年份
            month: 月份
            todos_by_date: 按日期分组的待办事项字典
            
        Returns:
            月度摘要字符串
        """
        total_todos = sum(len(todos) for todos in todos_by_date.values())
        total_days = len(todos_by_date)
        
        completed_count = 0
        pending_count = 0
        
        for todos in todos_by_date.values():
            for todo in todos:
                if todo.completed:
                    completed_count += 1
                else:
                    pending_count += 1
        
        lines = []
        lines.append(f"\n{year}年{month}月 待办事项摘要:")
        lines.append("-" * 50)
        lines.append(f"有待办事项的天数: {total_days}")
        lines.append(f"待办事项总数: {total_todos}")
        lines.append(f"已完成: {completed_count}")
        lines.append(f"未完成: {pending_count}")
        
        if total_todos > 0:
            completion_rate = (completed_count / total_todos) * 100
            lines.append(f"完成率: {completion_rate:.1f}%")
        
        lines.append("-" * 50)
        
        return "\n".join(lines)

