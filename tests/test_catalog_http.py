"""Exercise actual HTTP requests, including a request in flight during reset."""
import concurrent.futures
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest


@pytest.fixture
def server(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, DEMOSHOP_DB=str(tmp_path / "test.sqlite3"), DEMOSHOP_PRESENTER_TOKEN="test-only-token")
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "sre_agent.catalog.app:app", "--host", "127.0.0.1", "--port", str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/openapi.json", timeout=0.2).close()
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.05)
        else:
            pytest.fail("server did not start")
        yield base
    finally:
        process.terminate()
        process.wait(timeout=10)


def request(base, path, token=None, method="GET"):
    headers = {"X-Presenter-Token": token} if token else {}
    req = urllib.request.Request(base + path, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return response.status, {key.lower(): value for key, value in response.headers.items()}, json.load(response), time.perf_counter() - start
    except urllib.error.HTTPError as response:
        return response.code, {key.lower(): value for key, value in response.headers.items()}, json.load(response), time.perf_counter() - start


def test_real_fault_reset_and_inflight_version(server):
    status, _, baseline, elapsed = request(server, "/api/catalog?q=backpack")
    assert status == 200 and elapsed < 1
    ids = {p["id"] for p in baseline["products"]}
    assert ids == {"trail-backpack", "commuter-backpack"}
    assert request(server, "/presenter/api/inject", method="POST")[0] == 403
    assert request(server, "/presenter/api/inject", "wrong", "POST")[0] == 403
    injected = request(server, "/presenter/api/inject", "test-only-token", "POST")[2]
    with concurrent.futures.ThreadPoolExecutor() as pool:
        slow = pool.submit(request, server, "/api/catalog?q=backpack")
        time.sleep(0.4)
        reset = request(server, "/presenter/api/emergency-reset", "test-only-token", "POST")[2]
        status, headers, result, elapsed = slow.result()
    assert status == 200 and 3.8 <= elapsed < 7
    assert {p["id"] for p in result["products"]} == ids
    assert headers["x-config-version"] == str(injected["version"])
    assert headers["cache-control"] == "no-store"
    status, headers, result, elapsed = request(server, "/api/catalog?q=backpack")
    assert status == 200 and elapsed < 1 and {p["id"] for p in result["products"]} == ids
    assert headers["x-config-version"] == str(reset["version"])
    status, _, detail, _ = request(server, "/api/products/trail-backpack")
    assert status == 200 and detail["product"]["id"] == "trail-backpack"
    audit = request(server, "/presenter/api/state", "test-only-token")[2]["audit"]
    assert [a["action"] for a in audit] == ["emergency-reset", "inject"]
