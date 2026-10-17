import pytest
from datetime import datetime, timezone, timedelta

from mi_fitness_mcp.adapters.mi_fitness_cloud import (
    MiFitnessCloudAdapter,
    _is_authentication_error,
)


async def _collect(async_iterable):
    items = []
    async for item in async_iterable:
        items.append(item)
    return items


def test_optional_number_helpers():
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    assert adapter._optional_float(0) is None
    assert adapter._optional_float("1.5") == 1.5
    assert adapter._optional_int(0) is None
    assert adapter._optional_int("7") == 7


def test_parse_value_dict_and_json():
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    assert adapter._parse_value({"value": {"steps": 1}}) == {"steps": 1}
    assert adapter._parse_value({"value": '{"steps": 2}'}) == {"steps": 2}


def test_record_datetime_uses_zone_offset():
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    dt = adapter._record_datetime({"time": 0, "zone_offset": 10800})
    assert dt.isoformat().startswith("1970-01-01T03:00:00")


@pytest.mark.asyncio
async def test_iter_daily_activity_uses_latest_cloud_daily_report(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1", region="cn")
    adapter._connected = True
    adapter._client = object()

    async def fake_request(base_url, path, payload):
        # CN 午夜对应 UTC 前一天，日报没有 zone_offset；重复日报取最新版本。
        if path.endswith("get_aggregated_fitness_data_by_time"):
            assert payload["tag"] == "daily_report"
            values = (
                ['{"steps": 10, "distance": 8}', '{"steps": 20, "distance": 16}']
                if payload["key"] == "steps" else ['{"calories": 7}']
            )
            return {"data_list": [{"time": 1743436800, "update_time": i + 1, "value": v} for i, v in enumerate(values)], "has_more": False}
        # 旧实现会误把多来源明细相加。
        return {"data_list": [{"time": 1743467400, "value": '{"steps": 99, "distance": 99, "calories": 99}'}], "has_more": False}

    monkeypatch.setattr(adapter, "_request", fake_request)
    items = await _collect(adapter.iter_daily_activity("2025-04-01", "2025-04-01"))

    assert len(items) == 1
    assert items[0].date == "2025-04-01"
    assert items[0].steps == 20
    assert items[0].distance_m == 16
    assert items[0].active_kcal == 7


@pytest.mark.asyncio
async def test_daily_activity_rejects_missing_calorie_report(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1", region="cn")
    adapter._connected = True
    adapter._client = object()

    async def fake_request(base_url, path, payload):
        items = [{"time": 1743436800, "value": '{"steps": 20, "distance": 16}'}] if payload["key"] == "steps" else []
        return {"data_list": items, "has_more": False}

    monkeypatch.setattr(adapter, "_request", fake_request)
    with pytest.raises(ValueError, match="Incomplete daily report"):
        await _collect(adapter.iter_daily_activity("2025-04-01", "2025-04-01"))


@pytest.mark.asyncio
async def test_fetch_key_rejects_repeated_pagination_cursor(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1", region="cn")
    adapter._client = object()

    async def fake_request(base_url, api_path, payload):
        return {"data_list": [], "has_more": True, "next_key": "same"}

    monkeypatch.setattr(adapter, "_request", fake_request)
    with pytest.raises(RuntimeError, match="cursor loop"):
        await adapter._fetch_key("steps", "2026-07-06", "2026-07-12")


@pytest.mark.asyncio
async def test_connect_failure_closes_client(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="bad", region="cn")

    async def failed_login(user_id, pass_token):
        raise RuntimeError("invalid credentials")

    monkeypatch.setattr(adapter, "_login_with_token", failed_login)
    assert await adapter.connect() is False
    assert adapter._client is None
    assert "invalid credentials" in adapter.last_error


def test_authentication_error_detection():
    assert _is_authentication_error(401, "denied")
    assert _is_authentication_error(0, "session expired")
    assert _is_authentication_error(-10001, "unknown")
    assert not _is_authentication_error(500, "temporary server failure")


@pytest.mark.asyncio
async def test_sleep_daily_report_does_not_subtract_awake_twice(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1", region="cn")
    adapter._connected = True
    adapter._client = object()
    cn = timezone(timedelta(hours=8))
    bedtime = int(datetime(2025, 4, 1, 23, 40, tzinfo=cn).timestamp())
    wake = bedtime + 40 * 60
    segment = {"bedtime": bedtime, "wake_up_time": wake, "duration": 30, "sleep_awake_duration": 10, "sleep_deep_duration": 10, "sleep_light_duration": 20}

    async def fake_request(base_url, path, payload):
        if path.endswith("get_aggregated_fitness_data_by_time"):
            return {"data_list": [{"time": wake, "update_time": wake, "value": {"total_duration": 30, "sleep_score": 84, "segment_details": [segment]}}], "has_more": False}
        return {"data_list": [{"time": wake, "zone_offset": 28800, "value": segment}], "has_more": False}

    monkeypatch.setattr(adapter, "_request", fake_request)
    sessions = await _collect(adapter.iter_sleep_sessions("2025-04-02", "2025-04-02"))
    assert len(sessions) == 1
    assert sessions[0].duration_minutes == 30
    assert sessions[0].time_asleep_minutes == 30
    assert sessions[0].time_awake_minutes == 10
    assert sessions[0].sleep_score == 84


def test_sleep_queries_use_wake_date_and_latest_canonical_version(tmp_path):
    from mi_fitness_mcp.models import SleepSession
    from mi_fitness_mcp.storage import Database

    cn = timezone(timedelta(hours=8))
    db = Database(tmp_path / "test.sqlite")
    start = datetime(2025, 4, 1, 23, 40, tzinfo=cn)
    end = start + timedelta(minutes=40)
    for name, source, collected in [("raw", "raw:1", end), ("old", "daily_report:2025-04-02", end), ("new", "daily_report:2025-04-02", end + timedelta(minutes=5))]:
        db.insert_sleep_session(SleepSession(id=name, sleep_id=name, provider="mi_fitness", source_type="cloud_session", source_record_id=source, user_id="u1", timezone="Asia/Shanghai", collected_at=collected, start_at=start, end_at=end, duration_minutes=30, time_asleep_minutes=30, time_awake_minutes=10))
    sessions = db.query_sleep_sessions("u1", "2025-04-02", "2025-04-02")
    assert [row["id"] for row in sessions] == ["new"]
    with db._get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sleep_sessions").fetchone()[0] == 3
