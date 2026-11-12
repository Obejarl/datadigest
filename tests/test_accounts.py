"""Accounts mode: sign-in, who sees which dataset, API tokens and user management."""

import time
import uuid

import pytest

from datadigest import accounts
from datadigest.api import auth
from datadigest.config import Settings, get_settings
from datadigest.models import Dataset, Role, User
from tests.conftest import upload

ADMIN = ("ada@example.org", "correct-horse-battery")
ANN = ("ann@example.org", "ann-password-123")
BOB = ("bob@example.org", "bob-password-123")
MISSING = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def site(client, factory, monkeypatch):
    """The app in accounts mode with one administrator and two members."""
    monkeypatch.setattr(get_settings(), "auth_mode", "accounts")
    monkeypatch.setattr(get_settings(), "secret_key", "test-secret")
    auth._failures.clear()
    with factory() as db:
        accounts.create_user(db, *ADMIN, Role.ADMIN)
        accounts.create_user(db, *ANN)
        accounts.create_user(db, *BOB)
    yield client
    auth._failures.clear()


def sign_in(client, who):
    client.cookies.clear()
    r = client.post("/api/login", json={"email": who[0], "password": who[1]})
    assert r.status_code == 200, r.text
    return client


def token_of(client, who) -> dict:
    token = sign_in(client, who).post("/api/me/token").json()["token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- signing in


def test_everything_needs_a_sign_in(site):
    assert site.get("/api/datasets").status_code == 401
    assert site.get("/", follow_redirects=False).headers["location"] == "/login?next=/"
    status = site.get("/api/auth/status").json()
    assert status == {"required": True, "authenticated": False, "mode": "accounts", "user": None}
    for path in ["/healthz", "/readyz", "/metrics", "/login", "/static/style.css"]:
        assert site.get(path).status_code == 200, path


def test_sign_in_sets_a_session_and_sign_out_ends_it(site):
    r = site.post("/api/login", json={"email": "ANN@example.org ", "password": ANN[1]})  # case and spaces
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert ANN[1] not in cookie
    status = site.get("/api/auth/status").json()
    assert status["authenticated"] and status["user"] == {"email": ANN[0], "role": "member"}
    assert site.get("/api/datasets").status_code == 200
    site.post("/api/logout")
    assert site.get("/api/datasets").status_code == 401


def test_wrong_password_and_unknown_email_look_the_same_and_are_throttled(site):
    wrong = site.post("/api/login", json={"email": ANN[0], "password": "nope"})
    unknown = site.post("/api/login", json={"email": "nobody@example.org", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    for _ in range(3):
        site.post("/api/login", json={"email": ANN[0], "password": "nope"})
    blocked = site.post("/api/login", json={"email": ANN[0], "password": ANN[1]})  # even the right one
    assert blocked.status_code == 429


def test_sessions_cannot_be_forged_or_outlive_their_expiry(factory):
    settings = Settings(auth_mode="accounts", secret_key="k1")
    with factory() as db:
        user = accounts.create_user(db, *ANN)
    session = accounts.make_session(user.id, settings)
    assert accounts.read_session(session, settings) == user.id
    assert accounts.read_session(session, Settings(auth_mode="accounts", secret_key="k2")) is None
    body, _, signature = session.rpartition(".")
    assert accounts.read_session(f"{body}.{'0' * len(signature)}", settings) is None
    assert accounts.read_session("garbage", settings) is None
    later = time.time() + accounts.SESSION_SECONDS + 1
    assert accounts.read_session(session, settings, now=later) is None


def test_passwords_are_hashed_with_a_salt():
    first, second = accounts.hash_password("a-long-password"), accounts.hash_password("a-long-password")
    assert first != second and "a-long-password" not in first
    assert accounts.verify_password("a-long-password", first)
    assert not accounts.verify_password("another-password", first)
    assert not accounts.verify_password("a-long-password", "not-a-hash")


# ---------------------------------------------------------------- who sees what


def test_members_see_only_their_own_datasets(site):
    mine = upload(sign_in(site, ANN)).json()["id"]
    theirs = upload(sign_in(site, BOB), "tr_survey.csv").json()["id"]

    assert [d["id"] for d in site.get("/api/datasets").json()] == [theirs]  # signed in as Bob
    for call in (
        lambda: site.get(f"/api/datasets/{mine}"),
        lambda: site.get(f"/api/datasets/{mine}/profile"),
        lambda: site.get(f"/api/datasets/{mine}/charts"),
        lambda: site.get(f"/api/datasets/{mine}/report"),
        lambda: site.post(f"/api/datasets/{mine}/reprocess"),
        lambda: site.delete(f"/api/datasets/{mine}"),
    ):
        assert call().status_code == 404  # the same answer as for an id that does not exist
    assert site.get(f"/api/datasets/{MISSING}").status_code == 404

    sign_in(site, ANN)
    assert [d["id"] for d in site.get("/api/datasets").json()] == [mine]
    assert site.get(f"/api/datasets/{mine}/profile").status_code == 200  # Bob's delete did nothing
    assert site.get("/api/stats").json()["datasets"] == 1
    assert site.get("/api/me").json()["datasets"] == 1


def test_administrators_see_everything(site):
    mine = upload(sign_in(site, ANN)).json()["id"]
    theirs = upload(sign_in(site, BOB)).json()["id"]
    sign_in(site, ADMIN)
    assert {d["id"] for d in site.get("/api/datasets").json()} == {mine, theirs}
    assert site.get("/api/stats").json()["datasets"] == 2
    assert site.get(f"/api/datasets/{mine}/report").status_code == 200
    assert site.delete(f"/api/datasets/{theirs}").status_code == 204


def test_samples_belong_to_whoever_loaded_them(site, factory):
    dataset_id = sign_in(site, ANN).post("/api/samples/sales.csv").json()["id"]
    with factory() as db:
        owner = db.get(User, db.get(Dataset, uuid.UUID(dataset_id)).owner_id)
    assert owner.email == ANN[0]
    assert sign_in(site, BOB).get(f"/api/datasets/{dataset_id}").status_code == 404


# ---------------------------------------------------------------- API tokens


def test_an_api_token_works_for_scripts_and_can_be_replaced_or_revoked(site, factory):
    headers = token_of(site, ANN)
    assert headers["Authorization"].startswith("Bearer dd_")
    with factory() as db:  # only the hash is stored
        stored = db.query(User).filter_by(email=ANN[0]).one().token_hash
    assert stored and stored not in headers["Authorization"]

    dataset_id = upload(site, headers=headers).json()["id"]
    assert site.get(f"/api/datasets/{dataset_id}", headers=headers).status_code == 200
    assert site.get("/api/me", headers=headers).json()["has_token"] is True
    assert site.get("/api/datasets", headers={"Authorization": "Bearer dd_wrong"}).status_code == 401
    assert site.get("/api/datasets", headers={"Authorization": "Bearer wrong"}).status_code == 401

    newer = token_of(site, ANN)
    assert site.get("/api/datasets", headers=headers).status_code == 401  # the old one stopped working
    assert site.delete("/api/me/token", headers=newer).status_code == 204
    assert site.get("/api/datasets", headers=newer).status_code == 401


def test_changing_your_password(site):
    sign_in(site, ANN)
    change = lambda current, new: site.post(  # noqa: E731
        "/api/me/password", json={"current_password": current, "new_password": new}
    )
    assert change("not-my-password", "a-brand-new-password").status_code == 403
    assert change(ANN[1], "short").status_code == 422
    assert change(ANN[1], "a-brand-new-password").status_code == 204
    site.cookies.clear()
    assert site.post("/api/login", json={"email": ANN[0], "password": ANN[1]}).status_code == 401
    assert (
        site.post("/api/login", json={"email": ANN[0], "password": "a-brand-new-password"}).status_code == 200
    )


# ---------------------------------------------------------------- managing users


def test_only_administrators_manage_users(site):
    sign_in(site, ANN)
    assert site.get("/api/users").status_code == 403
    assert (
        site.post("/api/users", json={"email": "x@example.org", "password": "long-enough-pw"}).status_code
        == 403
    )
    sign_in(site, ADMIN)
    users = site.get("/api/users").json()
    assert [u["email"] for u in users] == [ADMIN[0], ANN[0], BOB[0]]
    assert all("password" not in key for u in users for key in u)


def test_creating_users_checks_the_input(site):
    sign_in(site, ADMIN)
    create = lambda **body: site.post("/api/users", json=body)  # noqa: E731
    created = create(email="Cem@Example.org", password="cem-password-123", role="admin")
    assert created.status_code == 201 and created.json()["email"] == "cem@example.org"
    assert create(email="cem@example.org", password="cem-password-123").status_code == 422  # taken
    assert create(email="not-an-email", password="cem-password-123").status_code == 422
    assert create(email="dan@example.org", password="short").status_code == 422
    assert create(email="dan@example.org", password="dan-password-123", role="owner").status_code == 422


def test_a_disabled_account_is_locked_out_at_once(site):
    headers = token_of(site, BOB)
    bob_session = sign_in(site, BOB).cookies.get("dd_session")
    sign_in(site, ADMIN)
    bob_id = next(u["id"] for u in site.get("/api/users").json() if u["email"] == BOB[0])
    assert site.patch(f"/api/users/{bob_id}", json={"is_active": False}).status_code == 200

    site.cookies.clear()
    site.cookies.set("dd_session", bob_session)
    assert site.get("/api/datasets").status_code == 401  # the cookie has not expired, the account has
    site.cookies.clear()
    assert site.get("/api/datasets", headers=headers).status_code == 401
    assert site.post("/api/login", json={"email": BOB[0], "password": BOB[1]}).status_code == 401


def test_deleting_a_user_removes_their_datasets(site, factory):
    dataset_id = upload(sign_in(site, BOB)).json()["id"]
    sign_in(site, ADMIN)
    bob_id = next(u["id"] for u in site.get("/api/users").json() if u["email"] == BOB[0])
    assert site.get("/api/users").json()[2]["datasets"] == 1
    assert site.delete(f"/api/users/{bob_id}").status_code == 204
    assert site.get(f"/api/datasets/{dataset_id}").status_code == 404
    with factory() as db:
        assert db.get(Dataset, uuid.UUID(dataset_id)) is None
    assert site.delete(f"/api/users/{bob_id}").status_code == 404


def test_administrators_cannot_lock_themselves_out(site):
    sign_in(site, ADMIN)
    me = site.get("/api/me").json()["id"]
    assert site.patch(f"/api/users/{me}", json={"role": "member"}).status_code == 409
    assert site.patch(f"/api/users/{me}", json={"is_active": False}).status_code == 409
    assert site.delete(f"/api/users/{me}").status_code == 409
    ann = next(u["id"] for u in site.get("/api/users").json() if u["email"] == ANN[0])
    promoted = site.patch(f"/api/users/{ann}", json={"role": "admin", "password": "reset-by-an-admin"})
    assert promoted.json()["role"] == "admin"
    assert sign_in(site, (ANN[0], "reset-by-an-admin")).get("/api/users").status_code == 200


# ---------------------------------------------------------------- setting it up


def test_the_first_administrator_comes_from_the_environment(factory):
    settings = Settings(
        auth_mode="accounts", admin_email="root@example.org", admin_password="root-password-1"
    )
    assert accounts.bootstrap_admin(factory, settings).role == Role.ADMIN
    assert accounts.bootstrap_admin(factory, settings) is None  # only when there are no users yet
    assert accounts.bootstrap_admin(factory, Settings(admin_email="a@b.co", admin_password="x" * 12)) is None


def test_the_command_line_adds_and_lists_users(factory, capsys):
    assert (
        accounts.main(["add", "eve@example.org", "--admin", "--password", "eve-password-123"], factory) == 0
    )
    assert accounts.main(["add", "eve@example.org", "--password", "eve-password-123"], factory) == 1
    assert accounts.main(["add", "x@example.org", "--password", "short"], factory) == 1
    assert accounts.main(["list"], factory) == 0
    out = capsys.readouterr()
    assert "eve@example.org\tadmin\tactive" in out.out
    assert "already has an account" in out.err and "at least 10 characters" in out.err


def test_account_calls_say_so_when_accounts_are_off(client):
    assert client.get("/api/me").status_code == 404
    assert client.get("/api/users").status_code == 404
    assert Settings(auth_mode="").auth_mode is None
    with pytest.raises(ValueError):
        Settings(auth_mode="ldap")


def test_accounts_take_precedence_over_the_shared_token(site, monkeypatch):
    monkeypatch.setattr(get_settings(), "access_token", "shared-token")
    assert site.get("/api/datasets", headers={"Authorization": "Bearer shared-token"}).status_code == 401
    assert sign_in(site, ANN).get("/api/datasets").status_code == 200


def test_optimization_runs_follow_their_dataset(site):
    ann_run = sign_in(site, ANN).post("/api/optimize/examples/production").json()
    assert site.get(f"/api/optimizations/{ann_run['id']}").json()["result_status"] == "optimal"

    sign_in(site, BOB)
    assert site.get("/api/optimizations").json() == []
    for method, path in [
        ("get", f"/api/optimizations/{ann_run['id']}"),
        ("get", f"/api/optimizations/{ann_run['id']}/report"),
        ("delete", f"/api/optimizations/{ann_run['id']}"),
    ]:
        assert getattr(site, method)(path).status_code == 404, path
    # Bob cannot point a solver at Ann's dataset either.
    body = {"dataset_id": ann_run["dataset_id"], "kind": "assignment", "params": {"agent_column": "product"}}
    assert site.post("/api/optimizations", json=body).status_code == 404

    assert [o["id"] for o in sign_in(site, ADMIN).get("/api/optimizations").json()] == [ann_run["id"]]
    assert [o["id"] for o in sign_in(site, ANN).get("/api/optimizations").json()] == [ann_run["id"]]
