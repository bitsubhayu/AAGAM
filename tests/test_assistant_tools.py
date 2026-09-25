"""Unit tests for the six allow-listed AAGAM Assistant tools (PRD §9.4)."""

import pytest

from api.app.assistant.schemas import ToolEnvelope
from api.app.assistant.tools import get_all_tools, get_openai_tools_schema, get_tool
from api.app.assistant.tools.alerts import GetAlertsTool
from api.app.assistant.tools.base import ToolContext
from api.app.assistant.tools.export import ExportDataTool, verify_signed_export_token
from api.app.assistant.tools.forecast import GetForecastTool
from api.app.assistant.tools.history import QueryHistoryTool
from api.app.assistant.tools.skill import GetSkillTool
from api.app.assistant.tools.weights import GetWeightsTool
from api.app.routers.artifacts import _ARTIFACT_STORE


@pytest.mark.asyncio
async def test_tool_allow_list_strictly_six():
    """Asserts that exactly six allow-listed tools exist and no arbitrary tools can be fetched."""
    tools = get_all_tools()
    assert len(tools) == 6
    assert set(tools.keys()) == {
        "get_forecast",
        "get_weights",
        "get_skill",
        "get_alerts",
        "query_history",
        "export_data",
    }
    assert get_tool("drop_table") is None
    assert get_tool("execute_sql") is None


@pytest.mark.asyncio
async def test_tool_schemas_token_compactness():
    """Asserts that OpenAI-compatible tool schemas are generated and stay under 900 tokens total."""
    schemas = get_openai_tools_schema()
    assert len(schemas) == 6
    from api.app.assistant.token_budgeter import estimate_tokens
    total_tokens = estimate_tokens(schemas)
    assert total_tokens <= 900, f"Tool schemas exceeded 900 tokens: {total_tokens}"


@pytest.fixture
def enable_test_fallback(monkeypatch):
    """Explicitly enables test fixtures in isolated offline unit test."""
    monkeypatch.setenv("AAGAM_ALLOW_TEST_FALLBACK", "1")


@pytest.mark.asyncio
async def test_production_mode_blocks_silent_parquet_fallback(monkeypatch):
    """Part 30 & Part 15: Proves that in production (fallback disabled), tools return structured unavailable, NOT test parquet."""
    monkeypatch.delenv("AAGAM_ALLOW_TEST_FALLBACK", raising=False)

    # 1. Forecast Tool
    f_tool = GetForecastTool()
    f_res = await f_tool.execute({"location": "Bhubaneswar", "variable": "rain_mm"}, ToolContext())
    assert f_res.n_rows == 0
    assert f_res.artifact_id == "none"
    assert "No forecast records" in f_res.title

    # 2. Weights Tool
    w_tool = GetWeightsTool()
    w_res = await w_tool.execute({"variable": "tmax_c", "region": "CENTRAL", "season": "monsoon"}, ToolContext())
    assert w_res.n_rows == 0
    assert w_res.artifact_id == "none"

    # 3. Alerts Tool
    a_tool = GetAlertsTool()
    a_res = await a_tool.execute({"severity_min": "warning"}, ToolContext())
    assert a_res.n_rows == 0
    assert a_res.artifact_id == "none"


@pytest.mark.asyncio
async def test_get_forecast_tool_envelope(enable_test_fallback):
    """Verifies get_forecast returns valid ToolEnvelope and stores artifact."""
    tool = GetForecastTool()
    ctx = ToolContext()
    res = await tool.execute({"location": "Bhubaneswar", "variable": "rain_mm", "lead_days_max": 7}, ctx)

    assert isinstance(res, ToolEnvelope)
    assert res.ok is True
    assert "Bhubaneswar" in res.title
    assert "rain_mm" in res.title
    assert res.n_rows >= 1
    assert len(res.preview) <= 5
    assert "blended" in res.stats
    assert res.artifact_id in _ARTIFACT_STORE


@pytest.mark.asyncio
async def test_get_weights_tool_envelope(enable_test_fallback):
    """Verifies get_weights returns model weight matrix and sample sizes."""
    tool = GetWeightsTool()
    ctx = ToolContext()
    res = await tool.execute({"variable": "tmax_c", "region": "CENTRAL", "season": "monsoon"}, ctx)

    assert res.ok is True
    assert "dominant_model" in res.stats
    assert len(res.columns) == 7
    assert res.artifact_id in _ARTIFACT_STORE


@pytest.mark.asyncio
async def test_get_skill_tool_envelope(enable_test_fallback):
    """Verifies get_skill returns verification scores table."""
    tool = GetSkillTool()
    ctx = ToolContext()
    res = await tool.execute({"metric": "mae", "group_by": "lead", "variable": "wind_max_kmh"}, ctx)

    assert res.ok is True
    assert "MAE" in res.stats["metric"]
    assert len(res.preview) <= 5


@pytest.mark.asyncio
async def test_get_alerts_tool_envelope(enable_test_fallback):
    """Verifies get_alerts returns active alerts with IMD decision-support notice."""
    tool = GetAlertsTool()
    ctx = ToolContext()
    res = await tool.execute({"status": "active"}, ctx)

    assert res.ok is True
    assert "decision support, not an official IMD warning" in res.stats["decision_rule_notice"]


@pytest.mark.asyncio
async def test_query_history_cap_5000():
    """Verifies query_history enforces 5,000 row cap and suggests export on overflow."""
    tool = QueryHistoryTool()
    ctx = ToolContext()

    # Normal range (within cap)
    res_ok = await tool.execute({
        "location": "Delhi",
        "variable": "tmax_c",
        "start": "2026-08-01",
        "end": "2026-08-14",
        "kind": "blended",
    }, ctx)
    assert res_ok.ok is True
    assert res_ok.n_rows <= 5000

    # Massive range (> 5,000 rows)
    res_overflow = await tool.execute({
        "location": "Delhi",
        "variable": "tmax_c",
        "start": "2024-01-01",
        "end": "2026-09-01",  # ~970 days * 7 leads = ~6,800 rows
        "kind": "forecast",
    }, ctx)
    assert res_overflow.ok is False
    assert res_overflow.meta.get("exceeded") is True
    assert "export" in res_overflow.preview[0][2].lower()


@pytest.mark.asyncio
async def test_export_data_signed_url():
    """Verifies export_data generates a backend-signed URL expiring in ~10 minutes."""
    tool = ExportDataTool()
    ctx = ToolContext()
    res = await tool.execute({"dataset": "forecast", "filters": {"location": "nagpur"}, "format": "csv"}, ctx)

    assert res.ok is True
    download_url = res.stats["signed_url"]
    assert "/api/v1/export" in download_url
    assert "token=" in download_url

    # Extract token and verify signature
    token = download_url.split("token=")[1].split("&")[0]
    payload = verify_signed_export_token(token)
    assert payload["dataset"] == "forecast"
    assert payload["format"] == "csv"
