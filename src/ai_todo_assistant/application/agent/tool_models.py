"""Agent 工具参数模型。"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Priority = Literal["high", "medium", "low"]
TodoFilter = Literal["all", "pending", "completed", "overdue", "upcoming"]
TimeRange = Literal["today", "week", "month", "all"]
PriorityFilter = Literal["high", "medium", "low", "all"]
EvidenceKind = Literal["command", "test", "note", "review", "link", "snapshot"]


def _strip_required_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("不能为空")
    return value


def _strip_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("不能为空")
    return value


def _strip_optional_time(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class ToolArgsModel(BaseModel):
    """所有工具参数的基类：禁止 AI 透传模型未声明的字段。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class EmptyArgs(ToolArgsModel):
    """无参数工具。"""


class ListTodosArgs(ToolArgsModel):
    filter: TodoFilter = Field(
        default="all",
        description="过滤条件：all=全部, pending=未完成, completed=已完成, overdue=已过期, upcoming=即将到期",
    )
    time_range: TimeRange = Field(
        default="all",
        description="时间范围：today=今天, week=本周, month=本月, all=不限",
    )
    priority: PriorityFilter = Field(
        default="all",
        description="优先级过滤：high=高, medium=中, low=低, all=不限",
    )


class AddTodoArgs(ToolArgsModel):
    title: str = Field(min_length=1, description="待办事项标题，简洁明了")
    description: str = Field(default="", description="详细描述（可选）")
    start_time: str | None = Field(
        default=None,
        description="开始时间，格式：YYYY-MM-DD 或 YYYY-MM-DD HH:MM（可选）",
    )
    end_time: str | None = Field(
        default=None,
        description="截止时间，格式：YYYY-MM-DD 或 YYYY-MM-DD HH:MM（可选，默认为当天23:59）",
    )
    priority: Priority = Field(default="medium", description="优先级：high=高, medium=中, low=低")

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _strip_required_text(value)

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_optional_time_text(cls, value: str | None) -> str | None:
        return _strip_optional_time(value)


class DeleteTodosArgs(ToolArgsModel):
    ids: list[str] = Field(min_length=1, description="要删除的待办事项 ID 列表（从 list_todos 结果中获取）")

    @field_validator("ids")
    @classmethod
    def validate_ids(cls, value: list[str]) -> list[str]:
        stripped_ids = []
        for item in value:
            stripped = item.strip()
            if not stripped:
                raise ValueError("ID 不能为空")
            stripped_ids.append(stripped)
        return stripped_ids


class ToggleTodoArgs(ToolArgsModel):
    id: str = Field(min_length=1, description="待办事项的 ID")

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _strip_required_text(value)


class UpdateTodoArgs(ToolArgsModel):
    id: str = Field(min_length=1, description="要修改的待办事项 ID")
    title: str | None = Field(default=None, description="新标题（可选，不传则保持原值）")
    description: str | None = Field(default=None, description="新描述（可选）")
    start_time: str | None = Field(
        default=None,
        description="新开始时间，格式：YYYY-MM-DD 或 YYYY-MM-DD HH:MM（可选）",
    )
    end_time: str | None = Field(
        default=None,
        description="新截止时间，格式：YYYY-MM-DD 或 YYYY-MM-DD HH:MM（可选）",
    )
    priority: Priority | None = Field(default=None, description="新优先级：high=高, medium=中, low=低（可选）")

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _strip_required_text(value)

    @field_validator("title", "description", "start_time", "end_time")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return _strip_optional_text(value)

    @model_validator(mode="after")
    def require_update_field(self):
        if all(
            value is None
            for value in [self.title, self.description, self.start_time, self.end_time, self.priority]
        ):
            raise ValueError("update_todo 至少需要一个待更新字段")
        return self


class SearchTodosArgs(ToolArgsModel):
    keyword: str = Field(min_length=1, description="搜索关键词")

    @field_validator("keyword")
    @classmethod
    def validate_keyword(cls, value: str) -> str:
        return _strip_required_text(value)


