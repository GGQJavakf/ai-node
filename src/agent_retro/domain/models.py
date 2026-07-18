"""Core AgentRetro domain values."""

from enum import Enum


class KnowledgeType(str, Enum):
    """Evidence-constrained knowledge categories."""

    RULE = "RULE"
    LESSON = "LESSON"
    TASK_STATE = "TASK_STATE"
