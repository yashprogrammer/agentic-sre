import json
import time
import uuid
from contextlib import closing

from fastapi.testclient import TestClient

from sre_agent.catalog.app import app, connect, initialize
from sre_agent.detection.probe import acquire, record, release


def sample(elapsed, generation=1, valid=True):
    now = time.time()
    return {"id": str(uuid.uuid4()), "started_at": now, "finished_at": now, "elapsed_ms": elapsed, "status": 200 if valid else 500, "valid": int(valid), "error": None if valid else "HTTP error", "request_id": str(uuid.uuid4()), "config_version": 2, "fault_generation": generation}


def test_detection_lease_evidence_and_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMOSHOP_DB", str(tmp_path / 'db'))
    monkeypatch.setenv("DEMOSHOP_PRESENTER_TOKEN", "test-token")
    initialize()
    with closing(connect()) as db, db:
        db.execute("UPDATE config SET version=2, generation=1, delay_ms=4000")
    assert acquire('first')
    assert not acquire('second')
    # Failed observations never count as a slow successful measurement.
    inputs = [sample(4100), sample(4100), sample(4200, valid=False), sample(50), sample(70)]
    for s in inputs:
        assert record(s, 'first')
    with closing(connect()) as db:
        assert db.execute('SELECT count(*) FROM alerts').fetchone()[0] == 0
    assert record(sample(4100), 'first')
    assert record(sample(4100), 'first')
    trigger = sample(4100)
    assert record(trigger, 'first')
    assert record(sample(4100), 'first')
    with closing(connect()) as db:
        alerts = db.execute('SELECT * FROM alerts').fetchall()
    assert len(alerts) == 1 and alerts[0]['status'] == 'OPEN'
    assert trigger['id'] in json.loads(alerts[0]['sample_ids'])
    assert not record(sample(4100), 'second')
    with TestClient(app) as client:
        assert client.get('/presenter/api/monitor').status_code == 403
        response = client.get('/presenter/api/monitor', headers={'X-Presenter-Token': 'test-token'}).json()
        assert response['probe_running'] and response['telemetry'] == 'receiving'
        assert response['investigation_available'] is True
        release('first')
        response = client.get('/presenter/api/monitor', headers={'X-Presenter-Token': 'test-token'}).json()
        assert not response['probe_running'] and response['telemetry'] == 'stale'
        assert len(response['alerts']) == 1
