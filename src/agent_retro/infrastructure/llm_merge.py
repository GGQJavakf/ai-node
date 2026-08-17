"""Strict typed model gateway for semantic merge proposals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_retro.application.merge import canonical_merge_path_identity
from agent_retro.application.merge_planner import MergeProposal


class MergeProposalResponseError(RuntimeError):
    """The model did not return one strict typed proposal."""


class MergeProposalUnavailableError(RuntimeError):
    """The configured model transport is unavailable or timed out."""


class _LLMClient(Protocol):
    def request(
        self, payload: dict, stream: bool = False, timeout: int = 30
    ) -> object: ...


class _Replacement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1)
    content: str


class _Rename(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)


class _MergeProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    replacements: list[_Replacement]
    deletes: list[str]
    renames: list[_Rename]
    conflicts: list[str]


_PROMPT = (
    "Propose a preview-only reorganization of the supplied redacted project Markdown. "
    "Return only the strict JSON schema. Use vault-relative paths, preserve unrelated "
    "content, surface ambiguity as conflicts, and never invent or restore secrets."
)


class LLMMergeProposalGateway:
    def __init__(self, client: _LLMClient, *, model: str) -> None:
        self.client = client
        self.model = model

    def propose(
        self,
        project_id: str,
        instruction: str,
        documents: Mapping[str, str],
        *,
        timeout: int,
    ) -> MergeProposal:
        try:
            response = self.client.request(
                {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": _PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "project_id": project_id,
                                    "instruction": instruction,
                                    "documents": documents,
                                },
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        },
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "agentretro_merge_proposal",
                            "strict": True,
                            "schema": _MergeProposalResponse.model_json_schema(),
                        },
                    },
                    "temperature": 0,
                },
                stream=False,
                timeout=timeout,
            )
        except Exception:
            raise MergeProposalUnavailableError("merge_proposal_unavailable") from None
        try:
            content = response["choices"][0]["message"]["content"]  # type: ignore[index]
            if not isinstance(content, str) or not content.strip():
                raise TypeError
            parsed = _MergeProposalResponse.model_validate_json(content, strict=True)
        except (IndexError, KeyError, TypeError, ValueError):
            raise MergeProposalResponseError(
                "merge_proposal_response_invalid"
            ) from None
        replacement_paths = [item.path for item in parsed.replacements]
        try:
            replacement_identities = [
                canonical_merge_path_identity(Path(path)) for path in replacement_paths
            ]
        except ValueError:
            raise MergeProposalResponseError(
                "merge_proposal_response_invalid"
            ) from None
        if len(replacement_identities) != len(set(replacement_identities)):
            raise MergeProposalResponseError("merge_proposal_response_invalid")
        return MergeProposal(
            replacements={
                Path(item.path): item.content for item in parsed.replacements
            },
            deletes=tuple(Path(item) for item in parsed.deletes),
            renames=tuple(
                (Path(item.source), Path(item.target)) for item in parsed.renames
            ),
            conflicts=tuple(parsed.conflicts),
        )
