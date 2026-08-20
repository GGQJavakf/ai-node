"""Agent 工具执行器。"""
from datetime import datetime
import os
from typing import Any

from ai_todo_assistant.application.ports import TodoRepository
from ai_todo_assistant.application.system_cli import SystemCliService, record_system_cli_evidence
from ai_todo_assistant.application.workflow import (
    CodexTaskReportService,
    ContinueService,
    DailyReviewService,
    EvidenceService,
    WorkItemService,
    WorkflowSyncService,
)
from ai_todo_assistant.infrastructure.persistence import build_workflow_repository


class ToolExecutor:
    """
    将 LLM 返回的工具调用映射到本地用例。

    这一层是 Agent 与业务能力的边界：LLM 只能看到工具名和参数，
    真正的数据变更仍由本地应用代码执行。
    """

    def __init__(
        self,
        manager: TodoRepository,
        config: dict | None = None,
        workflow_repository=None,
        system_cli_runner=None,
    ):
        self.manager = manager
        self.config = config or {}
        self.workflow_repository = workflow_repository or build_workflow_repository(self.config)
        self.system_cli_runner = system_cli_runner
        self._dispatch: dict[str, Any] = {
            "list_todos": self._list_todos,
            "add_todo": self._add_todo,
            "delete_todos": self._delete_todos,
            "toggle_todo": self._toggle_todo,
            "update_todo": self._update_todo,
            "search_todos": self._search_todos,
            "get_statistics": self._get_statistics,
            "clear_completed": self._clear_completed,
            "remember_preference": self._remember_preference,
            "list_preferences": self._list_preferences,
            "forget_preference": self._forget_preference,
            "create_work_item": self._create_work_item,
            "import_redmine_work_item": self._import_redmine_work_item,
            "list_work_status": self._list_work_status,
            "sync_workflow_context": self._sync_workflow_context,
            "recommend_next_work_action": self._recommend_next_work_action,
            "record_work_evidence": self._record_work_evidence,
            "summarize_work_evidence": self._summarize_work_evidence,
            "run_system_cli": self._run_system_cli,
            "read_codex_task_reports": self._read_codex_task_reports,
            "generate_daily_workflow_review": self._generate_daily_workflow_review,
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

    def _run_system_cli(
        self,
        command_key: str,
        cwd: str | None = None,
        reason: str = "",
        work_item_id: str | None = None,
        record_evidence: bool = False,
    ) -> str:
        service = SystemCliService(self.config, runner=self.system_cli_runner)
        record = service.run(command_key, cwd=cwd)
        lines = [service.format_for_tool(record)]
        if record_evidence and work_item_id:
            evidence_result = record_system_cli_evidence(self.workflow_repository, work_item_id, record)
            action = "recorded" if evidence_result.created else "reused"
            lines.append(f"Evidence {action}: {evidence_result.evidence.id}")
        return "\n".join(lines)

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
        start_time: str | None = None,
        end_time: str | None = None,
        priority: str = "medium",
    ) -> str:
        now = datetime.now()
        if start_time is None:
            start_time = now.strftime("%Y-%m-%d %H:%M:%S")
        if end_time is None:
            end_time = now.strftime("%Y-%m-%d 23:59:59")

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
        title: str | None = None,
        description: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        priority: str | None = None,
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

    def _remember_preference(self, key: str, value: str) -> str:
        self.manager.remember_preference(key, value)
        return f"已记住偏好：{key} = {value}"

    def _list_preferences(self) -> str:
        preferences = self.manager.list_preferences()
        if not preferences:
            return "当前还没有记住任何长期偏好。"
        return "已记住的偏好：\n" + "\n".join(
            f"  - {key}: {value}" for key, value in preferences.items()
        )

    def _forget_preference(self, key: str) -> str:
        if self.manager.forget_preference(key):
            return f"已忘记偏好：{key}"
        return f"未找到偏好：{key}"

    def _create_work_item(self, title: str, priority: str = "medium", next_action: str = "", project_path: str = "") -> str:
        item = WorkItemService(self.workflow_repository).create_manual(
            title=title,
            priority=priority,
            next_action=next_action,
            project_path=project_path,
        )
        return f"已创建工作项：{item.title} (ID:{item.id})"

    def _import_redmine_work_item(self, issue_id: str, project_path: str = "") -> str:
        try:
            item = WorkflowSyncService(self.workflow_repository).import_redmine(project_path or os.getcwd(), issue_id)
        except RuntimeError as exc:
            return f"Redmine 工作项导入失败：{exc}"
        return f"已导入 Redmine 工作项：{item.title} (ID:{item.id})"

    def _list_work_status(self) -> str:
        return WorkItemService(self.workflow_repository).status_summary()

    def _sync_workflow_context(self, project_path: str = "", openspec_change: str | None = None) -> str:
        snapshots = WorkflowSyncService(self.workflow_repository).sync_project(project_path or os.getcwd(), openspec_change)
        lines = []
        for snapshot in snapshots:
            status = "OK" if snapshot.success else "UNAVAILABLE"
            lines.append(f"[{status}] {snapshot.source}: {snapshot.summary}")
        return "\n".join(lines) if lines else "没有同步结果"

    def _recommend_next_work_action(self) -> str:
        return ContinueService(self.workflow_repository).recommend()

    def _record_work_evidence(
        self,
        work_item_id: str,
        evidence_type: str = "note",
        summary: str = "",
        command: str = "",
        output_excerpt: str = "",
        success: bool | None = None,
    ) -> str:
        evidence = EvidenceService(self.workflow_repository).record(
            work_item_id,
            evidence_type,
            summary,
            command=command,
            output_excerpt=output_excerpt,
            success=success,
        )
        return f"已记录证据：{evidence.summary}"

    def _summarize_work_evidence(self, work_item_id: str) -> str:
        return EvidenceService(self.workflow_repository).summarize(work_item_id)

    def _read_codex_task_reports(self, import_items: bool = True) -> str:
        report_dir = self.config.get("codex_task_report_dir", "data/codex-task-reports")
        if not os.path.isabs(report_dir):
            report_dir = os.path.join(self.config.get("project_root", os.getcwd()), report_dir)
        report = CodexTaskReportService(report_dir).latest_report()
        if not report:
            return f"暂无 Codex 任务报告: {report_dir}"
        imported = []
        if import_items:
            imported = WorkItemService(self.workflow_repository).import_codex_report(report)
        return (
            f"Codex 报告: {report.generated_at}\n"
            f"未完成/阻塞: {report.total_unfinished}\n"
            f"最近完成: {len(report.completed)}\n"
            f"已同步工作项: {len(imported)}"
        )

    def _generate_daily_workflow_review(self) -> str:
        return DailyReviewService(self.workflow_repository).review_day()


