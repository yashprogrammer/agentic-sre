"""Development-server contract test with fake Activities, not a cloud E2E test."""
import asyncio
import os
import tempfile
import time
import uuid

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, Replayer
from temporalio.strands_agents import StrandsPlugin

from sre_agent.workflows.temporal_incident import IncidentWorkflow
from sre_agent.activities.local_diagnosis import diagnose as measured_diagnose
from sre_agent.catalog.app import app, initialize
from sre_agent.detection.probe import acquire, record, release
from fastapi.testclient import TestClient
from test_temporal_diagnosis import sample

calls = {'diagnose': 0, 'execute': 0, 'verify': 0}


@activity.defn(name='diagnose')
async def diagnose(incident: dict) -> dict:
    calls['diagnose'] += 1
    if incident.get('slow_diagnosis'):
        await asyncio.sleep(1.5)
    return {'proposal': {'incident_id': incident['incident_id'], 'target': 'catalog', 'action': 'restore_service_config', 'expected_generation': incident['fault_generation'], 'expected_config_version': 2, 'restore_config_digest': 'a' * 64, 'expires_at': time.time() + incident.get('expiry_seconds', 600)}}


@activity.defn(name='execute_approved_restore')
async def execute_approved_restore(_request: dict) -> dict:
    calls['execute'] += 1
    return {'status': 'SUCCEEDED', 'applied_version': 3, 'applied_at': time.time()}


@activity.defn(name='verify_catalog')
async def verify_catalog(_request: dict) -> dict:
    calls['verify'] += 1
    return {'id': str(uuid.uuid4()), 'valid': True, 'elapsed_ms': 25, 'config_version': 3, 'fault_generation': 1, 'started_at': time.time()}


async def wait_phase(handle, wanted):
    for _ in range(100):
        result = await handle.query(IncidentWorkflow.status)
        if result['phase'] == wanted:
            return result
        await asyncio.sleep(.05)
    raise RuntimeError(f'Workflow did not reach {wanted}')


async def main():
    async with await WorkflowEnvironment.start_local() as env:
        args = {'task_queue': 'incident-contract', 'workflows': [IncidentWorkflow], 'activities': [diagnose, execute_approved_restore, verify_catalog], 'plugins': [StrandsPlugin()]}
        incident = {'incident_id': 'local-test', 'target': 'catalog', 'fault_generation': 1}
        async with Worker(env.client, **args):
            handle = await env.client.start_workflow(IncidentWorkflow.run, incident, id='contract-approval', task_queue='incident-contract')
            state = await wait_phase(handle, 'WAITING_APPROVAL')
            wrong = await handle.execute_update(IncidentWorkflow.decide, {'decision': 'APPROVE', 'request_id': 'wrong', 'proposal_hash': 'incorrect'})
            assert not wrong['accepted'] and calls['execute'] == 0
        async with Worker(env.client, **args):
            decision = {'decision': 'APPROVE', 'request_id': 'approved', 'proposal_hash': state['proposal_hash']}
            assert (await handle.execute_update(IncidentWorkflow.decide, decision))['accepted']
            result = await asyncio.wait_for(handle.result(), 40)
            assert result['phase'] == 'RESOLVED' and len(result['verification']) == 5
        assert calls == {'diagnose': 1, 'execute': 1, 'verify': 5}, calls
        await Replayer(workflows=[IncidentWorkflow], plugins=[StrandsPlugin()]).replay_workflow(await handle.fetch_history())
        async with Worker(env.client, **args):
            rejected = await env.client.start_workflow(IncidentWorkflow.run, incident, id='contract-rejection', task_queue='incident-contract')
            state = await wait_phase(rejected, 'WAITING_APPROVAL')
            assert (await rejected.execute_update(IncidentWorkflow.decide, {'decision': 'REJECT', 'request_id': 'rejected', 'proposal_hash': state['proposal_hash']}))['accepted']
            assert (await rejected.result())['phase'] == 'REJECTED'
        assert calls['execute'] == 1
        async with Worker(env.client, **args):
            expiring = await env.client.start_workflow(IncidentWorkflow.run, incident | {'expiry_seconds': 2}, id='contract-expiry', task_queue='incident-contract')
            await wait_phase(expiring, 'WAITING_APPROVAL')
            assert (await asyncio.wait_for(expiring.result(), 8))['phase'] == 'EXPIRED'
            cancelled = await env.client.start_workflow(IncidentWorkflow.run, incident, id='contract-cancellation', task_queue='incident-contract')
            await wait_phase(cancelled, 'WAITING_APPROVAL')
            assert (await cancelled.execute_update(IncidentWorkflow.cancel))['accepted']
            assert (await cancelled.result())['phase'] == 'CANCELLED'
            during_read = await env.client.start_workflow(IncidentWorkflow.run, incident | {'slow_diagnosis': True}, id='contract-cancel-during-read', task_queue='incident-contract')
            await wait_phase(during_read, 'TRIAGING')
            assert (await during_read.execute_update(IncidentWorkflow.cancel))['accepted']
            assert (await asyncio.wait_for(during_read.result(), 8))['phase'] == 'CANCELLED'
        assert calls['execute'] == 1
        # Exercise the real read-only local Activity inside Temporal. The control
        # plane and effect Activities are still fixtures in this test.
        with tempfile.TemporaryDirectory() as directory:
            os.environ['DEMOSHOP_DB'] = directory + '/evidence.sqlite'
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
                    args['activities'] = [measured_diagnose, execute_approved_restore, verify_catalog]
                    async with Worker(env.client, **args):
                        measured = await env.client.start_workflow(IncidentWorkflow.run, incident | {'alert_id': alert_id}, id='contract-measured', task_queue='incident-contract')
                        actual = await wait_phase(measured, 'WAITING_APPROVAL')
                        assert actual['proposal']['expected_config_version'] == 2
                        assert len(actual['proposal']['baseline_evidence_ids']) == 5
                        assert (await measured.execute_update(IncidentWorkflow.decide, {'decision': 'REJECT', 'request_id': 'safe-reject', 'proposal_hash': actual['proposal_hash']}))['accepted']
                        assert (await measured.result())['phase'] == 'REJECTED'
            finally:
                release('test')
    print('PASS: Temporal worker restart, approval, checks, rejection, expiry, cancellation, replay, and measured local read-only diagnosis; restore and verification Activities are fake')


if __name__ == '__main__':
    asyncio.run(main())
