import json,time
from contextlib import closing
from fastapi.testclient import TestClient
from sre_agent.catalog.app import app,connect,initialize
from sre_agent.detection.probe import acquire,record,release
from test_detection import sample


def test_old_alert_gets_fresh_investigation_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv('DEMOSHOP_DB',str(tmp_path/'db'))
    monkeypatch.setenv('DEMOSHOP_PRESENTER_TOKEN','test-token')
    initialize()
    with closing(connect()) as db, db:
        db.execute('UPDATE config SET version=2,generation=1,delay_ms=4000')
    assert acquire('probe')
    try:
        for _ in range(5): assert record(sample(4100),'probe')
        with closing(connect()) as db, db:
            alert=db.execute('SELECT * FROM alerts').fetchone()
            old_ids=json.loads(alert['sample_ids'])
            db.executemany('UPDATE probe_samples SET started_at=started_at-130,finished_at=finished_at-130 WHERE id=?',[(x,) for x in old_ids])
        fresh=[sample(4100) for _ in range(5)]
        for s in fresh: assert record(s,'probe')
        with TestClient(app) as client:
            result=client.post('/presenter/api/alerts/'+alert['id']+'/investigate',headers={'X-Presenter-Token':'test-token'})
            assert result.status_code==200
        with closing(connect()) as db:
            assert json.loads(db.execute('SELECT sample_ids FROM alerts WHERE id=?',(alert['id'],)).fetchone()[0])==old_ids
            selected=json.loads(db.execute('SELECT sample_ids FROM investigation_evidence WHERE incident_id=?',(result.json()['id'],)).fetchone()[0])
            assert set(selected)=={x['id'] for x in fresh}
    finally:release('probe')
