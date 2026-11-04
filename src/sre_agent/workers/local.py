"""Local SQLite-backed worker; deterministic diagnosis, not Temporal or an LLM agent."""
import hashlib
import json
import signal
import time
from contextlib import closing

from sre_agent.catalog.app import connect, initialize


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'))


def step():
    now = time.time()
    with closing(connect()) as db:
        db.execute('BEGIN IMMEDIATE')
        mode = db.execute('SELECT orchestrator FROM demo_identity WHERE id=1').fetchone()
        if not mode or mode['orchestrator'] != 'local':
            db.rollback()
            raise RuntimeError('SQLite-only worker is disabled for this demo environment')
        row = db.execute("SELECT * FROM incidents WHERE phase IN ('TRIAGING','WAITING_APPROVAL','APPROVED','VERIFYING') ORDER BY updated_at LIMIT 1").fetchone()
        if not row:
            db.rollback()
            return False
        incident = dict(row)
        config = db.execute('SELECT * FROM config WHERE id=1').fetchone()
        phase = incident['phase']
        if phase == 'TRIAGING':
            alert = db.execute('SELECT * FROM alerts WHERE id=?', (incident['alert_id'],)).fetchone()
            good = db.execute('SELECT * FROM good_configs WHERE version < ? ORDER BY version DESC LIMIT 1', (config['version'],)).fetchone()
            if not alert or alert['fault_generation'] != config['generation'] or config['delay_ms'] != 4000 or not good:
                db.execute("UPDATE incidents SET phase='NEEDS_MANUAL_REVIEW',reason=?,updated_at=? WHERE id=?", ('No current supported fault with a probe-verified known-good configuration.', now, incident['id']))
            else:
                selected = db.execute('SELECT sample_ids FROM investigation_evidence WHERE incident_id=?', (incident['id'],)).fetchone()
                proposal = {'schema_version': 1, 'incident_id': incident['id'], 'proposal_id': str(__import__('uuid').uuid4()), 'action': 'restore_service_config', 'target': 'catalog', 'expected_generation': config['generation'], 'expected_config_version': config['version'], 'restore_version': good['version'], 'restore_config_digest': good['digest'], 'evidence_ids': json.loads(selected['sample_ids'] if selected else alert['sample_ids']), 'baseline_evidence_ids': json.loads(good['evidence_ids']), 'created_at': now, 'expires_at': now + 600}
                digest = hashlib.sha256(canonical(proposal).encode()).hexdigest()
                db.execute("UPDATE incidents SET phase='WAITING_APPROVAL',proposal=?,proposal_hash=?,updated_at=? WHERE id=?", (canonical(proposal), digest, now, incident['id']))
        elif phase == 'WAITING_APPROVAL':
            proposal = json.loads(incident['proposal'])
            if now >= proposal['expires_at']:
                db.execute("UPDATE incidents SET phase='EXPIRED',reason='Approval expired',updated_at=? WHERE id=?", (now, incident['id']))
            else:
                # Rotate pending records so one waiting proposal cannot starve another incident.
                db.execute('UPDATE incidents SET updated_at=? WHERE id=?', (now, incident['id']))
        elif phase == 'APPROVED':
            proposal = json.loads(incident['proposal'])
            expected_hash = hashlib.sha256(canonical(proposal).encode()).hexdigest()
            good = db.execute('SELECT * FROM good_configs WHERE version=? AND digest=?', (proposal['restore_version'], proposal['restore_config_digest'])).fetchone()
            digest = hashlib.sha256(canonical({'delay_ms': good['delay_ms'], 'version': good['version']}).encode()).hexdigest() if good else None
            action_id = hashlib.sha256(canonical(['local', incident['id'], proposal['proposal_id'], expected_hash]).encode()).hexdigest()
            receipt = db.execute('SELECT * FROM action_receipts WHERE action_id=?', (action_id,)).fetchone()
            if receipt:
                db.execute("UPDATE incidents SET phase='VERIFYING', action_id=?, applied_at=?, applied_version=?,updated_at=? WHERE id=?", (action_id, receipt['applied_at'], receipt['applied_version'], now, incident['id']))
            elif incident['decision'] != 'APPROVE' or expected_hash != incident['proposal_hash'] or now >= proposal['expires_at'] or proposal['action'] != 'restore_service_config' or proposal['target'] != 'catalog' or not good or digest != good['digest'] or config['generation'] != proposal['expected_generation'] or config['version'] != proposal['expected_config_version']:
                db.execute("UPDATE incidents SET phase='NEEDS_MANUAL_REVIEW',reason='Approval expired, proposal changed, or target no longer matches.',updated_at=? WHERE id=?", (now, incident['id']))
            else:
                version = config['version'] + 1
                db.execute('UPDATE config SET version=?, delay_ms=? WHERE id=1', (version, good['delay_ms']))
                db.execute('INSERT INTO action_receipts VALUES (?,?,?,?,?)', (action_id, incident['id'], expected_hash, version, now))
                db.execute("INSERT INTO audit (id,action,version,generation) VALUES (?, 'approved-restore', ?, ?)", (action_id, version, config['generation']))
                db.execute("UPDATE incidents SET phase='VERIFYING',action_id=?,applied_at=?,applied_version=?,updated_at=? WHERE id=?", (action_id, now, version, now, incident['id']))
        else:
            samples = db.execute('SELECT * FROM probe_samples WHERE started_at > ? AND finished_at <= ? ORDER BY started_at', (incident['applied_at'], incident['applied_at'] + 120)).fetchall()
            consecutive = []
            proposal = json.loads(incident['proposal'])
            for sample in samples:
                if sample['valid'] and sample['elapsed_ms'] < 1000 and sample['config_version'] == incident['applied_version'] and sample['fault_generation'] == proposal['expected_generation']:
                    consecutive.append(sample['id'])
                    if len(consecutive) == 5:
                        break
                else:
                    consecutive = []
            if config['version'] != incident['applied_version'] or config['generation'] != proposal['expected_generation']:
                db.execute("UPDATE incidents SET phase='UNRESOLVED',reason='Configuration changed during recovery verification.',updated_at=? WHERE id=?", (now, incident['id']))
            elif len(consecutive) == 5:
                db.execute("UPDATE incidents SET phase='RESOLVED',verification_ids=?,updated_at=? WHERE id=?", (json.dumps(consecutive), now, incident['id']))
                db.execute("UPDATE alerts SET status='RECOVERED' WHERE id=?", (incident['alert_id'],))
            elif now - incident['applied_at'] >= 120:
                db.execute("UPDATE incidents SET phase='UNRESOLVED',reason='Five correct, fast post-action probe requests were not observed in time.',updated_at=? WHERE id=?", (now, incident['id']))
            else:
                db.execute('UPDATE incidents SET updated_at=? WHERE id=?', (now, incident['id']))
        db.commit()
    return True


def main():
    initialize()
    stop = False
    def handle(_signum, _frame):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)
    print('Local deterministic investigation worker started. Ctrl-C stops it.', flush=True)
    while not stop:
        step()
        time.sleep(1)
    print('Local worker stopped.', flush=True)


if __name__ == '__main__':
    main()
