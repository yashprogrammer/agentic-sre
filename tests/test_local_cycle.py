import json
import time
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from sre_agent.catalog.app import app, connect, initialize
from sre_agent.detection.probe import acquire, record, release
from sre_agent.workers.local import step
from test_detection import sample


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    monkeypatch.setenv('DEMOSHOP_DB', str(tmp_path / 'db'))
    monkeypatch.setenv('DEMOSHOP_PRESENTER_TOKEN', 'operator')
    initialize()
    assert acquire('probe')
    with TestClient(app) as client:
        headers = {'X-Presenter-Token': 'operator'}
        for _ in range(5):
            assert record(sample(20, generation=0) | {'config_version': 1}, 'probe')
        assert client.post('/presenter/api/inject', headers=headers).status_code == 200
        for _ in range(5):
            assert record(sample(4100, generation=1), 'probe')
        state = client.get('/presenter/api/monitor', headers=headers).json()
        alert_id = state['alerts'][0]['id']
        yield client, headers, alert_id
    release('probe')


def start(client, headers, alert):
    response = client.post(f'/presenter/api/alerts/{alert}/investigate', headers=headers)
    assert response.status_code == 200
    incident = response.json()['id']
    assert client.post(f'/presenter/api/alerts/{alert}/investigate', headers=headers).json()['id'] == incident
    assert step()
    state = client.get('/presenter/api/monitor', headers=headers).json()
    return state['incidents'][0]


def test_approved_action_once_and_requires_five_new_correct_samples(scenario):
    client, headers, alert = scenario
    incident = start(client, headers, alert)
    assert incident['phase'] == 'WAITING_APPROVAL'
    endpoint = f"/presenter/api/incidents/{incident['id']}/decision"
    body = {'decision': 'APPROVE', 'proposal_hash': incident['proposal_hash'], 'request_id': 'once'}
    assert client.post(endpoint, json=body).status_code == 403
    assert client.post(endpoint, headers=headers, json=body | {'proposal_hash': 'bad'}).status_code == 409
    assert client.post(endpoint, headers=headers, json=body).status_code == 200
    assert client.post(endpoint, headers=headers, json=body).status_code == 200
    assert step()
    with closing(connect()) as db:
        row = db.execute('SELECT * FROM incidents').fetchone()
        assert row['phase'] == 'VERIFYING' and row['applied_version'] == 3
        assert db.execute('SELECT delay_ms FROM config').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM action_receipts').fetchone()[0] == 1
    # A failure breaks the consecutive streak; old-version samples cannot count.
    for s in [sample(10, 1) | {'config_version': 3}, sample(10, 1) | {'config_version': 2}, sample(10, 1) | {'config_version': 3}]:
        assert record(s, 'probe')
    step()
    with closing(connect()) as db:
        assert db.execute('SELECT phase FROM incidents').fetchone()[0] == 'VERIFYING'
    for _ in range(5):
        assert record(sample(20, 1) | {'config_version': 3}, 'probe')
    step()
    state = client.get('/presenter/api/monitor', headers=headers).json()
    assert state['incidents'][0]['phase'] == 'RESOLVED'
    assert len(state['incidents'][0]['verification_ids']) == 5
    assert state['incidents'][0]['windows']['baseline']['count'] == 5
    assert state['incidents'][0]['windows']['recovery']['correct_count'] == 5
    assert state['alerts'][0]['status'] == 'RECOVERED'


def test_rejection_and_changed_generation_prevent_restore(scenario):
    client, headers, alert = scenario
    incident = start(client, headers, alert)
    endpoint = f"/presenter/api/incidents/{incident['id']}/decision"
    body = {'decision': 'REJECT', 'proposal_hash': incident['proposal_hash'], 'request_id': 'reject'}
    assert client.post(endpoint, headers=headers, json=body).status_code == 200
    assert not step()
    with closing(connect()) as db:
        assert db.execute('SELECT delay_ms FROM config').fetchone()[0] == 4000
        assert db.execute('SELECT count(*) FROM action_receipts').fetchone()[0] == 0


def test_approved_stale_generation_is_not_applied(scenario):
    client, headers, alert = scenario
    incident = start(client, headers, alert)
    body = {'decision': 'APPROVE', 'proposal_hash': incident['proposal_hash'], 'request_id': 'approve'}
    assert client.post(f"/presenter/api/incidents/{incident['id']}/decision", headers=headers, json=body).status_code == 200
    assert client.post('/presenter/api/inject', headers=headers).status_code == 200
    step()
    with closing(connect()) as db:
        assert db.execute('SELECT phase FROM incidents').fetchone()[0] == 'NEEDS_MANUAL_REVIEW'
        assert db.execute('SELECT delay_ms FROM config').fetchone()[0] == 4000
        assert db.execute('SELECT count(*) FROM action_receipts').fetchone()[0] == 0


