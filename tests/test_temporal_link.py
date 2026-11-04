import time,uuid
from contextlib import closing
from fastapi.testclient import TestClient
from sre_agent.catalog.app import app,connect,initialize


def test_monitor_links_only_the_matching_recorded_temporal_execution(tmp_path,monkeypatch):
    monkeypatch.setenv('DEMOSHOP_DB',str(tmp_path/'db'))
    monkeypatch.setenv('DEMOSHOP_PRESENTER_TOKEN','test-token')
    initialize();incident=str(uuid.uuid4());run=str(uuid.uuid4());unlinked=str(uuid.uuid4());now=time.time()
    with closing(connect()) as db,db:
        for i,alert in [(incident,'a'),(unlinked,'b')]:
            db.execute('INSERT INTO incidents (id,alert_id,phase,created_at,updated_at) VALUES (?,?,?,?,?)',(i,alert,'TRIAGING',now,now))
        db.execute('INSERT INTO temporal_workflow_links VALUES (?,?,?)',(incident,'demo.account',run))
    with TestClient(app) as c:
        rows=c.get('/presenter/api/monitor',headers={'X-Presenter-Token':'test-token'}).json()['incidents']
    links={row['id']:row['temporal_url'] for row in rows}
    assert links[incident]==f'https://cloud.temporal.io/namespaces/demo.account/workflows/demoshop-local-{incident}/{run}'
    assert links[unlinked] is None
