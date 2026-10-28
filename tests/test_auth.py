"""Optional access control: off by default, one shared token when ACCESS_TOKEN is set."""

import pytest

from datadigest.api import auth
from datadigest.config import Settings, get_settings
from tests.conftest import upload

TOKEN = "correct-horse-battery-staple"


@pytest.fixture
def secured(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "access_token", TOKEN)
    auth._failures.clear()
    yield client
    auth._failures.clear()


def test_off_by_default_everything_is_open(client):
    assert client.get("/api/auth/status").json() == {"required": False, "authenticated": True}
    assert client.get("/api/datasets").status_code == 200
    assert client.post("/api/login", json={"token": "anything"}).json()["required"] is False


def test_blank_token_means_off():
    assert Settings(access_token="   ").access_token is None
    assert Settings(access_token="").access_token is None
    assert Settings(access_token=" abc ").access_token == "abc"


def test_api_calls_need_the_token(secured):
    r = secured.get("/api/datasets")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert secured.post("/api/samples/sales.csv").status_code == 401
    assert secured.get("/api/datasets", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_bearer_token_works_for_scripts(secured):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    assert secured.get("/api/datasets", headers=headers).status_code == 200
    assert upload(secured, headers=headers).status_code == 202
    assert secured.get("/api/datasets", headers={"Authorization": f"bearer {TOKEN}"}).status_code == 200


def test_pages_redirect_to_login_and_keep_the_destination(secured):
    r = secured.get("/datasets/abc", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login?next=/datasets/abc"
    assert secured.get("/docs", follow_redirects=False).status_code == 303
    assert secured.get("/optimize", follow_redirects=False).status_code == 303


def test_probes_metrics_login_and_static_stay_open(secured):
    for path in ["/healthz", "/readyz", "/metrics", "/login", "/static/style.css", "/api/auth/status"]:
        assert secured.get(path).status_code == 200, path


def test_login_sets_an_httponly_cookie_and_it_opens_everything(secured):
    assert secured.get("/api/auth/status").json() == {"required": True, "authenticated": False}
    r = secured.post("/api/login", json={"token": TOKEN})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "dd_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert TOKEN not in cookie  # the browser never holds the token itself
    assert secured.get("/api/datasets").status_code == 200
    assert secured.get("/", follow_redirects=False).status_code == 200
    assert secured.get("/api/auth/status").json()["authenticated"] is True


def test_wrong_token_is_rejected_without_a_cookie(secured):
    r = secured.post("/api/login", json={"token": "nope"})
    assert r.status_code == 401 and "set-cookie" not in r.headers
    assert secured.get("/api/datasets").status_code == 401


def test_logout_removes_access(secured):
    secured.post("/api/login", json={"token": TOKEN})
    assert secured.get("/api/datasets").status_code == 200
    secured.post("/api/logout")
    assert secured.get("/api/datasets").status_code == 401


def test_a_stale_or_forged_cookie_does_not_work(secured):
    secured.cookies.set("dd_session", "0" * 64)
    assert secured.get("/api/datasets").status_code == 401
    secured.cookies.set("dd_session", TOKEN)  # the raw token is not a valid session value either
    assert secured.get("/api/datasets").status_code == 401


def test_repeated_wrong_tokens_are_throttled_even_for_the_right_one(secured):
    for _ in range(auth.MAX_FAILURES):
        assert secured.post("/api/login", json={"token": "nope"}).status_code == 401
    r = secured.post("/api/login", json={"token": TOKEN})
    assert r.status_code == 429 and r.headers["retry-after"] == "60"


def test_rejected_requests_are_counted_in_the_metrics(secured):
    secured.get("/api/datasets")
    body = secured.get("/metrics").text
    assert 'status="401"' in body


def test_security_headers_are_on_rejections_too(secured):
    r = secured.get("/api/datasets")
    assert r.headers["x-frame-options"] == "DENY"
