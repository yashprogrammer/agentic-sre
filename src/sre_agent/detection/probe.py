"""Independent, low-rate local HTTP probe. Run explicitly; never started by the app."""
import json
import math
import os
import signal
import time
import urllib.error
import urllib.request
import uuid
from contextlib import closing

from sre_agent.catalog.app import connect, initialize

URL = "http://127.0.0.1:8000/api/catalog?q=backpack"
EXPECTED = {"trail-backpack", "commuter-backpack"}
INTERVAL = 5.0
try:
    MAX_DURATION = min(21600.0, max(60.0, float(os.environ.get('DEMOSHOP_PROBE_MAX_SECONDS', '900'))))
except ValueError:
    MAX_DURATION = 900.0
LEASE_SECONDS = 30.0


def acquire(owner):
    now = time.time()
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM probe_lease WHERE target='catalog'").fetchone()
        if row and row["expires_at"] > now:
            db.rollback()
            return False
        db.execute("INSERT INTO probe_lease VALUES ('catalog', ?, ?) ON CONFLICT(target) DO UPDATE SET owner=excluded.owner, expires_at=excluded.expires_at", (owner, now + LEASE_SECONDS))
        db.commit()
    return True


def renew(owner):
    with closing(connect()) as db, db:
        cursor = db.execute("UPDATE probe_lease SET expires_at=? WHERE target='catalog' AND owner=? AND expires_at>?", (time.time() + LEASE_SECONDS, owner, time.time()))
        return cursor.rowcount == 1


def release(owner):
    with closing(connect()) as db, db:
        db.execute("DELETE FROM probe_lease WHERE target='catalog' AND owner=?", (owner,))


def collect():
    started = time.time()
    timer = time.monotonic()
    sample = {"id": str(uuid.uuid4()), "started_at": started, "status": None, "valid": 0, "error": None, "request_id": None, "config_version": None, "fault_generation": None}
    try:
        req = urllib.request.Request(URL, headers={"Cache-Control": "no-store"})
        with urllib.request.urlopen(req, timeout=8) as response:
            sample["status"] = response.status
            sample["request_id"] = response.headers.get("X-Request-ID")
            sample["config_version"] = int(response.headers["X-Config-Version"])
            sample["fault_generation"] = int(response.headers["X-Fault-Generation"])
            body = json.load(response)
            products = body.get("products")
            valid = isinstance(products, list) and all(isinstance(p, dict) and isinstance(p.get("id"), str) for p in products) and len(products) == len(EXPECTED) and {p["id"] for p in products} == EXPECTED
            sample["valid"] = int(response.status == 200 and valid and bool(sample["request_id"]))
            if not sample["valid"]:
                sample["error"] = "Incorrect response or missing request ID"
    except urllib.error.HTTPError as exc:
        sample["status"] = exc.code
        sample["error"] = "HTTP error"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        sample["error"] = type(exc).__name__
    sample["elapsed_ms"] = round((time.monotonic() - timer) * 1000, 2)
    sample["finished_at"] = time.time()
    return sample


def record(sample, owner):
    """Persist evidence and detect atomically only while this runner owns the lease."""
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        lease = db.execute("SELECT owner, expires_at FROM probe_lease WHERE target='catalog'").fetchone()
        if not lease or lease["owner"] != owner or lease["expires_at"] <= time.time():
            db.rollback()
            return False
        db.execute("INSERT INTO probe_samples VALUES (:id, :started_at, :finished_at, :elapsed_ms, :status, :valid, :error, :request_id, :config_version, :fault_generation)", sample)
        current = db.execute("SELECT generation FROM config WHERE id=1").fetchone()["generation"]
        rows = db.execute("SELECT * FROM probe_samples WHERE started_at >= ? ORDER BY started_at DESC LIMIT 5", (sample["finished_at"] - 60,)).fetchall()
        # Include failed observations in the five; never count them as slow successes.
        slow = [r for r in rows if r["valid"] and r["fault_generation"] == current and r["elapsed_ms"] > 2000]
        if len(rows) == 5 and len(slow) >= 3 and sample["fault_generation"] == current:
            db.execute("INSERT OR IGNORE INTO alerts VALUES (?, ?, ?, ?, 'OPEN')", (str(uuid.uuid4()), current, time.time(), json.dumps([r["id"] for r in rows])))
        db.commit()
    return True


def main():
    initialize()
    owner = str(uuid.uuid4())
    if not acquire(owner):
        raise SystemExit("A probe already holds the catalog lease.")
    stopping = False
    def stop(_signal, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    start = time.monotonic()
    next_start = start
    print(f"Catalog probe started; Ctrl-C stops it. Maximum runtime: {int(MAX_DURATION // 60)} minutes.", flush=True)
    try:
        while not stopping and time.monotonic() - start < MAX_DURATION:
            now = time.monotonic()
            if now < next_start:
                time.sleep(min(next_start - now, 0.25))
                continue
            # Leave enough time for the bounded HTTP timeout before the run deadline.
            if time.monotonic() - start + 8 >= MAX_DURATION:
                break
            if not renew(owner):
                print("Probe lease lost; stopping.", flush=True)
                break
            sample = collect()
            if not record(sample, owner):
                print("Probe lease lost before recording; stopping.", flush=True)
                break
            print(f"Probe: {sample['elapsed_ms']:.0f} ms, status={sample['status']}, valid={bool(sample['valid'])}, generation={sample['fault_generation']}", flush=True)
            # Skip missed slots rather than overlapping or issuing catch-up traffic.
            next_start = start + (math.floor((time.monotonic() - start) / INTERVAL) + 1) * INTERVAL
    finally:
        release(owner)
        print("Catalog probe stopped.", flush=True)


if __name__ == "__main__":
    main()
