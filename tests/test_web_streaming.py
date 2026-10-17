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


@pytest.mark.parametrize("method", ["GET", "POST"])
@respx.mock
def test_stream_disconnect_closes_cursor_and_proxy_response(monkeypatch, method):
    stream = TrackedStream()
    route = respx.get("http://synthetic-backend/api/views/stress/export").mock(return_value=httpx.Response(200,
        stream=stream, headers={"Content-Type": "text/csv; charset=utf-8", "Content-Disposition": 'attachment; filename="synthetic.csv"', "X-API-Key": "must-not-leak", "X-Admin-Key": "must-not-leak", "Authorization": "must-not-leak", "Set-Cookie": "must-not-leak"}))
    client = make_client(monkeypatch)
    response = client.open("/proxy/api/views/stress/export", method=method, data={"api_key": "synthetic-browser-key"} if method == "POST" else None, auth=("admin", "synthetic-web-password"), buffered=False)
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


@pytest.mark.parametrize("method", ["GET", "POST"])
@respx.mock
def test_stream_normal_completion_and_error_release_upstream(monkeypatch, method):
    client = make_client(monkeypatch)
    for fail in [False, True]:
        stream = TrackedStream(fail)
        respx.get("http://synthetic-backend/api/views/body/export").mock(return_value=httpx.Response(200, stream=stream, headers={"Content-Type": "text/csv"}))
        response = client.open("/proxy/api/views/body/export", method=method, data={"api_key": "synthetic-browser-key"} if method == "POST" else None, auth=("admin", "synthetic-web-password"), buffered=False)
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


@respx.mock
def test_form_export_uses_the_same_selected_user_as_summary_without_key_in_url(monkeypatch):
    monkeypatch.setenv("MI_FITNESS_WEB_PASSWORD", "synthetic-web-password")
    monkeypatch.delenv("MI_FITNESS_API_KEY", raising=False)
    monkeypatch.delenv("MI_FITNESS_ADMIN_KEY", raising=False)
    client = create_app(backend_url="http://synthetic-backend").test_client()
    selected_key = "synthetic-selected-key"
    seen = []

    def user_response(request):
        selected = request.headers.get("X-API-Key") == selected_key
        seen.append(request)
        if not selected:
            return httpx.Response(401, json={"status": "error"})
        if request.url.path.endswith("/export"):
            return httpx.Response(200, content=b"synthetic-selected-user,csv", headers={"Content-Type": "text/csv", "Content-Disposition": 'attachment; filename="synthetic.csv"'})
        return httpx.Response(200, json={"status": "ok", "synthetic_user": "synthetic-selected-user"})

    respx.get("http://synthetic-backend/api/views/stress").mock(side_effect=user_response)
    respx.get("http://synthetic-backend/api/views/stress/export").mock(side_effect=user_response)
    auth = ("admin", "synthetic-web-password")
    query = "?start_date=2026-10-01&end_date=2026-10-17&pressure_level=mild&limit=11"
    summary = client.get("/proxy/api/views/stress" + query, auth=auth, headers={"X-API-Key": selected_key})
    export = client.post("/proxy/api/views/stress/export" + query, data={"api_key": selected_key, "unexpected": "must-not-forward"}, auth=auth)
    assert summary.status_code == export.status_code == 200
    assert summary.json["synthetic_user"].encode() in export.data
    assert len(seen) == 2
    assert all(request.headers["X-API-Key"] == selected_key for request in seen)
    assert seen[1].method == "GET"
    assert seen[1].content == b""
    assert selected_key not in str(seen[1].url)
    assert "unexpected" not in str(seen[1].url)
    assert seen[1].url.query == seen[0].url.query
    assert "application/x-www-form-urlencoded" not in seen[1].headers.get("Content-Type", "")
    export.close()


@respx.mock
def test_server_key_wins_over_form_and_browser_header(monkeypatch):
    client = make_client(monkeypatch)
    summary_route = respx.get("http://synthetic-backend/api/views/activity").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    summary = client.get("/proxy/api/views/activity", headers={"X-API-Key": "synthetic-header-key"}, auth=("admin", "synthetic-web-password"))
    assert summary.status_code == 200
    assert summary_route.calls[0].request.headers.get_list("X-API-Key") == ["synthetic-api-key"]
    route = respx.get("http://synthetic-backend/api/views/activity/export").mock(return_value=httpx.Response(200, content=b"synthetic", headers={"Content-Type": "text/csv"}))
    response = client.post("/proxy/api/views/activity/export", data={"api_key": "synthetic-form-key"}, headers={"X-API-Key": "synthetic-header-key"}, auth=("admin", "synthetic-web-password"))
    assert response.status_code == 200
    assert route.calls[0].request.headers.get_list("X-API-Key") == ["synthetic-api-key"]
    assert route.calls[0].request.content == b""
    response.close()


@respx.mock
def test_only_whitelisted_exports_translate_post_and_form_key(monkeypatch):
    client = make_client(monkeypatch)
    for path in ["api/views/not-a-kind/export", "api/views/stress/records", "api/sync"]:
        route = respx.post("http://synthetic-backend/" + path).mock(return_value=httpx.Response(200, json={"status": "ok"}))
        response = client.post("/proxy/" + path, data={"api_key": "synthetic-form-key"}, auth=("admin", "synthetic-web-password"))
        assert response.status_code == 200
        request = route.calls[0].request
        assert request.method == "POST"
        assert request.content == b"api_key=synthetic-form-key"
        assert request.headers["X-API-Key"] == "synthetic-api-key"


@respx.mock
def test_form_export_retains_basic_host_and_origin_checks(monkeypatch):
    client = make_client(monkeypatch)
    path = "/proxy/api/views/stress/export"
    assert client.post(path, data={"api_key": "synthetic"}).status_code == 401
    auth = ("admin", "synthetic-web-password")
    assert client.post(path, data={"api_key": "synthetic"}, auth=auth, headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert client.post(path, data={"api_key": "synthetic"}, auth=auth, headers={"Host": "untrusted.example"}).status_code == 403
