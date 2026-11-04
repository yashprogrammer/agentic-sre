"""Local-only restore and verification Activities; not a production authorization boundary."""
import hashlib
import json
import time
from contextlib import closing
from temporalio import activity
from sre_agent.catalog.app import connect


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


@activity.defn(name='execute_approved_restore')
async def execute_approved_restore(request: dict) -> dict:
    proposal, decision = request['proposal'], request['decision']
    digest = hashlib.sha256(canonical(proposal).encode()).hexdigest()
    action_id = hashlib.sha256(canonical(['temporal-local', proposal['incident_id'], proposal['proposal_id'], digest]).encode()).hexdigest()
    now = time.time()
    with closing(connect()) as db:
        db.execute('BEGIN IMMEDIATE')
        receipt = db.execute('SELECT * FROM action_receipts WHERE action_id=?', (action_id,)).fetchone()
        if receipt:
            db.rollback()
            return {'status':'SUCCEEDED', 'action_id':action_id, 'applied_version':receipt['applied_version'], 'applied_at':receipt['applied_at']}
        incident = db.execute('SELECT * FROM incidents WHERE id=?', (proposal['incident_id'],)).fetchone()
        config = db.execute('SELECT * FROM config WHERE id=1').fetchone()
        good = db.execute('SELECT * FROM good_configs WHERE version=? AND digest=?', (proposal['restore_version'], proposal['restore_config_digest'])).fetchone()
        good_digest = hashlib.sha256(canonical({'delay_ms':good['delay_ms'], 'version':good['version']}).encode()).hexdigest() if good else None
        valid = (incident and incident['phase'] == 'APPROVED' and incident['decision'] == 'APPROVE' and incident['proposal_hash'] == digest == request['proposal_hash'] and incident['decision_request_id'] == decision.get('request_id') and decision.get('decision') == 'APPROVE' and decision.get('accepted') is True and now < proposal['expires_at'] and proposal['action'] == 'restore_service_config' and proposal['target'] == 'catalog' and good and good['delay_ms'] == 0 and good_digest == good['digest'] and config['version'] == proposal['expected_config_version'] and config['generation'] == proposal['expected_generation'])
        if not valid:
            db.rollback()
            return {'status':'DENIED'}
        version = config['version'] + 1
        db.execute('UPDATE config SET version=?, delay_ms=? WHERE id=1', (version, good['delay_ms']))
        db.execute('INSERT INTO action_receipts VALUES (?,?,?,?,?)', (action_id, incident['id'], digest, version, now))
        db.execute("INSERT INTO audit (id, action, version, generation) VALUES (?, 'temporal-approved-restore', ?, ?)", (action_id, version, config['generation']))
        db.execute("UPDATE incidents SET phase='VERIFYING', action_id=?, applied_at=?, applied_version=?, updated_at=? WHERE id=?", (action_id, now, version, now, incident['id']))
        db.commit()
    return {'status':'SUCCEEDED', 'action_id':action_id, 'applied_version':version, 'applied_at':now}


@activity.defn(name='verify_catalog')
async def verify_catalog(request: dict) -> dict:
    action, proposal = request['action'], request['proposal']
    with closing(connect()) as db:
        config = db.execute('SELECT version, generation FROM config WHERE id=1').fetchone()
        if config['version'] != action['applied_version'] or config['generation'] != proposal['expected_generation']:
            return {'valid':False, 'target_changed':True}
        sample = db.execute('SELECT * FROM probe_samples WHERE started_at>? ORDER BY started_at ASC LIMIT 1', (max(action['applied_at'], request.get('observed_after', action['applied_at'])),)).fetchone()
        if not sample:
            return {'pending':True}
        return {'id':sample['id'], 'valid':bool(sample['valid']), 'elapsed_ms':sample['elapsed_ms'], 'started_at':sample['started_at'], 'config_version':sample['config_version'], 'fault_generation':sample['fault_generation']}