class RememberPreferenceArgs(ToolArgsModel):
    key: str = Field(min_length=1, description="偏好名称，例如 工作时间、称呼、默认项目")
    value: str = Field(min_length=1, description="偏好内容，需要稳定且可复用")

    @field_validator("key", "value")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _strip_required_text(value)


class ForgetPreferenceArgs(ToolArgsModel):
    key: str = Field(min_length=1, description="要删除的偏好名称")

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return _strip_required_text(value)


class CreateWorkItemArgs(ToolArgsModel):
    title: str = Field(min_length=1, description="工作项标题")
    priority: Priority = Field(default="medium", description="优先级")
    next_action: str = Field(default="", description="建议下一步")
    project_path: str = Field(default="", description="项目路径")

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _strip_required_text(value)


class ImportRedmineWorkItemArgs(ToolArgsModel):
    issue_id: str = Field(min_length=1, description="Redmine issue id")
    project_path: str = Field(default="", description="Playbook workspace path, empty means current directory")

    @field_validator("issue_id")
    @classmethod
    def validate_issue_id(cls, value: str) -> str:
        value = _strip_required_text(value)
        if not value.isdigit():
            raise ValueError("Redmine issue id 必须是数字")
        return value


class RecordEvidenceArgs(ToolArgsModel):
    work_item_id: str = Field(min_length=1, description="工作项 ID")
    evidence_type: EvidenceKind = Field(default="note", description="证据类型")
    summary: str = Field(min_length=1, description="证据摘要")
    command: str = Field(default="", description="命令文本")
    output_excerpt: str = Field(default="", description="输出摘录")
    success: bool | None = Field(default=None, description="是否成功")

    @field_validator("work_item_id", "summary")
    @classmethod
    def validate_required(cls, value: str) -> str:
        return _strip_required_text(value)


class WorkItemIdArgs(ToolArgsModel):
    work_item_id: str = Field(min_length=1, description="工作项 ID")

    @field_validator("work_item_id")
    @classmethod
    def validate_work_item_id(cls, value: str) -> str:
        return _strip_required_text(value)


class SyncWorkflowArgs(ToolArgsModel):
    project_path: str = Field(default="", description="项目路径，空表示当前目录")
    openspec_change: str | None = Field(default=None, description="OpenSpec change name")

    @field_validator("openspec_change")
    @classmethod
    def validate_openspec_change(cls, value: str | None) -> str | None:
        value = _strip_optional_text(value)
        if value is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
            raise ValueError("OpenSpec change name 只能包含字母、数字、下划线、点和连字符")
        return value


class ReadCodexReportsArgs(ToolArgsModel):
    import_items: bool = Field(default=True, description="是否将未完成/阻塞项导入 WorkItem")


TOOL_ARG_MODELS: dict[str, type[ToolArgsModel]] = {
    "list_todos": ListTodosArgs,
    "add_todo": AddTodoArgs,
    "delete_todos": DeleteTodosArgs,
    "toggle_todo": ToggleTodoArgs,
    "update_todo": UpdateTodoArgs,
    "search_todos": SearchTodosArgs,
    "get_statistics": EmptyArgs,
    "clear_completed": EmptyArgs,
    "remember_preference": RememberPreferenceArgs,
    "list_preferences": EmptyArgs,
    "forget_preference": ForgetPreferenceArgs,
    "create_work_item": CreateWorkItemArgs,
    "import_redmine_work_item": ImportRedmineWorkItemArgs,
    "list_work_status": EmptyArgs,
    "sync_workflow_context": SyncWorkflowArgs,
    "recommend_next_work_action": EmptyArgs,
    "record_work_evidence": RecordEvidenceArgs,
    "summarize_work_evidence": WorkItemIdArgs,
    "read_codex_task_reports": ReadCodexReportsArgs,
    "generate_daily_workflow_review": EmptyArgs,
}
