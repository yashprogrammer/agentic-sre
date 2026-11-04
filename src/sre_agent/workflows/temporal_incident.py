"""Temporal incident state machine for the loopback DemoShop demonstration.

Production still needs independent authorization and trusted cloud execution.
"""
import asyncio
import hashlib
import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ChildWorkflowError
from temporalio.strands_agents import TemporalAgent


@workflow.defn
class ModelReviewWorkflow:
    @workflow.run
    async def run(self, facts: dict) -> str:
        agent = TemporalAgent(model='local_qwen', tools=[], start_to_close_timeout=timedelta(seconds=30), schedule_to_close_timeout=timedelta(seconds=35), retry_policy=RetryPolicy(maximum_attempts=1), callback_handler=None, system_prompt='Classify only the supplied facts. If injected_delay_ms is greater than zero AND verified_good_available is true AND verified_good_delay_ms is zero, return cause injected_dependency_delay and action restore_verified_config. Otherwise return cause unknown and action manual_review. Return JSON only.')
        return str(await agent.invoke_async(json.dumps(facts, sort_keys=True)))


@workflow.defn
class GroqModelReviewWorkflow:
    @workflow.run
    async def run(self, facts: dict) -> str:
        agent = TemporalAgent(model='groq_gpt_oss', tools=[], start_to_close_timeout=timedelta(seconds=30), schedule_to_close_timeout=timedelta(seconds=35), retry_policy=RetryPolicy(maximum_attempts=1), callback_handler=None, system_prompt='Classify only the supplied facts. If injected_delay_ms is greater than zero AND verified_good_available is true AND verified_good_delay_ms is zero, return cause injected_dependency_delay and action restore_verified_config. Otherwise return cause unknown and action manual_review. Return JSON only.')
        return str(await agent.invoke_async(json.dumps(facts, sort_keys=True)))


