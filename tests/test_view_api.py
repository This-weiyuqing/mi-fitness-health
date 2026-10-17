import pytest
from fastapi.testclient import TestClient

from mi_fitness_mcp import api
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.storage import Database
from test_view_queries import insert


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    db = Database(tmp_path / "synthetic.db")
    monkeypatch.setenv("MI_FITNESS_API_KEY", "synthetic-api-key")
    context = api.UserContext("owner", "synthetic-unused", "cn", query_service=QueryService(db, "owner"))
    monkeypatch.setattr(api.app.state, "db", db, raising=False)
    monkeypatch.setattr(api.app.state, "default_context", context, raising=False)
    client = TestClient(api.app, base_url="http://localhost", headers={"X-API-Key": "synthetic-api-key"})
    yield client, db
    client.close()


def test_view_auth_validation_and_legacy_compatibility(api_client):
    client, db = api_client
    insert(db, "heart_rate_samples", id="sample", timestamp="2026-10-15T02:00:00Z", bpm=72, sample_type="passive")
    query = "?start_date=2026-10-15&end_date=2026-10-15"
    for path in ["/api/views/heartrate", "/api/views/heartrate/records", "/api/views/heartrate/export", "/api/overview"]:
        request = client.build_request("GET", path + query)
        request.headers.pop("X-API-Key")
        assert client.send(request).status_code == 401
    result = client.get("/api/views/heartrate" + query)
    assert result.status_code == 200
    assert result.json()["statistics"]["primary_mean"] == 72
    assert result.json()["page"]["size"] == 10
    assert result.json()["range"] == {"start": "2026-10-15", "end": "2026-10-15"}
    old = client.get("/api/heart-rate" + query)
    assert old.status_code == 200
    assert old.json() == {"status": "ok", "count": 1, "data": [dict(timestamp="2026-10-15T02:00:00Z", bpm=72, sample_type="passive")]}
    page = client.get("/api/views/heartrate/records" + query).json()
    assert set(page) == {"status", "kind", "range", "page"}
    overview = client.get("/api/overview" + query).json()
    assert overview["status"] == "ok"
    assert overview["range"] == {"start": "2026-10-15", "end": "2026-10-15"}
    assert overview["data"]["resting_mean_bpm"] is None
    assert set(overview["data"]) == {"steps", "active_kcal", "distance_m", "resting_mean_bpm", "mean_daily_asleep_minutes", "mean_spo2_pct", "mean_stress", "activity_days", "sleep_days", "resting_count", "spo2_count"}


@pytest.mark.parametrize("changes", [dict(kind="unknown"), dict(start_date="2026-02-30"), dict(start_date="2026-10-16"),
    dict(start_date="2000-01-01"), dict(page=0), dict(page=1000001), dict(limit=0), dict(limit=-1),
    dict(pressure_level="invalid"), dict(page="1.5"), dict(include_naps="invalid")])
def test_invalid_view_query_rejected(api_client, changes):
    client, _ = api_client
    values = dict(kind="stress", start_date="2026-10-15", end_date="2026-10-15") | changes
    kind = values.pop("kind")
    response = client.get(f"/api/views/{kind}", params=values)
    assert response.status_code in (400, 422)
    assert "detail" in response.json()


def test_blank_filters_and_empty_values_are_supported(api_client):
    client, _ = api_client
    response = client.get("/api/views/stress", params=dict(start_date="2026-10-15", end_date="2026-10-15", sample_type="", pressure_level=""))
    assert response.status_code == 200
    assert response.json()["statistics"]["primary_mean"] is None
    assert response.json()["page"]["rows"] == []


def test_records_endpoint_does_not_reaggregate(api_client, monkeypatch):
    client, _ = api_client
    from mi_fitness_mcp.storage.view_queries import ViewRepository
    def forbidden(*args, **kwargs):
        raise AssertionError("翻页不能重新聚合")
    monkeypatch.setattr(ViewRepository, "statistics", forbidden)
    monkeypatch.setattr(ViewRepository, "points", forbidden)
    assert client.get("/api/views/stress/records", params=dict(start_date="2026-10-15", end_date="2026-10-15", page=2)).status_code == 200
