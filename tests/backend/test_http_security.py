"""Host validation must run before any sensitive route/dependency or streaming."""
import asyncio

import pytest
from starlette.testclient import TestClient

from backend.api import deps
from backend.http_security import LoopbackHostMiddleware, is_loopback_authority
from backend.main import app, is_allowed_origin


@pytest.mark.parametrize("host", [
    "localhost", "LOCALHOST:8765", "127.0.0.1:8765", "127.23.45.67",
    "127.255.255.255:65535", "[::1]", "[::1]:8765", "[0:0:0:0:0:0:0:1]:1",
])
def test_loopback_authorities(host):
    assert is_loopback_authority(host)


@pytest.mark.parametrize("host", [
    "", "evil.example", "localhost.evil.example", "evil-localhost", "localhost.",
    "testserver", "0.0.0.0", "192.168.1.2", "126.255.255.255", "128.0.0.1",
    "127.1", "2130706433", "127.00.0.1", "[::]", "[::ffff:127.0.0.1]",
    "::1", "[::1%lo]", "localhost:", "localhost:0", "localhost:65536",
    "localhost:-1", "localhost:+80", "localhost:80:90", "localhost:abc",
    "localhost:８０", " localhost", "localhost ", "localhost\n", "localhost\t",
    "user@localhost", "localhost/", "localhost?x", "localhost#x", "localhost\\evil",
    "localhost,evil.example", "[127.0.0.1]", "http://localhost",
])
def test_untrusted_or_malformed_authorities(host):
    assert not is_loopback_authority(host)


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/photos"), ("GET", "/api/photos/1/file"),
    ("GET", "/api/photos/1/thumbnail"), ("GET", "/"),
    ("GET", "/assets/app.js"), ("GET", "/review"),
    ("POST", "/api/scans/prepare"), ("OPTIONS", "/api/photos"),
])
def test_reject_before_dependencies_and_file_access(client, monkeypatch, method, path):
    def forbidden_dependency():
        raise AssertionError("Route dependency ran before Host rejection")

    monkeypatch.setitem(app.dependency_overrides, deps.get_image_repo, forbidden_dependency)
    monkeypatch.setitem(app.dependency_overrides, deps.get_scan_engine, forbidden_dependency)
    # FileResponse opens/streams asynchronously; this catches routing to any file handler.
    async def forbidden_file_response(*args, **kwargs):
        raise AssertionError("A file response was reached before Host rejection")

    monkeypatch.setattr("starlette.responses.FileResponse.__call__", forbidden_file_response)
    response = client.request(method, path, headers={
        "Host": "evil.example", "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET", "X-Forwarded-Host": "localhost",
        "Forwarded": "host=localhost;for=127.0.0.1",
    })
    assert response.status_code == 403
    assert "Forbidden Host" in response.json()["detail"]


@pytest.mark.parametrize("host", ["localhost:8765", "127.0.0.1:8765", "[::1]:8765"])
def test_valid_host_routes_normally(client, host):
    assert client.get("/api/photos", headers={"Host": host}).status_code == 200
    assert client.get("/", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("headers", [[], [(b"host", b"localhost"), (b"host", b"evil.example")]])
def test_missing_and_duplicate_raw_host_headers(headers):
    called = []
    messages = []

    async def inner(scope, receive, send):
        called.append(True)

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    asyncio.run(LoopbackHostMiddleware(inner)(
        {"type": "http", "headers": headers}, receive, send,
    ))
    assert not called
    assert messages[0]["status"] == 403


def test_default_testserver_has_no_production_exception(db_path):
    with TestClient(app) as synthetic_client:
        assert synthetic_client.get("/api/photos").status_code == 403


@pytest.mark.parametrize("origin", [
    "http://localhost:8765", "http://127.0.0.1:5173", "https://[::1]:8765/review",
])
def test_local_origins_and_referers(origin):
    assert is_allowed_origin(origin)


@pytest.mark.parametrize("origin", [
    "http://evil.example", "http://testserver", "http://user@localhost", "ftp://localhost",
    "http://localhost:65536", "http://localhost.evil.example", "http://[::1%lo]",
])
def test_origin_policy_has_no_host_or_scheme_bypass(origin):
    assert not is_allowed_origin(origin)


def test_referer_and_cross_site_protection_remain(client):
    assert client.post("/api/scans/prepare", json={"image_ids": []},
                       headers={"Referer": "http://evil.example/page"}).status_code == 403
    assert client.post("/api/scans/prepare", json={"image_ids": []},
                       headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
