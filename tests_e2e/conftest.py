"""Browser tests: a real server (SQLite, inline mode) and a real browser.

    pip install -r requirements-e2e.txt && playwright install chromium
    pytest tests_e2e

Locally you can drive Edge or Chrome instead of downloading Chromium:
    E2E_BROWSER_CHANNEL=msedge pytest tests_e2e
Failure screenshots go to e2e-artifacts/.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "e2e-artifacts"
TOKEN = "e2e-access-token-0123456789"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(tmp_path: Path, name: str, token: str = "") -> tuple[subprocess.Popen, str]:
    port = free_port()
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{(tmp_path / (name + '.db')).as_posix()}",
        "REDIS_URL": "",  # inline mode: no Redis needed
        "ACCESS_TOKEN": token,  # explicit, so a developer's .env cannot leak into the test
        "PYTHONUNBUFFERED": "1",
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    log = open(tmp_path / f"{name}.log", "w")  # noqa: SIM115 (lives as long as the server)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "datadigest.api.main:app", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(base + "/readyz", timeout=1).read()
            return proc, base
        except OSError:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError(f"server did not start; log:\n{(tmp_path / f'{name}.log').read_text()}")


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    proc, base = start_server(tmp_path_factory.mktemp("e2e"), "open")
    yield base
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def secured_server(tmp_path_factory):
    proc, base = start_server(tmp_path_factory.mktemp("e2e-secured"), "secured", token=TOKEN)
    yield base
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        channel = os.environ.get("E2E_BROWSER_CHANNEL") or None
        b = p.chromium.launch(channel=channel, headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser, request):
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.set_default_timeout(20_000)
    page.js_errors = []
    page.on("pageerror", lambda exc: page.js_errors.append(str(exc)))  # uncaught exceptions in our scripts
    yield page
    failed = request.node.rep_call.failed if hasattr(request.node, "rep_call") else False
    if failed:
        ARTIFACTS.mkdir(exist_ok=True)
        page.screenshot(path=str(ARTIFACTS / f"{request.node.name}.png"), full_page=True)
    context.close()
    assert not page.js_errors, f"JavaScript errors: {page.js_errors}"


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    setattr(item, "rep_" + outcome.get_result().when, outcome.get_result())


def post(base: str, path: str, token: str = "") -> dict:
    """Create things through the API (faster than clicking, and independent of the UI under test)."""
    req = urllib.request.Request(base + path, method="POST")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path, timeout=20) as r:
        return json.loads(r.read())


def wait_status(base: str, path: str, want: str = "done", seconds: int = 30) -> dict:
    for _ in range(seconds * 2):
        item = get(base, path)
        if item["status"] in (want, "failed"):
            return item
        time.sleep(0.5)
    raise TimeoutError(path)


@pytest.fixture(scope="session")
def sales_id(server):
    dataset = post(server, "/api/samples/sales.csv")
    wait_status(server, f"/api/datasets/{dataset['id']}")
    return dataset["id"]


@pytest.fixture(scope="session")
def production_run_id(server):
    run = post(server, "/api/optimize/examples/production")
    wait_status(server, f"/api/optimizations/{run['id']}")
    return run["id"]
