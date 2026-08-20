"""OpenAI 兼容 Tool Calling 工具定义。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ai_todo_assistant.application.agent.tool_models import TOOL_ARG_MODELS


TOOL_DESCRIPTIONS = {
    "list_todos": (
        "获取待办事项列表。可以按时间范围、状态、优先级等条件过滤。"
        "当用户问'有什么任务'、'查看进度'、'待办清单'、'今天有什么事'等时调用。"
    ),
    "add_todo": (
        "新增一条待办事项。当用户想记录任务、创建事项、安排日程时调用。"
        "如果用户说了多件事，可以多次调用此工具。"
    ),
    "delete_todos": (
        "删除一条或多条待办事项。需要提供 todo ID 列表。"
        "当用户说'删除'、'取消'、'移除'某任务时调用。"
        "调用 list_todos 后可以获得 ID，再用此工具删除。"
    ),
    "toggle_todo": (
        "切换一条待办事项的完成状态（完成↔未完成）。"
        "当用户说'完成了'、'做完了'、'标记完成/未完成'时调用。"
    ),
    "update_todo": (
        "修改已有待办事项的标题、描述、时间或优先级信息。"
        "当用户说'改一下'、'修改'、'推迟到...'、'提高优先级'时调用。"
    ),
    "search_todos": "搜索待办事项，按关键词匹配标题或描述。当用户说'搜索'、'查找'、'找到关于...的任务'时调用。",
    "get_statistics": "获取待办事项的统计信息（总数、完成数、待完成数、过期数、即将到期数、完成率）。当用户问进度、效率、整体情况、汇报、总结等时调用。",
    "clear_completed": "清除所有已完成的待办事项。当用户说'清理已完成'、'删除已完成任务'时调用。",
    "remember_preference": "持久化记住用户的稳定偏好，例如称呼、工作时间、默认项目、写作风格。只在用户明确要求记住或长期使用时调用。",
    "list_preferences": "查看已经记住的用户偏好。当用户问你记住了什么、我的偏好是什么时调用。",
    "forget_preference": "删除一条已记住的用户偏好。当用户要求忘记、删除某个偏好时调用。",
    "create_work_item": "创建个人工作项，用于跟踪 Redmine/OpenSpec/Git/Codex 之外的手工工作。",
    "import_redmine_work_item": "通过 Playbook 只读导入 Redmine issue 为本地 WorkItem，不写 Redmine。",
    "list_work_status": "查看本地 WorkItem 与同步状态摘要。",
    "sync_workflow_context": "只读同步当前项目 Git/OpenSpec/Playbook 上下文，缺少外部命令时返回不可用状态。",
    "recommend_next_work_action": "从活动 WorkItem 中推荐下一步。",
    "record_work_evidence": "为 WorkItem 追加命令、测试、备注、评审或链接证据。",
    "summarize_work_evidence": "汇总 WorkItem 的证据，用于日报、closeout 或 MR/Redmine 草稿。",
    "run_system_cli": (
        "执行只读系统 CLI catalog 命令，例如 git.status。只能传 command_key，不能执行任意 shell；"
        "命令输出会先脱敏、截断并摘要；需要留痕时设置 record_evidence=true 并提供 work_item_id。"
    ),
    "read_codex_task_reports": "读取 Codex 每日任务 JSON/Markdown 报告，并可导入未完成/阻塞项为 WorkItem。",
    "generate_daily_workflow_review": "基于 WorkItem 与 Evidence 生成工作日复盘草稿。",
}


def _tool_parameters_schema(tool_name: str) -> dict[str, Any]:
    schema = deepcopy(TOOL_ARG_MODELS[tool_name].model_json_schema())
    schema.pop("title", None)
    return _remove_nullable_any_of(schema)


def _remove_nullable_any_of(value: Any) -> Any:
    """把 Pydantic 的 string|null schema 收敛成工具提示更友好的 optional string。"""
    if isinstance(value, dict):
        any_of = value.get("anyOf")
        if isinstance(any_of, list) and len(any_of) == 2:
            non_null = [item for item in any_of if item.get("type") != "null"]
            if len(non_null) == 1:
                merged = {k: _remove_nullable_any_of(v) for k, v in value.items() if k != "anyOf"}
                merged.update(_remove_nullable_any_of(non_null[0]))
                return merged
        return {key: _remove_nullable_any_of(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_remove_nullable_any_of(item) for item in value]
    return value


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": TOOL_DESCRIPTIONS[name],
            "parameters": _tool_parameters_schema(name),
        },
    }
    for name in TOOL_ARG_MODELS
]

