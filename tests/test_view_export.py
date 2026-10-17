import asyncio
import csv
import io
import threading
from contextlib import contextmanager

import pytest
from starlette.requests import Request

from mi_fitness_mcp import api
from mi_fitness_mcp.storage.view_queries import ViewRepository, ViewSelection
from test_view_api import api_client as api_client
from test_view_queries import insert


def test_export_matches_filtered_set_and_escapes_formula(api_client):
    client, db = api_client
    for n in range(31):
        insert(db, "stress_samples", id=str(n), timestamp=f"2026-10-15T00:{n:02}:00Z", stress_score=26 + n if n < 25 else 99, level="=1+1")
    params = dict(start_date="2026-10-15", end_date="2026-10-15", pressure_level="mild", limit=11, page=2)
    response = client.get("/api/views/stress/export", params=params)
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert "content-length" not in response.headers
    records = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(records) == 11
    assert [int(row["压力指数"]) for row in records] == list(range(50, 39, -1))
    assert all(row["源等级（原值）"] == "'=1+1" for row in records)
    assert all(row["压力等级（当前分界）"] == "轻度" for row in records)
    assert not set(records[0]) & {"id", "user_id", "device_id", "pass_token", "api_key"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("text", ["=1+1", "+SUM(A1)", "-1+1", "@SUM(A1)", "\t =1+1", "\n=1+1"])
def test_formula_prefixes_in_source_text_are_safe(api_client, text):
    client, db = api_client
    insert(db, "heart_rate_samples", id="sample", timestamp="2026-10-15T00:00:00Z", bpm=72, sample_type=text)
    response = client.get("/api/views/heartrate/export", params=dict(start_date="2026-10-15", end_date="2026-10-15"))
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0]["采样类型"] == "'" + text
    assert rows[0]["心率（bpm）"] == "72"


def test_sleep_export_keeps_source_and_normalized_fields(api_client):
    client, db = api_client
    insert(db, "sleep_sessions", id="sample", sleep_id="synthetic-sleep", start_at="2026-10-14T23:00:00+08:00", end_at="2026-10-15T07:15:00+08:00", duration_minutes=495, time_asleep_minutes=480, time_awake_minutes=15, stages='[{"stage":"deep","minutes":120}]')
    response = client.get("/api/views/sleep/export", params=dict(start_date="2026-10-15", end_date="2026-10-15"))
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0]["实睡时长（分钟）"] == "480"
    assert rows[0]["源时长（分钟）"] == "495"
    assert rows[0]["深睡（分钟）"] == "120"
    assert '"deep"' in rows[0]["睡眠阶段（源字段）"]


@pytest.mark.asyncio
async def test_stream_disconnect_closes_cursor_and_proxy_response(api_client, monkeypatch):
    _, db = api_client
    insert(db, "stress_samples", id="sample", timestamp="2026-10-15T00:00:00Z", stress_score=26, level="source")
    original = ViewRepository.snapshot
    opened, closed, threads = [], [], []
    @contextmanager
    def observed(repository):
        with original(repository) as connection:
            threads.append(threading.get_ident())
            opened.append(connection)
            try:
                yield connection
            finally:
                threads.append(threading.get_ident())
                closed.append(connection)
    monkeypatch.setattr(ViewRepository, "snapshot", observed)
    request = Request({"type": "http", "app": api.app, "headers": [(b"x-api-key", b"synthetic-api-key")]})
    response = api.get_view_export(request, ViewSelection("stress", "2026-10-15", "2026-10-15"))
    assert not opened
    await response.body_iterator.__anext__()
    await response.body_iterator.__anext__()
    assert len(opened) == 1
    assert not closed
    await response.body_iterator.aclose()
    assert closed == opened
    assert len(set(threads)) == 1
    assert threads[0] != threading.get_ident()


@pytest.mark.asyncio
async def test_stream_send_error_closes_database_in_original_worker(api_client, monkeypatch):
    _, db = api_client
    insert(db, "stress_samples", id="sample", timestamp="2026-10-15T00:00:00Z", stress_score=26, level="source")
    original = ViewRepository.snapshot
    opened, closed = [], []
    @contextmanager
    def observed(repository):
        with original(repository) as connection:
            opened.append(threading.get_ident())
            try:
                yield connection
            finally:
                closed.append(threading.get_ident())
    monkeypatch.setattr(ViewRepository, "snapshot", observed)
    request = Request({"type": "http", "app": api.app, "headers": [(b"x-api-key", b"synthetic-api-key")]})
    response = api.get_view_export(request, ViewSelection("stress", "2026-10-15", "2026-10-15"))
    chunks = 0
    async def send(message):
        nonlocal chunks
        if message["type"] == "http.response.body":
            chunks += 1
            if chunks == 2:
                raise OSError("synthetic disconnect")
    with pytest.raises(OSError, match="synthetic disconnect"):
        await response.stream_response(send)
    assert closed == opened
    assert len(opened) == 1
    assert opened[0] != threading.get_ident()


@pytest.mark.asyncio
async def test_cancelled_read_still_queues_close_on_original_worker(api_client, monkeypatch):
    _, db = api_client
    original = ViewRepository.iter_records
    started, released, closed = threading.Event(), threading.Event(), threading.Event()
    threads = []
    def slow_records(repository, selection, connection):
        threads.append(threading.get_ident())
        try:
            started.set()
            released.wait(5)
            yield from original(repository, selection, connection)
        finally:
            threads.append(threading.get_ident())
            closed.set()
    monkeypatch.setattr(ViewRepository, "iter_records", slow_records)
    insert(db, "stress_samples", id="sample", timestamp="2026-10-15T00:00:00Z", stress_score=26, level="source")
    request = Request({"type": "http", "app": api.app, "headers": [(b"x-api-key", b"synthetic-api-key")]})
    response = api.get_view_export(request, ViewSelection("stress", "2026-10-15", "2026-10-15"))
    await response.body_iterator.__anext__()
    pending = asyncio.create_task(response.body_iterator.__anext__())
    try:
        assert await asyncio.to_thread(started.wait, 3)
        pending.cancel()
        released.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert await asyncio.to_thread(closed.wait, 3)
        assert len(set(threads)) == 1
        assert threads[0] != threading.get_ident()
    finally:
        released.set()
        await response.body_iterator.aclose()
