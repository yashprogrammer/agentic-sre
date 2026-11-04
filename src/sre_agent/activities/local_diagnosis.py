"""Read-only evidence and proposal Activity for the local demonstration."""
import hashlib
import json
import time
import uuid
from contextlib import closing

from temporalio import activity
from sre_agent.catalog.app import connect


@activity.defn(name='diagnose')
async def diagnose(incident: dict) -> dict:
    """Bind one proposal to a current alert, recorded measurements, and baseline."""
    now = time.time()
    with closing(connect()) as db:
        config = db.execute('SELECT * FROM config WHERE id=1').fetchone()
        alert = db.execute('SELECT * FROM alerts WHERE id=?', (incident.get('alert_id'),)).fetchone()
        if not config or not alert or incident.get('target') != 'catalog' or alert['fault_generation'] != incident.get('fault_generation') or config['generation'] != alert['fault_generation'] or config['delay_ms'] != 4000:
            return {'outcome': 'manual_review'}
        try:
            selected = db.execute('SELECT sample_ids FROM investigation_evidence WHERE incident_id=?', (incident.get('incident_id'),)).fetchone()
            evidence_ids = json.loads(selected['sample_ids'] if selected else alert['sample_ids'])
            if not isinstance(evidence_ids, list) or len(evidence_ids) != 5 or len(set(evidence_ids)) != 5 or not all(isinstance(i, str) for i in evidence_ids):
                return {'outcome': 'manual_review'}
            observations = db.execute('SELECT * FROM probe_samples WHERE id IN (?,?,?,?,?)', evidence_ids).fetchall()
        except (TypeError, ValueError):
            return {'outcome': 'manual_review'}
        slow = [r for r in observations if r['valid'] and r['fault_generation'] == config['generation'] and r['config_version'] == config['version'] and r['elapsed_ms'] > 2000]
        if len(observations) != 5 or len(slow) < 3 or min(r['started_at'] for r in observations) < now - 60:
            return {'outcome': 'manual_review'}
        good = db.execute('SELECT * FROM good_configs WHERE version < ? ORDER BY version DESC LIMIT 1', (config['version'],)).fetchone()
        if not good:
            return {'outcome': 'manual_review'}
        canonical = json.dumps({'delay_ms': good['delay_ms'], 'version': good['version']}, sort_keys=True, separators=(',', ':'))
        if good['delay_ms'] != 0 or hashlib.sha256(canonical.encode()).hexdigest() != good['digest']:
            return {'outcome': 'manual_review'}
        try:
            baseline_ids = json.loads(good['evidence_ids'])
            if not isinstance(baseline_ids, list) or len(baseline_ids) != 5 or len(set(baseline_ids)) != 5:
                return {'outcome': 'manual_review'}
            baseline = db.execute('SELECT * FROM probe_samples WHERE id IN (?,?,?,?,?)', baseline_ids).fetchall()
        except (TypeError, ValueError):
            return {'outcome': 'manual_review'}
        if len(baseline) != 5 or not all(r['valid'] and r['elapsed_ms'] < 1000 and r['config_version'] == good['version'] for r in baseline):
            return {'outcome': 'manual_review'}
    return {'analysis_samples_ms': [r['elapsed_ms'] for r in observations], 'facts': {'injected_delay_ms': config['delay_ms'], 'verified_good_available': True, 'verified_good_delay_ms': good['delay_ms'], 'slow_requests': len(slow)}, 'proposal': {'schema_version': 1, 'incident_id': incident['incident_id'], 'proposal_id': str(uuid.uuid4()), 'target': 'catalog', 'action': 'restore_service_config', 'expected_generation': config['generation'], 'expected_config_version': config['version'], 'restore_version': good['version'], 'restore_config_digest': good['digest'], 'evidence_ids': evidence_ids, 'baseline_evidence_ids': baseline_ids, 'created_at': now, 'expires_at': now + 600}}
