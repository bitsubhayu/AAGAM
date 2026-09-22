"""BaseTool class and execution context for AAGAM Assistant tools (PRD §9.4)."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

import asyncpg
from pydantic import BaseModel

from api.app.assistant.schemas import ToolEnvelope
from api.app.auth.dependencies import CurrentUser
from api.app.routers.artifacts import register_artifact


class ToolContext:
    """Execution context provided to tools."""

    def __init__(
        self,
        conn: Optional[asyncpg.Connection] = None,
        current_user: Optional[CurrentUser] = None,
    ) -> None:
        self.conn = conn
        self.current_user = current_user or CurrentUser(user_id="anonymous", role="viewer")


class BaseTool(ABC):
    """Abstract base class for all allow-listed tools."""

    name: str
    description: str
    args_model: Type[BaseModel]

    @abstractmethod
    async def execute(self, raw_args: Dict[str, Any], context: ToolContext) -> ToolEnvelope:
        """Executes the tool with validated arguments and returns a ToolEnvelope."""
        pass

    def to_openai_tool_dict(self) -> Dict[str, Any]:
        """Converts tool schema to compact OpenAI-compatible function definition (PRD §9.4, §9.6 <= 900 tokens)."""
        schema = self.args_model.model_json_schema()
        properties = schema.get("properties", {})
        cleaned_properties = {}

        for prop_name, prop_def in properties.items():
            cleaned_prop = {}
            if "anyOf" in prop_def:
                types = [item.get("type") for item in prop_def["anyOf"] if item.get("type") and item.get("type") != "null"]
                base_type = types[0] if types else "string"
                cleaned_prop["type"] = [base_type, "null"]
            elif "type" in prop_def:
                cleaned_prop["type"] = prop_def["type"]
            else:
                cleaned_prop["type"] = "string"

            if "enum" in prop_def:
                cleaned_prop["enum"] = prop_def["enum"]
            if "items" in prop_def:
                cleaned_prop["items"] = prop_def["items"]
            if "default" in prop_def:
                cleaned_prop["default"] = prop_def["default"]
            cleaned_properties[prop_name] = cleaned_prop

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": cleaned_properties,
                    "required": schema.get("required", []),
                },
            },
        }


def save_tool_artifact(
    owner_id: str,
    title: str,
    columns: List[str],
    full_rows: List[Dict[str, Any]],
) -> str:
    """Stores full dataset server-side in artifact registry and returns artifact_id."""
    artifact_id = f"art_{uuid.uuid4().hex[:10]}"
    register_artifact(artifact_id, owner_id, full_rows)
    return artifact_id
