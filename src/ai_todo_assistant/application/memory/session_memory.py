"""短期滑动窗口消息记忆。"""
from __future__ import annotations

from collections import deque


class SessionMemory:
    """
    单次运行期间的短期会话记忆。

    这里只保存 user/assistant 的自然语言消息，不保存 tool_call 和 tool 结果。
    真实待办状态由仓储提供，工具执行细节不进入短期对话窗口，避免占用过多上下文。
    """

    def __init__(self, max_messages: int = 20):
        if max_messages <= 0:
            raise ValueError("max_messages 必须大于 0")
        self.max_messages = max_messages
        self._messages = deque(maxlen=max_messages)

    def add_user_message(self, content: str) -> None:
        """记录用户消息。"""
        self._messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        """记录助手最终自然语言回复。"""
        self._messages.append({"role": "assistant", "content": content})

    def build_messages(self, system_message: dict) -> list[dict]:
        """构造发送给 LLM 的消息列表，system message 始终在最前。"""
        return [system_message] + self.snapshot()

    def clear(self) -> None:
        """清空当前会话记忆。"""
        self._messages.clear()

    def snapshot(self) -> list[dict]:
        """返回消息快照，避免调用方修改内部滑动窗口。"""
        return [message.copy() for message in self._messages]
