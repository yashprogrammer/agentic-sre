"""Local read-only Activity check with isolated SQLite evidence."""
import asyncio
import json
import os
import tempfile
import time
import uuid
from contextlib import closing

from sre_agent.catalog.app import connect, initialize
from sre_agent.detection.probe import acquire, record, release
from sre_agent.activities.local_diagnosis import diagnose
from fastapi.testclient import TestClient
from sre_agent.catalog.app import app


def sample(ms, version, generation):
    now = time.time()
    return {'id': str(uuid.uuid4()), 'started_at': now, 'finished_at': now, 'elapsed_ms': ms, 'status': 200, 'valid': 1, 'error': None, 'request_id': str(uuid.uuid4()), 'config_version': version, 'fault_generation': generation}


async def main():
    with tempfile.TemporaryDirectory() as directory:
        os.environ['DEMOSHOP_DB'] = directory + '/test.sqlite'
        os.environ['DEMOSHOP_PRESENTER_TOKEN'] = 'isolated-test'
        initialize()
        assert acquire('test')
        try:
            with TestClient(app) as client:
                for _ in range(5):
                    assert record(sample(10, 1, 0), 'test')
                assert client.post('/presenter/api/inject', headers={'X-Presenter-Token': 'isolated-test'}).status_code == 200
                for _ in range(5):
                    assert record(sample(4100, 2, 1), 'test')
                alert_id = client.get('/presenter/api/monitor', headers={'X-Presenter-Token': 'isolated-test'}).json()['alerts'][0]['id']
                incident = {'incident_id': 'test', 'alert_id': alert_id, 'target': 'catalog', 'fault_generation': 1}
                proposal = (await diagnose(incident))['proposal']
                assert proposal['expected_config_version'] == 2 and proposal['restore_version'] == 1
                with closing(connect()) as db, db:
                    original = json.loads(db.execute('SELECT sample_ids FROM alerts WHERE id=?', (alert_id,)).fetchone()[0])
                    db.executemany('UPDATE probe_samples SET started_at=started_at-130,finished_at=finished_at-130 WHERE id=?', [(x,) for x in original])
                fresh = [sample(4100, 2, 1) for _ in range(5)]
                for observation in fresh:
                    assert record(observation, 'test')
                response = client.post('/presenter/api/alerts/'+alert_id+'/investigate', headers={'X-Presenter-Token': 'isolated-test'})
                assert response.status_code == 200
                refreshed = await diagnose(incident | {'incident_id': response.json()['id']})
                assert set(refreshed['proposal']['evidence_ids']) == {x['id'] for x in fresh}
                with closing(connect()) as db:
                    assert db.execute('SELECT delay_ms FROM config').fetchone()[0] == 4000
                assert (await diagnose(incident | {'fault_generation': 0}))['outcome'] == 'manual_review'
        finally:
            release('test')
    print('PASS: local diagnosis derives a proposal from measured records, denies stale generation, and does not change configuration')


if __name__ == '__main__':
    asyncio.run(main())