def test_verification_timeout_is_unresolved(scenario):
    client, headers, alert = scenario
    incident = start(client, headers, alert)
    body = {'decision': 'APPROVE', 'proposal_hash': incident['proposal_hash'], 'request_id': 'approve'}
    assert client.post(f"/presenter/api/incidents/{incident['id']}/decision", headers=headers, json=body).status_code == 200
    step()
    with closing(connect()) as db, db:
        db.execute('UPDATE incidents SET applied_at=?', (time.time() - 121,))
    step()
    with closing(connect()) as db:
        assert db.execute('SELECT phase FROM incidents').fetchone()[0] == 'UNRESOLVED'
        assert db.execute('SELECT status FROM alerts').fetchone()[0] != 'RECOVERED'


def test_new_fault_during_verification_cannot_resolve(scenario):
    client, headers, alert = scenario
    incident = start(client, headers, alert)
    body = {'decision': 'APPROVE', 'proposal_hash': incident['proposal_hash'], 'request_id': 'approve'}
    assert client.post(f"/presenter/api/incidents/{incident['id']}/decision", headers=headers, json=body).status_code == 200
    step()
    for _ in range(5):
        assert record(sample(10, 1) | {'config_version': 3}, 'probe')
    assert client.post('/presenter/api/inject', headers=headers).status_code == 200
    step()
    with closing(connect()) as db:
        assert db.execute('SELECT phase FROM incidents').fetchone()[0] == 'UNRESOLVED'
        assert db.execute('SELECT status FROM alerts').fetchone()[0] != 'RECOVERED'
        assert db.execute('SELECT delay_ms FROM config').fetchone()[0] == 4000


def test_local_worker_restarts_across_approval(scenario):
    import os
    import subprocess
    import sys

    client, headers, alert = scenario
    incident_id = client.post(f'/presenter/api/alerts/{alert}/investigate', headers=headers).json()['id']
    def run_worker_until(wanted):
        process = subprocess.Popen([sys.executable, '-m', 'sre_agent.workers.local'], env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                with closing(connect()) as db:
                    row = db.execute('SELECT phase FROM incidents WHERE id=?', (incident_id,)).fetchone()
                if row['phase'] == wanted:
                    return
                if process.poll() is not None:
                    pytest.fail('Worker exited unexpectedly')
                time.sleep(.1)
            pytest.fail(f'Worker did not reach {wanted}')
        finally:
            process.terminate()
            process.wait(timeout=5)
    run_worker_until('WAITING_APPROVAL')
    incident = client.get('/presenter/api/monitor', headers=headers).json()['incidents'][0]
    decision = {'decision': 'APPROVE', 'proposal_hash': incident['proposal_hash'], 'request_id': 'restart'}
    assert client.post(f'/presenter/api/incidents/{incident_id}/decision', headers=headers, json=decision).status_code == 200
    run_worker_until('VERIFYING')
    with closing(connect()) as db:
        assert db.execute('SELECT count(*) FROM action_receipts').fetchone()[0] == 1
        assert db.execute('SELECT delay_ms FROM config').fetchone()[0] == 0


def test_missing_verified_baseline_needs_manual_review(tmp_path, monkeypatch):
    monkeypatch.setenv('DEMOSHOP_DB', str(tmp_path / 'db'))
    monkeypatch.setenv('DEMOSHOP_PRESENTER_TOKEN', 'operator')
    initialize()
    assert acquire('probe')
    try:
        with TestClient(app) as client:
            headers = {'X-Presenter-Token': 'operator'}
            assert client.post('/presenter/api/inject', headers=headers).status_code == 200
            for _ in range(5):
                assert record(sample(4100, 1), 'probe')
            alert = client.get('/presenter/api/monitor', headers=headers).json()['alerts'][0]['id']
            assert client.post(f'/presenter/api/alerts/{alert}/investigate', headers=headers).status_code == 200
            step()
            incident = client.get('/presenter/api/monitor', headers=headers).json()['incidents'][0]
            assert incident['phase'] == 'NEEDS_MANUAL_REVIEW'
            assert incident['proposal'] is None
            with closing(connect()) as db:
                assert db.execute('SELECT delay_ms FROM config').fetchone()[0] == 4000
    finally:
        release('probe')


def test_expired_proposal_cannot_be_approved(scenario, monkeypatch):
    client, headers, alert = scenario
    incident = start(client, headers, alert)
    monkeypatch.setattr('sre_agent.catalog.app.time.time', lambda: incident['proposal']['expires_at'] + 1)
    body = {'decision': 'APPROVE', 'proposal_hash': incident['proposal_hash'], 'request_id': 'late'}
    assert client.post(f"/presenter/api/incidents/{incident['id']}/decision", headers=headers, json=body).status_code == 409
    with closing(connect()) as db:
        assert db.execute('SELECT delay_ms FROM config').fetchone()[0] == 4000
        assert db.execute('SELECT count(*) FROM action_receipts').fetchone()[0] == 0


def test_local_worker_cannot_execute_temporal_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('DEMOSHOP_DB', str(tmp_path / 'db'))
    monkeypatch.setenv('DEMOSHOP_ORCHESTRATOR', 'temporal')
    initialize()
    with pytest.raises(RuntimeError, match='disabled'):
        step()
