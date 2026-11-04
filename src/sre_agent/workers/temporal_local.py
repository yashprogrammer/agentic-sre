"""Local-only Temporal Cloud worker and SQLite/UI bridge.

Credentials supplied in memory by caller; never logs or persists them. Run only
with loopback app and never simultaneously with the SQLite-only worker.
"""
import asyncio
import json
import os
import time
from contextlib import closing
from datetime import timedelta

from temporalio.client import Client, WorkflowFailureError
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Worker
from temporalio.strands_agents import StrandsPlugin

from sre_agent.catalog.app import connect, initialize
from sre_agent.workflows.temporal_incident import IncidentWorkflow, ModelReviewWorkflow, GroqModelReviewWorkflow
from sre_agent.activities.local_diagnosis import diagnose
from sre_agent.activities.local_execution import execute_approved_restore, verify_catalog
from sre_agent.activities.agentcore_analysis import analyze_latency_with_agentcore

QUEUE_PREFIX = 'demoshop-local-v1-'
TERMINAL = {'RESOLVED', 'UNRESOLVED', 'REJECTED', 'EXPIRED', 'CANCELLED', 'NEEDS_MANUAL_REVIEW', 'EXECUTION_UNKNOWN', 'NO_ACTION_REQUIRED'}


def queue_name():
    with closing(connect()) as db:
        row = db.execute('SELECT instance_id,orchestrator FROM demo_identity WHERE id=1').fetchone()
    if not row or row['orchestrator'] != 'temporal':
        raise RuntimeError('Temporal mode is not enabled for this demo environment')
    return QUEUE_PREFIX + row['instance_id']


async def save_workflow_link(client, incident_id, handle=None):
    with closing(connect()) as db:
        if db.execute('SELECT 1 FROM temporal_workflow_links WHERE incident_id=?', (incident_id,)).fetchone():
            return
    handle = handle or client.get_workflow_handle('demoshop-local-' + incident_id)
    description = await handle.describe()
    with closing(connect()) as db, db:
        db.execute('INSERT OR IGNORE INTO temporal_workflow_links VALUES (?,?,?)', (incident_id, client.namespace, description.run_id))


async def backfill_workflow_links(client):
    with closing(connect()) as db:
        ids = [r['id'] for r in db.execute('SELECT i.id FROM incidents i LEFT JOIN temporal_workflow_links l ON l.incident_id=i.id WHERE l.incident_id IS NULL ORDER BY i.created_at DESC LIMIT 20')]
    for incident_id in ids:
        try:
            await save_workflow_link(client, incident_id)
        except Exception:
            # Some records may not have reached Temporal; reconciliation retries active ones.
            pass


