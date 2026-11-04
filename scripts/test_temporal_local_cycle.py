"""Local Temporal service and real SQLite Activities, with controlled sample records."""
import asyncio
import json
import os
import tempfile
import time
import uuid
from contextlib import closing
from fastapi.testclient import TestClient
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from temporalio.strands_agents import StrandsPlugin
from sre_agent.catalog.app import app, connect, initialize
from sre_agent.detection.probe import acquire, record, release
from sre_agent.workers.temporal_local import reconcile, queue_name
from sre_agent.workflows.temporal_incident import IncidentWorkflow
from sre_agent.activities.local_diagnosis import diagnose
from sre_agent.activities.local_execution import execute_approved_restore, verify_catalog
from sre_agent.activities.agentcore_analysis import analyze_latency_with_agentcore


def sample(ms, version, gen):
    now=time.time()
    return {'id':str(uuid.uuid4()),'started_at':now,'finished_at':now,'elapsed_ms':ms,'status':200,'valid':1,'error':None,'request_id':str(uuid.uuid4()),'config_version':version,'fault_generation':gen}


async def reach(client, api, headers, phase, timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        await reconcile(client)
        incidents=api.get('/presenter/api/monitor',headers=headers).json()['incidents']
        if incidents and incidents[0]['phase']==phase:
            return incidents[0]
        await asyncio.sleep(.3)
    raise AssertionError('Timed out waiting for '+phase)


async def main():
    with tempfile.TemporaryDirectory() as folder:
        os.environ['DEMOSHOP_DB']=folder+'/data.sqlite'
        os.environ['DEMOSHOP_PRESENTER_TOKEN']='isolated-test'
        os.environ['DEMOSHOP_ORCHESTRATOR']='temporal'
        if os.environ.get('TEST_AGENTCORE') == '1':
            os.environ['DEMOSHOP_AGENTCORE']='1'
        initialize()
        assert acquire('probe')
        try:
            with TestClient(app) as api:
                headers={'X-Presenter-Token':'isolated-test'}
                for _ in range(5): assert record(sample(20,1,0),'probe')
                assert api.post('/presenter/api/inject',headers=headers).status_code==200
                for _ in range(5): assert record(sample(4100,2,1),'probe')
                alert=api.get('/presenter/api/monitor',headers=headers).json()['alerts'][0]
                assert api.post('/presenter/api/alerts/'+alert['id']+'/investigate',headers=headers).status_code==200
                async with await WorkflowEnvironment.start_local() as env:
                    client=env.client
                    async with Worker(client,task_queue=queue_name(),workflows=[IncidentWorkflow],activities=[diagnose,execute_approved_restore,verify_catalog,analyze_latency_with_agentcore],plugins=[StrandsPlugin()]):
                        incident=await reach(client,api,headers,'WAITING_APPROVAL')
                        if os.environ.get('TEST_AGENTCORE') == '1':
                            assert incident['agentcore_analysis']['provider']=='AgentCore Code Interpreter'
                            assert incident['agentcore_analysis']['median_ms']==4100
                        proposal=incident['proposal']
                        request={'proposal':proposal,'proposal_hash':incident['proposal_hash'],'decision':{'request_id':'x','decision':'APPROVE','accepted':True}}
                        assert (await execute_approved_restore(request))['status']=='DENIED'
                        command={'decision':'APPROVE','request_id':'x','proposal_hash':incident['proposal_hash']}
                        assert api.post('/presenter/api/incidents/'+incident['id']+'/decision',headers=headers,json=command).status_code==200
                        incident=await reach(client,api,headers,'VERIFYING')
                        assert (await execute_approved_restore(request))['status']=='SUCCEEDED'
                        with closing(connect()) as db:
                            assert db.execute('SELECT count(*) FROM action_receipts').fetchone()[0]==1
                            assert db.execute('SELECT delay_ms FROM config').fetchone()[0]==0
                        for _ in range(5):
                            assert record(sample(20,incident['applied_version'],1),'probe')
                        result=await reach(client,api,headers,'RESOLVED',timeout=45)
                        assert len(result['verification_ids'])==5
                        assert api.get('/presenter/api/monitor',headers=headers).json()['alerts'][0]['status']=='RECOVERED'
                        # A second incident rejected by the presenter must not execute.
                        for _ in range(5): assert record(sample(20,3,1),'probe')
                        assert api.post('/presenter/api/inject',headers=headers).status_code==200
                        for _ in range(5): assert record(sample(4100,4,2),'probe')
                        alerts=api.get('/presenter/api/monitor',headers=headers).json()['alerts']
                        alert2=next(a for a in alerts if a['fault_generation']==2)
                        assert api.post('/presenter/api/alerts/'+alert2['id']+'/investigate',headers=headers).status_code==200
                        second=await reach(client,api,headers,'WAITING_APPROVAL')
                        command={'decision':'REJECT','request_id':'reject','proposal_hash':second['proposal_hash']}
                        assert api.post('/presenter/api/incidents/'+second['id']+'/decision',headers=headers,json=command).status_code==200
                        await reach(client,api,headers,'REJECTED')
                        with closing(connect()) as db:
                            assert db.execute('SELECT count(*) FROM action_receipts').fetchone()[0]==1
                            assert db.execute('SELECT delay_ms FROM config').fetchone()[0]==4000
        finally:
            release('probe')
    print('PASS: actual Temporal workflow, SQLite approval guard, one restore, independent evidence gate and rejection; controlled sample records')


if __name__=='__main__': asyncio.run(main())