@workflow.defn
class IncidentWorkflow:
    def __init__(self):
        self.phase = 'RECEIVED'
        self.proposal = None
        self.proposal_hash = None
        self.decision = None
        self.receipt = None
        self.action = None
        self.reason = None
        self.agentcore_analysis = None
        self.verification = []
        self.escalation_due = False

    @workflow.run
    async def run(self, incident: dict) -> dict:
        self.phase = 'TRIAGING'
        try:
            result = await workflow.execute_activity('diagnose', incident, start_to_close_timeout=timedelta(seconds=60), retry_policy=RetryPolicy(maximum_attempts=2))
        except ActivityError:
            if self.phase == 'CANCELLED':
                return self._snapshot()
            return self._finish('NEEDS_MANUAL_REVIEW', 'Diagnosis failed')
        if self.phase == 'CANCELLED':
            return self._snapshot()
        if not isinstance(result, dict):
            return self._finish('NEEDS_MANUAL_REVIEW', 'Invalid diagnosis result')
        if result.get('outcome') == 'healthy':
            return self._finish('NO_ACTION_REQUIRED')
        proposal = result.get('proposal')
        if not self._valid_proposal(proposal, incident):
            return self._finish('NEEDS_MANUAL_REVIEW', 'Diagnosis did not produce a valid supported proposal')
        if incident.get('agentcore_analysis') is True:
            try:
                self.agentcore_analysis = await workflow.execute_activity('analyze_latency_with_agentcore', result.get('analysis_samples_ms', []), start_to_close_timeout=timedelta(seconds=50), retry_policy=RetryPolicy(maximum_attempts=1))
            except ActivityError:
                self.agentcore_analysis = {'provider': 'AgentCore Code Interpreter', 'status': 'unavailable'}
        if incident.get('diagnosis_mode') in ('strands-local', 'strands-groq'):
            try:
                review_workflow = GroqModelReviewWorkflow.run if incident.get('diagnosis_mode') == 'strands-groq' else ModelReviewWorkflow.run
                review = await workflow.execute_child_workflow(review_workflow, result.get('facts', {}), execution_timeout=timedelta(seconds=45))
                review = json.loads(review)
            except (ChildWorkflowError, ValueError, TypeError):
                return self._finish('NEEDS_MANUAL_REVIEW', 'Model review failed')
            if review != {'cause': 'injected_dependency_delay', 'action': 'restore_verified_config'}:
                return self._finish('NEEDS_MANUAL_REVIEW', 'Model did not recommend the supported restore')
            self.reason = ('Groq GPT-OSS 20B' if incident.get('diagnosis_mode') == 'strands-groq' else 'Local Qwen') + ' via Strands reviewed measured evidence and recommended restoring the verified configuration.'
        self.proposal = proposal
        self.proposal_hash = hashlib.sha256(json.dumps(proposal, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.phase = 'WAITING_APPROVAL'
        due = workflow.now().timestamp() + 90
        while self.phase == 'WAITING_APPROVAL':
            now = workflow.now().timestamp()
            if now >= proposal['expires_at']:
                return self._finish('EXPIRED', 'Approval expired')
            if not self.escalation_due and now >= due:
                self.escalation_due = True
                # A notification adapter has not yet been implemented.
            deadline = proposal['expires_at'] if self.escalation_due else min(due, proposal['expires_at'])
            try:
                await workflow.wait_condition(lambda: self.phase != 'WAITING_APPROVAL', timeout=timedelta(seconds=max(0.001, deadline - now)))
            except asyncio.TimeoutError:
                pass
        if self.phase != 'APPROVED':
            return self._snapshot()
        self.phase = 'REMEDIATION_STARTING'
        try:
            self.action = await workflow.execute_activity('execute_approved_restore', {'incident': incident, 'proposal': proposal, 'proposal_hash': self.proposal_hash, 'decision': self.receipt}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
        except ActivityError:
            return self._finish('EXECUTION_UNKNOWN', 'Restore outcome could not be established')
        if not isinstance(self.action, dict) or self.action.get('status') != 'SUCCEEDED' or type(self.action.get('applied_version')) is not int or not isinstance(self.action.get('applied_at'), (int, float)):
            return self._finish('NEEDS_MANUAL_REVIEW', 'Restore was not confirmed successful')
        self.phase = 'VERIFYING'
        deadline = workflow.now().timestamp() + 120
        consecutive = []
        cursor = self.action['applied_at']
        while workflow.now().timestamp() < deadline:
            try:
                sample = await workflow.execute_activity('verify_catalog', {'incident': incident, 'proposal': proposal, 'action': self.action, 'observed_after': cursor}, start_to_close_timeout=timedelta(seconds=10), retry_policy=RetryPolicy(maximum_attempts=1))
            except ActivityError:
                sample = {'valid': False}
            if isinstance(sample, dict) and sample.get('target_changed'):
                return self._finish('UNRESOLVED', 'Configuration changed during verification')
            if isinstance(sample, dict) and sample.get('pending'):
                await workflow.sleep(5)
                continue
            if isinstance(sample, dict) and isinstance(sample.get('started_at'), (int, float)) and cursor < sample['started_at'] <= workflow.now().timestamp():
                cursor = sample['started_at']
            if (isinstance(sample, dict) and sample.get('valid') is True and isinstance(sample.get('elapsed_ms'), (int, float)) and 0 <= sample['elapsed_ms'] < 1000 and sample.get('config_version') == self.action.get('applied_version') and sample.get('fault_generation') == proposal['expected_generation'] and isinstance(sample.get('started_at'), (int, float)) and self.action['applied_at'] < sample['started_at'] <= workflow.now().timestamp() and isinstance(sample.get('id'), str) and sample['id'] and sample['id'] not in consecutive):
                consecutive.append(sample['id'])
                if len(consecutive) == 5:
                    self.verification = consecutive
                    return self._finish('RESOLVED')
            else:
                consecutive = []
            await workflow.sleep(5)
        return self._finish('UNRESOLVED', 'Five fresh correct fast samples were not verified')

    def _valid_proposal(self, proposal, incident):
        return (isinstance(proposal, dict) and proposal.get('incident_id') == incident.get('incident_id') and proposal.get('target') == incident.get('target') == 'catalog' and proposal.get('action') == 'restore_service_config' and proposal.get('expected_generation') == incident.get('fault_generation') and isinstance(proposal.get('expected_config_version'), int) and isinstance(proposal.get('restore_config_digest'), str) and len(proposal['restore_config_digest']) == 64 and isinstance(proposal.get('expires_at'), (int, float)) and workflow.now().timestamp() < proposal['expires_at'] <= workflow.now().timestamp() + 600)

    @workflow.update
    def decide(self, command: dict) -> dict:
        if not isinstance(command, dict) or command.get('decision') not in ('APPROVE', 'REJECT') or not isinstance(command.get('request_id'), str) or not command['request_id']:
            return {'accepted': False, 'reason': 'invalid command'}
        if self.receipt and command['request_id'] == self.receipt['request_id']:
            if all(command.get(key) == self.receipt.get(key) for key in ('decision', 'proposal_hash')):
                return self.receipt
            return {'accepted': False, 'reason': 'request id conflict'}
        if self.phase != 'WAITING_APPROVAL' or command.get('proposal_hash') != self.proposal_hash or workflow.now().timestamp() >= self.proposal['expires_at']:
            return {'accepted': False, 'reason': 'stale decision'}
        self.receipt = {'accepted': True, 'request_id': command['request_id'], 'decision': command['decision'], 'proposal_hash': self.proposal_hash, 'recorded_at': workflow.now().timestamp()}
        self.decision = command['decision']
        self.phase = 'APPROVED' if self.decision == 'APPROVE' else 'REJECTED'
        return self.receipt

    @workflow.update
    def cancel(self) -> dict:
        if self.phase not in ('TRIAGING', 'WAITING_APPROVAL'):
            return {'accepted': False, 'reason': 'cannot cancel after decision'}
        self.phase = 'CANCELLED'
        return {'accepted': True}

    @workflow.query
    def status(self) -> dict:
        return self._snapshot()

    def _finish(self, phase, reason=None):
        self.phase = phase
        self.reason = reason
        return self._snapshot()

    def _snapshot(self):
        return {'phase': self.phase, 'proposal': self.proposal, 'proposal_hash': self.proposal_hash, 'decision': self.receipt, 'action': self.action, 'reason': self.reason, 'verification': self.verification, 'escalation_due': self.escalation_due, 'agentcore_analysis': self.agentcore_analysis}