async def reconcile(client):
    queue = queue_name()
    with closing(connect()) as db:
        rows = [dict(r) for r in db.execute("SELECT i.*, a.fault_generation FROM incidents i JOIN alerts a ON a.id=i.alert_id WHERE i.phase NOT IN ('RESOLVED','UNRESOLVED','REJECTED','EXPIRED','CANCELLED','NEEDS_MANUAL_REVIEW','EXECUTION_UNKNOWN','NO_ACTION_REQUIRED')")]
    for row in rows:
        workflow_id = 'demoshop-local-' + row['id']
        incident = {'incident_id':row['id'], 'alert_id':row['alert_id'], 'target':'catalog', 'fault_generation':row['fault_generation'], 'diagnosis_mode':os.environ.get('DEMOSHOP_DIAGNOSIS', 'deterministic'), 'agentcore_analysis':os.environ.get('DEMOSHOP_AGENTCORE') == '1'}
        try:
            handle = await client.start_workflow(IncidentWorkflow.run, incident, id=workflow_id, task_queue=queue, id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE, execution_timeout=timedelta(hours=1))
        except WorkflowAlreadyStartedError:
            handle = client.get_workflow_handle(workflow_id)
        try:
            await save_workflow_link(client, row['id'], handle)
        except Exception:
            # Link generation must not block an approval or remediation.
            pass
        # Other failures leave persisted work pending for safe reconciliation.
        if row['phase'] in ('APPROVED', 'REJECTION_PENDING') and row['decision_request_id']:
            command = {'decision':row['decision'], 'request_id':row['decision_request_id'], 'proposal_hash':row['proposal_hash']}
            receipt = await handle.execute_update(IncidentWorkflow.decide, command, id=row['decision_request_id'])
            if not receipt.get('accepted'):
                with closing(connect()) as db, db:
                    db.execute("UPDATE incidents SET phase='NEEDS_MANUAL_REVIEW',reason='Temporal did not accept the decision',updated_at=? WHERE id=? AND phase IN ('APPROVED','REJECTION_PENDING')", (time.time(), row['id']))
                continue
        snapshot = await handle.query(IncidentWorkflow.status)
        proposal = snapshot.get('proposal')
        action = snapshot.get('action') or {}
        phase = snapshot['phase']
        with closing(connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM incidents WHERE id=?', (row['id'],)).fetchone()
            if not current or current['phase'] in TERMINAL:
                db.rollback()
                continue
            # Preserve a decision recorded by the API until Temporal accepts it.
            if current['phase'] in ('APPROVED', 'REJECTION_PENDING') and phase in ('TRIAGING', 'WAITING_APPROVAL'):
                db.rollback()
                continue
            if phase == 'RESOLVED':
                config = db.execute('SELECT version,generation FROM config WHERE id=1').fetchone()
                if not proposal or config['version'] != action.get('applied_version') or config['generation'] != proposal['expected_generation']:
                    phase = 'UNRESOLVED'
            db.execute('UPDATE incidents SET phase=?, proposal=COALESCE(?,proposal), proposal_hash=COALESCE(?,proposal_hash), reason=?, action_id=COALESCE(?,action_id), applied_at=COALESCE(?,applied_at), applied_version=COALESCE(?,applied_version), verification_ids=?, updated_at=? WHERE id=?', (phase, json.dumps(proposal,sort_keys=True,separators=(',',':')) if proposal else None, snapshot.get('proposal_hash'), snapshot.get('reason'), action.get('action_id'), action.get('applied_at'), action.get('applied_version'), json.dumps(snapshot.get('verification') or []), time.time(), row['id']))
            if snapshot.get('agentcore_analysis') is not None:
                db.execute('INSERT OR REPLACE INTO incident_agentcore VALUES (?,?)', (row['id'], json.dumps(snapshot['agentcore_analysis'], sort_keys=True)))
            if phase == 'RESOLVED':
                db.execute("UPDATE alerts SET status='RECOVERED' WHERE id=?", (row['alert_id'],))
            db.commit()


async def run(namespace: str, api_key: str, groq_key: str = ''):
    initialize()
    queue = queue_name()
    models = {}
    if os.environ.get('DEMOSHOP_DIAGNOSIS') == 'strands-local':
        from strands.models.ollama import OllamaModel
        schema = {'type':'object','properties':{'cause':{'type':'string','enum':['injected_dependency_delay','unknown']},'action':{'type':'string','enum':['restore_verified_config','manual_review']}},'required':['cause','action']}
        models['local_qwen'] = lambda: OllamaModel(host='http://127.0.0.1:11434', model_id='qwen3:0.6b', temperature=0, max_tokens=100, keep_alive='1m', additional_args={'think':False,'format':schema})
    if os.environ.get('DEMOSHOP_DIAGNOSIS') == 'strands-groq':
        if not groq_key:
            raise RuntimeError('Groq key required for Groq model mode')
        from strands.models.openai import OpenAIModel
        models['groq_gpt_oss'] = lambda: OpenAIModel(client_args={'api_key': groq_key, 'base_url': 'https://api.groq.com/openai/v1', 'max_retries': 0}, model_id='openai/gpt-oss-20b', stream=False, params={'temperature': 0, 'max_completion_tokens': 512, 'response_format': {'type': 'json_object'}, 'reasoning_effort': 'low'})
    client = await Client.connect(namespace + '.tmprl.cloud:7233', namespace=namespace, api_key=api_key, tls=True, plugins=[StrandsPlugin(models=models)])
    async with Worker(client, task_queue=queue, workflows=[IncidentWorkflow, ModelReviewWorkflow, GroqModelReviewWorkflow], activities=[diagnose, execute_approved_restore, verify_catalog, analyze_latency_with_agentcore]):
        print('Temporal Cloud worker connected; local-only execution; diagnosis mode:', os.environ.get('DEMOSHOP_DIAGNOSIS', 'deterministic'), flush=True)
        await backfill_workflow_links(client)
        while True:
            try:
                await reconcile(client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Never log request, workflow payload, endpoint, or credentials.
                print('Temporal reconciliation error:', type(exc).__name__, flush=True)
            await asyncio.sleep(2)
