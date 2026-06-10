"""Agent 工具调用参数校验。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ai_todo_assistant.application.agent.tool_models import TOOL_ARG_MODELS


class ToolValidationError(ValueError):
    """LLM 返回的工具名或工具参数未通过本地校验。"""


@dataclass(frozen=True)
class ValidatedToolCall:
    """通过本地校验后的工具调用。"""

    call_id: str
    name: str
    args: dict[str, Any]


def validate_tool_calls(
    tool_calls: list[dict],
    tool_definitions: list[dict] | None = None,
) -> list[ValidatedToolCall]:
    """批量校验工具调用，全部通过后才允许执行。"""
    return [
        ValidatedToolCall(
            call_id=tool_call.get("id", ""),
            name=name,
            args=args,
        )
        for tool_call in tool_calls
        for name, args in [validate_tool_call(tool_call, tool_definitions)]
    ]


def validate_tool_call(
    tool_call: dict,
    tool_definitions: list[dict] | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    校验单个 tool_call。

    模型输出即使带了 schema，也只能视为“不可信输入”。真正执行本地工具前，
    必须再做一次白名单、JSON、必填字段、类型和枚举校验。
    """
    function = tool_call.get("function") or {}
    tool_name = function.get("name")
    if not tool_name:
        raise ToolValidationError("工具调用缺少 function.name")
    if tool_name not in TOOL_ARG_MODELS:
        raise ToolValidationError(f"未知工具: {tool_name}")

    raw_arguments = function.get("arguments", "{}")
    args = _parse_arguments(raw_arguments, tool_name)
    try:
        # Pydantic 是工具参数的唯一校验源：字段、类型、枚举、默认值和未知字段都在模型里声明。
        validated_args = TOOL_ARG_MODELS[tool_name].model_validate(args)
    except ValidationError as exc:
        raise ToolValidationError(_format_validation_error(tool_name, exc)) from exc
    except ValueError as exc:
        raise ToolValidationError(f"{tool_name} 参数校验失败: {exc}") from exc
    return tool_name, validated_args.model_dump()


def _parse_arguments(raw_arguments: Any, tool_name: str) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        args = raw_arguments
    elif isinstance(raw_arguments, str):
        try:
            args = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as exc:
            raise ToolValidationError(
                f"{tool_name}.arguments 不是合法 JSON object 字符串: {exc.msg}"
            ) from exc
    else:
        raise ToolValidationError(f"{tool_name}.arguments 必须是 JSON object 字符串")

    if not isinstance(args, dict):
        raise ToolValidationError(f"{tool_name}.arguments 必须解析为 JSON object")
    return args


def _format_validation_error(tool_name: str, exc: ValidationError) -> str:
    messages = []
    for error in exc.errors():
        field_path = _format_location(error.get("loc", ()))
        error_type = error.get("type", "")
        context = error.get("ctx") or {}

        if error_type == "missing":
            messages.append(f"{tool_name} 缺少必填参数: {field_path}")
        elif error_type == "extra_forbidden":
            messages.append(f"{tool_name} 包含未知参数: {field_path}")
        elif error_type == "literal_error":
            expected = context.get("expected", "")
            messages.append(f"{tool_name}.{field_path} 的值不在允许范围: {expected}")
        else:
            messages.append(f"{tool_name}.{field_path} 参数校验失败: {error.get('msg', error_type)}")
    return "；".join(messages)


def _format_location(location: tuple[Any, ...]) -> str:
    if not location:
        return "__root__"

    text = str(location[0])
    for item in location[1:]:
        if isinstance(item, int):
            text += f"[{item}]"
        else:
            text += f".{item}"
    return text
