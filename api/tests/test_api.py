from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app.main import app

client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "AAGAM" in data["project"]
    assert data["phase"] == "Phase 0 — Setup"


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "AAGAM Backend API"
    assert "version" in data
    assert "timestamp" in data
    assert "supabase_connected" in data


def test_meta_endpoint():
    response = client.get("/api/v1/meta")
    assert response.status_code == 200
    data = response.json()
    assert data["locations_count"] == 40
    assert len(data["locations"]) == 40
    assert "models" in data
    assert "gfs" in data["models"]["models"]
    assert "ecmwf_aifs" in data["models"]["models"]


def test_hello_endpoint_fallback():
    # Without live Supabase credentials, hello endpoint returns graceful 200 with notice
    with patch("api.app.main.read_setup_row") as mock_read:
        mock_read.return_value = (False, None, "Pending credentials")
        response = client.get("/api/v1/hello")
        assert response.status_code == 200
        data = response.json()
        assert data["project"] == "AAGAM (Adaptive AI-Grid Assimilation Model)"
        assert data["phase"] == "Phase 0 — Setup"
        assert "read_row" in data


def test_hello_endpoint_supabase_read():
    # When Supabase returns a row, hello endpoint provides live row data
    mock_row = {
        "id": 1,
        "component": "supabase_database",
        "status": "verified",
        "details": {"phase": "Phase 0", "postgis_enabled": True}
    }
    with patch("api.app.main.read_setup_row") as mock_read:
        mock_read.return_value = (True, mock_row, "Read successfully")
        response = client.get("/api/v1/hello")
        assert response.status_code == 200
        data = response.json()
        assert data["supabase_status"] == "connected"
        assert data["read_row"]["component"] == "supabase_database"
        assert data["read_row"]["status"] == "verified"
