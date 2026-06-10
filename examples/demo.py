"""
待办事项管理工具演示脚本
自动添加一些示例数据并展示各种功能
"""
from datetime import datetime, timedelta
from pathlib import Path

from ai_todo_assistant.infrastructure.persistence import TodoManager
from ai_todo_assistant.presentation.calendar_view import CalendarView


def demo():
    """运行演示"""
    print("=" * 60)
    print("待办事项管理工具演示".center(60))
    print("=" * 60)
    
    # 创建管理器
    demo_data_file = Path(__file__).with_name("demo_todos.json")
    manager = TodoManager(str(demo_data_file))
    calendar_view = CalendarView()
    
    # 清空现有数据
    manager.todos = []
    
    print("\n📝 添加示例待办事项...")
    
    # 添加一些示例数据
    today = datetime.now()
    tomorrow = today + timedelta(days=1)
    next_week = today + timedelta(days=7)
    yesterday = today - timedelta(days=1)
    
    todo1 = manager.add(
        title="完成项目报告",
        description="准备Q1季度项目总结报告,包含数据分析和图表",
        end_time=tomorrow.strftime("%Y-%m-%d")
    )
    
    todo2 = manager.add(
        title="团队会议",
        description="讨论下季度工作计划",
        end_time=today.strftime("%Y-%m-%d")
    )
    
    todo3 = manager.add(
        title="代码审查",
        description="审查新功能的代码实现",
        end_time=next_week.strftime("%Y-%m-%d")
    )
    
    todo4 = manager.add(
        title="更新文档",
        description="更新API文档和用户手册"
    )
    
    todo5 = manager.add(
        title="修复Bug #123",
        description="修复登录页面的显示问题",
        end_time=yesterday.strftime("%Y-%m-%d")
    )
    
    # 标记一些为已完成
    manager.toggle_completed(todo4.id)
    
    print(f"✅ 已添加 {len(manager.get_all())} 个待办事项\n")
    
    # 显示所有待办事项
    print("=" * 60)
    print("📋 所有待办事项")
    print("=" * 60)
    for i, todo in enumerate(manager.get_all(), 1):
        status = "✓" if todo.completed else "✗"
        print(f"{i}. [{status}] {todo.title}")
        if todo.description:
            print(f"   描述: {todo.description}")
        if todo.end_time:
            overdue = " [已过期]" if todo.is_overdue() else ""
            print(f"   截止: {todo.end_time}{overdue}")
        print()
    
    # 显示统计信息
    print("=" * 60)
    print("📊 统计信息")
    print("=" * 60)
    stats = manager.get_statistics()
    print(f"总计: {stats['total']}")
    print(f"已完成: {stats['completed']}")
    print(f"未完成: {stats['pending']}")
    print(f"已过期: {stats['overdue']}")
    print(f"完成率: {stats['completion_rate']}")
    print()
    
    # 显示未完成的任务
    print("=" * 60)
    print("⏳ 未完成的待办事项")
    print("=" * 60)
    pending = manager.get_by_status(False)
    for i, todo in enumerate(pending, 1):
        print(f"{i}. {todo.title}")
        if todo.end_time:
            print(f"   截止: {todo.end_time}")
    print()
    
    # 显示已过期的任务
    print("=" * 60)
    print("⚠️  已过期的待办事项")
    print("=" * 60)
    overdue = manager.get_overdue()
    if overdue:
        for i, todo in enumerate(overdue, 1):
            print(f"{i}. {todo.title} (截止: {todo.end_time})")
    else:
        print("暂无过期任务")
    print()
    
    # 显示日历视图
    print("=" * 60)
    print("📅 本月日历视图")
    print("=" * 60)
    year, month = CalendarView.get_current_month()
    todos_by_date = manager.get_by_month(year, month)
    
    calendar_str = calendar_view.format_month(year, month, todos_by_date)
    print(calendar_str)
    print()
    
    # 显示月度摘要
    summary = calendar_view.show_month_summary(year, month, todos_by_date)
    print(summary)
    
    print("\n" + "=" * 60)
    print("演示完成!".center(60))
    print("=" * 60)
    print("\n提示:")
    print("  - 运行 'python -m ai_todo_assistant' 启动命令行界面")
    print("  - 运行 'python -m ai_todo_assistant.presentation.gui' 启动图形界面")
    print("  - 数据已保存到 'demo_todos.json'")
    print()


if __name__ == "__main__":
    demo()

