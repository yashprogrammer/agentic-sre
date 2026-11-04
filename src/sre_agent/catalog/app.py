"""Local DemoShop request path. This is not the AWS deployment or an SRE runbook."""
import asyncio
import hmac
import hashlib
import json
import os
import re
import sqlite3
import statistics
import time
import uuid
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

PRODUCTS = [
    ("trail-backpack", "Trail Backpack", "A versatile 24L pack for everyday adventures.", "Bags", 79.0, "🎒"),
    ("commuter-backpack", "Commuter Backpack", "A streamlined pack with a padded laptop sleeve.", "Bags", 95.0, "🎒"),
    ("steel-bottle", "Steel Water Bottle", "A reusable insulated bottle for the road.", "Accessories", 28.0, "🥤"),
    ("camp-mug", "Camp Mug", "A lightweight mug for your morning coffee.", "Home", 18.0, "☕"),
    ("weekend-tote", "Weekend Tote", "A roomy canvas tote for everything else.", "Bags", 42.0, "👜"),
    ("field-notebook", "Field Notebook", "A durable notebook for your next good idea.", "Accessories", 12.0, "📓"),
]


def connect():
    path = Path(os.environ.get("DEMOSHOP_DB", ".data/demoshop.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def initialize():
    with closing(connect()) as db, db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS demo_identity (id INTEGER PRIMARY KEY CHECK(id=1), instance_id TEXT NOT NULL, orchestrator TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS products (id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL, category TEXT NOT NULL, price REAL NOT NULL, icon TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, generation INTEGER NOT NULL, delay_ms INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS audit (id TEXT PRIMARY KEY, action TEXT NOT NULL, version INTEGER NOT NULL, generation INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, route TEXT NOT NULL, query TEXT, status INTEGER NOT NULL, elapsed_ms REAL NOT NULL, config_version INTEGER NOT NULL, fault_generation INTEGER NOT NULL, started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS probe_lease (target TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS probe_samples (id TEXT PRIMARY KEY, started_at REAL NOT NULL, finished_at REAL NOT NULL, elapsed_ms REAL NOT NULL, status INTEGER, valid INTEGER NOT NULL, error TEXT, request_id TEXT, config_version INTEGER, fault_generation INTEGER);
        CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY, fault_generation INTEGER NOT NULL UNIQUE, created_at REAL NOT NULL, sample_ids TEXT NOT NULL, status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS good_configs (version INTEGER PRIMARY KEY, delay_ms INTEGER NOT NULL, digest TEXT NOT NULL, verified_at REAL NOT NULL, evidence_ids TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, alert_id TEXT UNIQUE NOT NULL, phase TEXT NOT NULL, proposal TEXT, proposal_hash TEXT, decision TEXT, decision_request_id TEXT, decided_at REAL, created_at REAL NOT NULL, updated_at REAL NOT NULL, reason TEXT, action_id TEXT, applied_at REAL, applied_version INTEGER, verification_ids TEXT);
        CREATE TABLE IF NOT EXISTS investigation_evidence (incident_id TEXT PRIMARY KEY, sample_ids TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS temporal_workflow_links (incident_id TEXT PRIMARY KEY, namespace TEXT NOT NULL, run_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS incident_agentcore (incident_id TEXT PRIMARY KEY, result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS action_receipts (action_id TEXT PRIMARY KEY, incident_id TEXT UNIQUE NOT NULL, proposal_hash TEXT NOT NULL, applied_version INTEGER NOT NULL, applied_at REAL NOT NULL);
        INSERT OR IGNORE INTO config VALUES (1, 1, 0, 0);
        """)
        db.execute("INSERT OR IGNORE INTO demo_identity VALUES (1, ?, 'local')", (str(uuid.uuid4()),))
        mode = os.environ.get("DEMOSHOP_ORCHESTRATOR")
        if mode:
            if mode not in ("local", "temporal"):
                raise ValueError("Unsupported DEMOSHOP_ORCHESTRATOR")
            db.execute("UPDATE demo_identity SET orchestrator=? WHERE id=1", (mode,))
        db.executemany("INSERT OR IGNORE INTO products VALUES (?, ?, ?, ?, ?, ?)", PRODUCTS)


@asynccontextmanager
async def lifespan(_app):
    initialize()
    yield


app = FastAPI(title="DemoShop local catalog", lifespan=lifespan)


def authorize(token: str | None):
    expected = os.environ.get("DEMOSHOP_PRESENTER_TOKEN", "")
    if not expected or not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Presenter authorization required")


async def catalog_request(route: str, query: str | None = None, product_id: str | None = None):
    started = time.perf_counter()
    request_id = str(uuid.uuid4())
    # Capture configuration once per request. An in-flight request retains its version.
    with closing(connect()) as db:
        config = dict(db.execute("SELECT * FROM config WHERE id=1").fetchone())
    await asyncio.sleep(config["delay_ms"] / 1000)
    with closing(connect()) as db:
        if product_id is not None:
            row = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
            result = dict(row) if row else None
        else:
            term = (query or "").strip().casefold()
            rows = db.execute("SELECT * FROM products ORDER BY name").fetchall()
            result = [dict(row) for row in rows if term in (row["name"] + " " + row["description"] + " " + row["category"]).casefold()]
    status = 404 if product_id is not None and result is None else 200
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    # A failed evidence write is explicitly reported, never fabricated.
    recorded = True
    try:
        with closing(connect()) as db, db:
            db.execute("INSERT INTO requests (id, route, query, status, elapsed_ms, config_version, fault_generation) VALUES (?, ?, ?, ?, ?, ?, ?)", (request_id, route, query, status, elapsed, config["version"], config["generation"]))
    except sqlite3.Error:
        recorded = False
    body = {"product": result} if product_id else {"products": result, "query": (query or "").strip()}
    if status == 404:
        body = {"detail": "Product not found"}
    return JSONResponse(body, status_code=status, headers={
        "Cache-Control": "no-store", "X-Request-ID": request_id,
        "X-Config-Version": str(config["version"]), "X-Fault-Generation": str(config["generation"]),
        "Server-Timing": f"catalog;dur={elapsed}", "X-Evidence-Recorded": str(recorded).lower(),
    })


@app.get("/api/catalog")
async def catalog(q: str = ""):
    return await catalog_request("/api/catalog", query=q)


@app.get("/api/products/{product_id}")
async def product(product_id: str):
    return await catalog_request("/api/products/{id}", product_id=product_id)


@app.get("/presenter/api/state")
def state(x_presenter_token: Annotated[str | None, Header()] = None):
    authorize(x_presenter_token)
    with closing(connect()) as db:
        config = dict(db.execute("SELECT version, generation, delay_ms FROM config WHERE id=1").fetchone())
        events = [dict(row) for row in db.execute("SELECT * FROM audit ORDER BY rowid DESC LIMIT 20")]
    return {"config": config, "audit": events}


@app.post("/presenter/api/{action}")
def presenter_action(action: str, request: Request, x_presenter_token: Annotated[str | None, Header()] = None):
    authorize(x_presenter_token)
    # Reject browser cross-origin requests even if an operator has supplied a token.
    verify_origin(request)
    if action not in ("inject", "emergency-reset"):
        raise HTTPException(status_code=404, detail="Unknown action")
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT * FROM config WHERE id=1").fetchone()
        version, generation = old["version"] + 1, old["generation"] + 1
        delay = 4000 if action == "inject" else 0
        if action == "inject" and old["delay_ms"] == 0:
            baseline = db.execute("SELECT * FROM probe_samples WHERE config_version=? AND fault_generation=? AND started_at >= ? ORDER BY started_at DESC LIMIT 5", (old["version"], old["generation"], time.time() - 60)).fetchall()
            if len(baseline) == 5 and all(row["valid"] and row["elapsed_ms"] < 1000 for row in baseline):
                data = json.dumps({"delay_ms": old["delay_ms"], "version": old["version"]}, sort_keys=True, separators=(",", ":"))
                digest = hashlib.sha256(data.encode()).hexdigest()
                db.execute("INSERT OR IGNORE INTO good_configs VALUES (?, ?, ?, ?, ?)", (old["version"], old["delay_ms"], digest, time.time(), json.dumps([row["id"] for row in baseline])))
        db.execute("UPDATE config SET version=?, generation=?, delay_ms=? WHERE id=1", (version, generation, delay))
        receipt = str(uuid.uuid4())
        db.execute("INSERT INTO audit (id, action, version, generation) VALUES (?, ?, ?, ?)", (receipt, action, version, generation))
        db.commit()
    return {"receipt": receipt, "action": action, "version": version, "generation": generation}


@app.get("/presenter/api/monitor")
def monitor(x_presenter_token: Annotated[str | None, Header()] = None):
    authorize(x_presenter_token)
    with closing(connect()) as db:
        lease = db.execute("SELECT expires_at FROM probe_lease WHERE target='catalog' ").fetchone()
        samples = [dict(row) for row in db.execute("SELECT * FROM probe_samples ORDER BY started_at DESC LIMIT 30")]
        alerts = [dict(row) for row in db.execute("SELECT * FROM alerts ORDER BY created_at DESC LIMIT 20")]
        config = dict(db.execute("SELECT version, generation FROM config WHERE id=1").fetchone())
        incidents = [dict(row) for row in db.execute("SELECT * FROM incidents ORDER BY created_at DESC LIMIT 20")]
        for incident in incidents:
            analysis = db.execute("SELECT result FROM incident_agentcore WHERE incident_id=?", (incident["id"],)).fetchone()
            incident["agentcore_analysis"] = json.loads(analysis["result"]) if analysis else None
            link = db.execute("SELECT namespace, run_id FROM temporal_workflow_links WHERE incident_id=?", (incident["id"],)).fetchone()
            incident["temporal_url"] = None
            if link and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*\.[A-Za-z0-9][A-Za-z0-9-]*", link["namespace"]) and re.fullmatch(r"[0-9a-fA-F-]{36}", link["run_id"]):
                incident["temporal_url"] = "https://cloud.temporal.io/namespaces/" + quote(link["namespace"], safe="") + "/workflows/" + quote("demoshop-local-" + incident["id"], safe="") + "/" + quote(link["run_id"], safe="")
            incident["proposal"] = json.loads(incident["proposal"]) if incident["proposal"] else None
            incident["verification_ids"] = json.loads(incident["verification_ids"]) if incident["verification_ids"] else []
            proposal = incident["proposal"]
            incident["windows"] = {}
            if proposal:
                for label, ids in (("baseline", proposal["baseline_evidence_ids"]), ("trigger", proposal["evidence_ids"]), ("recovery", incident["verification_ids"])):
                    if not ids:
                        continue
                    placeholders = ','.join('?' for _ in ids)
                    window = db.execute(f"SELECT * FROM probe_samples WHERE id IN ({placeholders})", ids).fetchall()
                    valid = [row["elapsed_ms"] for row in window if row["valid"]]
                    incident["windows"][label] = {"count": len(window), "correct_count": len(valid), "errors": len(window) - len(valid), "median_ms": round(statistics.median(valid), 2) if valid else None, "min_ms": min(valid) if valid else None, "max_ms": max(valid) if valid else None}
    now = time.time()
    running = bool(lease and lease["expires_at"] > now)
    fresh = bool(running and samples and now - samples[0]["finished_at"] < 20)
    mode = "Temporal Cloud with Groq GPT-OSS 20B/Strands evidence review" if os.environ.get("DEMOSHOP_DIAGNOSIS") == "strands-groq" else ("Temporal Cloud with local Qwen/Strands evidence review" if os.environ.get("DEMOSHOP_DIAGNOSIS") == "strands-local" else ("Temporal Cloud with local deterministic diagnosis" if os.environ.get("DEMOSHOP_ORCHESTRATOR") == "temporal" else "local deterministic rules"))
    return {"probe_running": running, "telemetry": "receiving" if fresh else "stale", "samples": samples, "alerts": alerts, "config": config, "investigation_available": True, "diagnosis_mode": mode, "cloudwatch_enabled": os.environ.get("DEMOSHOP_CLOUDWATCH") == "1", "incidents": incidents}


def verify_origin(request: Request):
    origin = request.headers.get("origin")
    allowed = {"http://localhost:5173", "http://127.0.0.1:5173"}
    if os.environ.get("DEMOSHOP_ALLOWED_ORIGIN") == "http://127.0.0.1:5174":
        allowed.add("http://127.0.0.1:5174")
    public_origin = os.environ.get("DEMOSHOP_PUBLIC_ORIGIN", "")
    if re.fullmatch(r"https://(?:[0-9]{1,3}-){3}[0-9]{1,3}\.sslip\.io", public_origin):
        allowed.add(public_origin)
    if origin and origin not in allowed:
        raise HTTPException(status_code=403, detail="Origin not allowed")


@app.post("/presenter/api/alerts/{alert_id}/investigate")
def investigate(alert_id: str, request: Request, x_presenter_token: Annotated[str | None, Header()] = None):
    authorize(x_presenter_token)
    verify_origin(request)
    now = time.time()
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT id, phase FROM incidents WHERE alert_id=?", (alert_id,)).fetchone()
        if existing:
            db.rollback()
            return dict(existing)
        alert = db.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
        config = db.execute("SELECT * FROM config WHERE id=1").fetchone()
        latest = db.execute("SELECT finished_at FROM probe_samples WHERE fault_generation=? ORDER BY started_at DESC LIMIT 1", (config["generation"],)).fetchone()
        lease = db.execute("SELECT expires_at FROM probe_lease WHERE target='catalog'").fetchone()
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")
        if alert["fault_generation"] != config["generation"] or not latest or now - latest["finished_at"] > 20 or not lease or lease["expires_at"] <= now:
            raise HTTPException(status_code=409, detail="Alert generation is stale or probe telemetry is unavailable")
        samples = db.execute("SELECT * FROM probe_samples WHERE started_at >= ? ORDER BY started_at DESC LIMIT 5", (now - 60,)).fetchall()
        slow = [s for s in samples if s["valid"] and s["elapsed_ms"] > 2000 and s["config_version"] == config["version"] and s["fault_generation"] == config["generation"]]
        if len(samples) != 5 or len(slow) < 3:
            raise HTTPException(status_code=409, detail="Five fresh measurements with at least three slow requests are required")
        incident_id = str(uuid.uuid4())
        db.execute("INSERT INTO incidents (id,alert_id,phase,created_at,updated_at) VALUES (?,?,'TRIAGING',?,?)", (incident_id, alert_id, now, now))
        db.execute("INSERT INTO investigation_evidence VALUES (?,?)", (incident_id, json.dumps([s["id"] for s in samples])))
        db.execute("UPDATE alerts SET status='INVESTIGATING' WHERE id=?", (alert_id,))
        db.commit()
    return {"id": incident_id, "phase": "TRIAGING"}


@app.post("/presenter/api/incidents/{incident_id}/decision")
async def decide(incident_id: str, request: Request, x_presenter_token: Annotated[str | None, Header()] = None):
    authorize(x_presenter_token)
    verify_origin(request)
    body = await request.json()
    if not isinstance(body, dict) or body.get("decision") not in ("APPROVE", "REJECT") or not isinstance(body.get("proposal_hash"), str) or not isinstance(body.get("request_id"), str) or not 1 <= len(body["request_id"]) <= 100:
        raise HTTPException(status_code=400, detail="Invalid decision")
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Incident not found")
        if row["decision_request_id"] == body["request_id"] and row["decision"] == body["decision"] and row["proposal_hash"] == body["proposal_hash"]:
            db.rollback()
            return {"decision": row["decision"], "phase": row["phase"], "incident_id": incident_id}
        if row["phase"] != "WAITING_APPROVAL" or row["proposal_hash"] != body["proposal_hash"]:
            raise HTTPException(status_code=409, detail="Decision is stale or already recorded")
        proposal = json.loads(row["proposal"])
        now = time.time()
        config = db.execute("SELECT version, generation FROM config WHERE id=1").fetchone()
        if now >= proposal["expires_at"] or config["version"] != proposal["expected_config_version"] or config["generation"] != proposal["expected_generation"]:
            raise HTTPException(status_code=409, detail="Proposal expired or configuration changed")
        phase = "APPROVED" if body["decision"] == "APPROVE" else ("REJECTION_PENDING" if os.environ.get("DEMOSHOP_ORCHESTRATOR") == "temporal" else "REJECTED")
        db.execute("UPDATE incidents SET phase=?,decision=?,decision_request_id=?,decided_at=?,updated_at=? WHERE id=?", (phase, body["decision"], body["request_id"], now, now, incident_id))
        db.commit()
    return {"decision": body["decision"], "phase": phase, "incident_id": incident_id}
