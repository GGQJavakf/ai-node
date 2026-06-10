"""
待办事项管理器单元测试
"""
import unittest
import os
import json
from datetime import datetime, timedelta

import _path  # noqa: F401
from ai_todo_assistant.domain.models import Todo
from ai_todo_assistant.infrastructure.persistence import TodoManager


class TestTodo(unittest.TestCase):
    """测试Todo类"""
    
    def test_create_todo(self):
        """测试创建待办事项"""
        todo = Todo("测试任务", "这是一个测试", "2026-12-31")
        
        self.assertEqual(todo.title, "测试任务")
        self.assertEqual(todo.description, "这是一个测试")
        self.assertEqual(todo.due_date, "2026-12-31")
        self.assertFalse(todo.completed)
        self.assertIsNotNone(todo.id)
        self.assertIsNotNone(todo.created_at)
    
    def test_empty_title(self):
        """测试空标题"""
        with self.assertRaises(ValueError):
            Todo("", "描述")
    
    def test_invalid_date(self):
        """测试无效日期"""
        with self.assertRaises(ValueError):
            Todo("任务", "", "2026-13-01")  # 无效月份
        
        with self.assertRaises(ValueError):
            Todo("任务", "", "2026/12/31")  # 错误格式
    
    def test_toggle_completed(self):
        """测试切换完成状态"""
        todo = Todo("任务")
        self.assertFalse(todo.completed)
        
        todo.toggle_completed()
        self.assertTrue(todo.completed)
        
        todo.toggle_completed()
        self.assertFalse(todo.completed)
    
    def test_is_overdue(self):
        """测试过期检查"""
        # 过去的日期
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        todo = Todo("任务", due_date=yesterday)
        self.assertTrue(todo.is_overdue())
        
        # 未来的日期
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        todo = Todo("任务", due_date=tomorrow)
        self.assertFalse(todo.is_overdue())
        
        # 已完成的不算过期
        todo = Todo("任务", due_date=yesterday, completed=True)
        self.assertFalse(todo.is_overdue())
    
    def test_to_dict(self):
        """测试序列化"""
        todo = Todo("任务", "描述", "2026-12-31")
        data = todo.to_dict()
        
        self.assertEqual(data["title"], "任务")
        self.assertEqual(data["description"], "描述")
        self.assertEqual(data["due_date"], "2026-12-31")
        self.assertFalse(data["completed"])
    
    def test_from_dict(self):
        """测试反序列化"""
        data = {
            "id": "test-id",
            "title": "任务",
            "description": "描述",
            "due_date": "2026-12-31",
            "completed": True,
            "created_at": "2026-01-01 00:00:00"
        }
        
        todo = Todo.from_dict(data)
        
        self.assertEqual(todo.id, "test-id")
        self.assertEqual(todo.title, "任务")
        self.assertEqual(todo.description, "描述")
        self.assertEqual(todo.due_date, "2026-12-31")
        self.assertTrue(todo.completed)


class TestTodoManager(unittest.TestCase):
    """测试TodoManager类"""
    
    def setUp(self):
        """测试前准备"""
        self.test_file = "test_todos.json"
        self.manager = TodoManager(self.test_file)
    
    def tearDown(self):
        """测试后清理"""
        if os.path.exists(self.test_file):
            os.remove(self.test_file)
    
    def test_add_todo(self):
        """测试添加待办事项"""
        todo = self.manager.add("任务1", "描述1", "2026-12-31")
        
        self.assertEqual(len(self.manager.get_all()), 1)
        self.assertEqual(todo.title, "任务1")
    
    def test_delete_todo(self):
        """测试删除待办事项"""
        todo = self.manager.add("任务1")
        self.assertEqual(len(self.manager.get_all()), 1)
        
        result = self.manager.delete(todo.id)
        self.assertTrue(result)
        self.assertEqual(len(self.manager.get_all()), 0)
        
        # 删除不存在的
        result = self.manager.delete("non-existent")
        self.assertFalse(result)
    
    def test_update_todo(self):
        """测试更新待办事项"""
        todo = self.manager.add("原标题", "原描述")
        
        updated = self.manager.update(todo.id, title="新标题")
        self.assertEqual(updated.title, "新标题")
        self.assertEqual(updated.description, "原描述")
        
        updated = self.manager.update(todo.id, description="新描述")
        self.assertEqual(updated.description, "新描述")
    
    def test_toggle_completed(self):
        """测试切换完成状态"""
        todo = self.manager.add("任务1")
        self.assertFalse(todo.completed)
        
        self.manager.toggle_completed(todo.id)
        updated = self.manager.get_by_id(todo.id)
        self.assertTrue(updated.completed)
    
    def test_get_by_status(self):
        """测试按状态筛选"""
        todo1 = self.manager.add("任务1")
        todo2 = self.manager.add("任务2")
        self.manager.toggle_completed(todo1.id)
        
        completed = self.manager.get_by_status(True)
        pending = self.manager.get_by_status(False)
        
        self.assertEqual(len(completed), 1)
        self.assertEqual(len(pending), 1)
    
    def test_get_by_date(self):
        """测试按日期筛选"""
        self.manager.add("任务1", due_date="2026-01-01")
        self.manager.add("任务2", due_date="2026-01-01")
        self.manager.add("任务3", due_date="2026-01-02")
        
        todos = self.manager.get_by_date("2026-01-01")
        self.assertEqual(len(todos), 2)
    
    def test_get_overdue(self):
        """测试获取过期任务"""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        self.manager.add("过期任务", due_date=yesterday)
        self.manager.add("未来任务", due_date=tomorrow)
        
        overdue = self.manager.get_overdue()
        self.assertEqual(len(overdue), 1)
    
    def test_get_by_month(self):
        """测试按月份获取"""
        self.manager.add("任务1", due_date="2026-01-15")
        self.manager.add("任务2", due_date="2026-01-20")
        self.manager.add("任务3", due_date="2026-02-10")
        
        todos_by_date = self.manager.get_by_month(2026, 1)
        self.assertEqual(len(todos_by_date), 2)
        self.assertIn("2026-01-15", todos_by_date)
        self.assertIn("2026-01-20", todos_by_date)
    
    def test_statistics(self):
        """测试统计功能"""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        todo1 = self.manager.add("任务1")
        todo2 = self.manager.add("任务2", due_date=yesterday)
        self.manager.toggle_completed(todo1.id)
        
        stats = self.manager.get_statistics()
        
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["completed"], 1)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["overdue"], 1)
    
    def test_save_and_load(self):
        """测试保存和加载"""
        self.manager.add("任务1", "描述1", "2026-12-31")
        self.manager.add("任务2", "描述2")
        
        # 创建新管理器,应该能加载数据
        new_manager = TodoManager(self.test_file)
        self.assertEqual(len(new_manager.get_all()), 2)
    
    def test_clear_completed(self):
        """测试清除已完成"""
        todo1 = self.manager.add("任务1")
        todo2 = self.manager.add("任务2")
        todo3 = self.manager.add("任务3")
        
        self.manager.toggle_completed(todo1.id)
        self.manager.toggle_completed(todo2.id)
        
        cleared = self.manager.clear_completed()
        
        self.assertEqual(cleared, 2)
        self.assertEqual(len(self.manager.get_all()), 1)


if __name__ == "__main__":
    unittest.main()
