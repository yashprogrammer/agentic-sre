"""Check that the public demo origin is explicitly scoped for control commands."""
from fastapi.testclient import TestClient
from sre_agent.catalog.app import app


def test_public_control_origin_is_scoped(monkeypatch, tmp_path):
    monkeypatch.setenv('DEMOSHOP_DB', str(tmp_path / 'demo.sqlite'))
    monkeypatch.setenv('DEMOSHOP_PRESENTER_TOKEN', 'test-token')
    monkeypatch.setenv('DEMOSHOP_PUBLIC_ORIGIN', 'https://192-0-2-42.sslip.io')
    with TestClient(app) as client:
        headers = {'X-Presenter-Token':'test-token', 'Origin':'https://192-0-2-42.sslip.io'}
        assert client.post('/presenter/api/emergency-reset', headers=headers).status_code == 200
        headers['Origin'] = 'https://192-0-2-43.sslip.io'
        assert client.post('/presenter/api/emergency-reset', headers=headers).status_code == 403
        headers['Origin'] = 'http://192-0-2-42.sslip.io'
        assert client.post('/presenter/api/emergency-reset', headers=headers).status_code == 403
