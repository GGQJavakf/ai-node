"""Read-only workflow source connectors."""

from .command_runner import CommandResult, CommandRunner
from .git_connector import GitConnector
from .openspec_connector import OpenSpecConnector
from .playbook_connector import PlaybookConnector

__all__ = [
    "CommandResult",
    "CommandRunner",
    "GitConnector",
    "OpenSpecConnector",
    "PlaybookConnector",
]
