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


def test_hello_endpoint_blocked():
    """When credentials or table rows are missing, hello endpoint returns BLOCKED."""
    with patch("api.app.main.read_setup_row") as mock_read:
        mock_read.return_value = ("BLOCKED", None, "Pending credentials")
        response = client.get("/api/v1/hello")
        assert response.status_code == 200
        data = response.json()
        assert data["verification_status"] == "BLOCKED"
        assert data["supabase_status"] == "blocked"
        assert data["data_source"] == "none"
        assert data["read_row"] is None
        assert "Supabase read blocked" in data["message"]


def test_hello_endpoint_supabase_read_pass():
    """When Supabase returns a row, hello endpoint provides PASS and live row data."""
    mock_row = {
        "id": 1,
        "component": "supabase_database",
        "status": "verified",
        "details": {"phase": "Phase 0", "postgis_enabled": True},
    }
    with patch("api.app.main.read_setup_row") as mock_read:
        mock_read.return_value = ("PASS", mock_row, "Read successfully")
        response = client.get("/api/v1/hello")
        assert response.status_code == 200
        data = response.json()
        assert data["verification_status"] == "PASS"
        assert data["supabase_status"] == "connected"
        assert data["data_source"] == "supabase:_aagam_setup_check"
        assert data["read_row"]["component"] == "supabase_database"
        assert data["read_row"]["status"] == "verified"


def test_hello_endpoint_fail():
    """When database query encounters an error, hello endpoint returns FAIL."""
    with patch("api.app.main.read_setup_row") as mock_read:
        mock_read.return_value = ("FAIL", None, "Database error: connection refused")
        response = client.get("/api/v1/hello")
        assert response.status_code == 200
        data = response.json()
        assert data["verification_status"] == "FAIL"
        assert data["supabase_status"] == "failed"
        assert data["data_source"] == "none"
        assert data["read_row"] is None


def test_cors_restrictions():
    """Verify that CORS does not use wildcard allow_origins with credentials."""
    # Test allowed origin
    headers = {"Origin": "http://localhost:5173"}
    resp = client.get("/health", headers=headers)
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    # Test disallowed origin
    evil_headers = {"Origin": "https://malicious-site.com"}
    resp_evil = client.get("/health", headers=evil_headers)
    assert resp_evil.status_code == 200
    assert resp_evil.headers.get("access-control-allow-origin") is None
