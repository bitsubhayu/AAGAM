"""Registry of the six allow-listed read-only tools for AAGAM Assistant (PRD §9.4, Tech Stack §8.3).

Exposes strictly:
1. get_forecast
2. get_weights
3. get_skill
4. get_alerts
5. query_history
6. export_data
No other tools may be exposed to the model.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from api.app.assistant.tools.alerts import GetAlertsTool
from api.app.assistant.tools.base import BaseTool
from api.app.assistant.tools.export import ExportDataTool
from api.app.assistant.tools.forecast import GetForecastTool
from api.app.assistant.tools.history import QueryHistoryTool
from api.app.assistant.tools.skill import GetSkillTool
from api.app.assistant.tools.weights import GetWeightsTool

# Strictly the 6 allow-listed tools
_TOOLS_REGISTRY: Dict[str, BaseTool] = {
    "get_forecast": GetForecastTool(),
    "get_weights": GetWeightsTool(),
    "get_skill": GetSkillTool(),
    "get_alerts": GetAlertsTool(),
    "query_history": QueryHistoryTool(),
    "export_data": ExportDataTool(),
}


def get_tool(name: str) -> Optional[BaseTool]:
    """Returns the requested tool if in the allow-list, else None."""
    return _TOOLS_REGISTRY.get(name)


def get_all_tools() -> Dict[str, BaseTool]:
    """Returns all 6 registered tools."""
    return _TOOLS_REGISTRY


def get_openai_tools_schema() -> List[Dict[str, Any]]:
    """Returns OpenAI-compatible tools schema list for all 6 tools."""
    return [t.to_openai_tool_dict() for t in _TOOLS_REGISTRY.values()]
