import httpx
import pytest
import respx

from mi_fitness_mcp.web import create_app


class TrackedStream(httpx.SyncByteStream):
    def __init__(self, fail=False):
        self.consumed = 0
        self.closed = False
        self.fail = fail

    def __iter__(self):
        for n in range(30):
            if self.fail and n == 1:
                raise httpx.ReadError("synthetic read failure")
            self.consumed += 1
            yield f"synthetic-row-{n}\r\n".encode()

    def close(self):
        self.closed = True


def make_client(monkeypatch):
    monkeypatch.setenv("MI_FITNESS_WEB_PASSWORD", "synthetic-web-password")
    app = create_app(backend_url="http://synthetic-backend", api_key="synthetic-api-key", admin_key="synthetic-admin-key")
    app.config["TESTING"] = True
    return app.test_client()


@respx.mock
def test_stream_disconnect_closes_cursor_and_proxy_response(monkeypatch):
    stream = TrackedStream()
    route = respx.get("http://synthetic-backend/api/views/stress/export").mock(return_value=httpx.Response(200,
        stream=stream, headers={"Content-Type": "text/csv; charset=utf-8", "Content-Disposition": 'attachment; filename="synthetic.csv"', "X-API-Key": "must-not-leak", "X-Admin-Key": "must-not-leak", "Authorization": "must-not-leak", "Set-Cookie": "must-not-leak"}))
    client = make_client(monkeypatch)
    response = client.get("/proxy/api/views/stress/export", auth=("admin", "synthetic-web-password"), buffered=False)
    assert response.status_code == 200
    assert response.is_streamed
    assert 0 < stream.consumed < 30
    assert not stream.closed
    assert response.headers["Content-Disposition"].startswith("attachment")
    assert not any(name.lower() in {"x-api-key", "x-admin-key", "authorization", "set-cookie"} for name in response.headers.keys())
    assert route.calls[0].request.headers["X-API-Key"] == "synthetic-api-key"
    response.close()
    assert stream.closed
    assert stream.consumed < 30


@respx.mock
def test_stream_normal_completion_and_error_release_upstream(monkeypatch):
    client = make_client(monkeypatch)
    for fail in [False, True]:
        stream = TrackedStream(fail)
        respx.get("http://synthetic-backend/api/views/body/export").mock(return_value=httpx.Response(200, stream=stream, headers={"Content-Type": "text/csv"}))
        response = client.get("/proxy/api/views/body/export", auth=("admin", "synthetic-web-password"), buffered=False)
        if fail:
            with pytest.raises(httpx.ReadError):
                list(response.response)
        else:
            assert len(b"".join(response.response).splitlines()) == 30
        assert stream.closed
        response.close()


@respx.mock
def test_export_still_requires_web_auth_and_same_origin(monkeypatch):
    client = make_client(monkeypatch)
    assert client.get("/proxy/api/views/stress/export").status_code == 401
    assert client.get("/proxy/api/views/stress/export", auth=("admin", "synthetic-web-password"), headers={"Origin": "https://untrusted.example"}).status_code == 403


@respx.mock
def test_export_connection_failure_uses_existing_error_shape(monkeypatch):
    respx.get("http://synthetic-backend/api/views/stress/export").mock(side_effect=httpx.ConnectError("synthetic unavailable"))
    response = make_client(monkeypatch).get("/proxy/api/views/stress/export", auth=("admin", "synthetic-web-password"))
    assert response.status_code == 502
    assert response.json["error"] == "Flask 代理无法访问后端"
    assert "X-Upstream-Time-Ms" in response.headers
