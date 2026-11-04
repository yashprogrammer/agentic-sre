"""Free local Temporal compatibility spike; no cloud account or model calls.

Run only in the separate environment documented in LOCAL_REHEARSAL.md. This
spike does not connect the product workflow to Temporal or prove model replay.
"""
import asyncio
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, Replayer
from temporalio.strands_agents import StrandsPlugin

calls = []


@activity.defn
async def read_health() -> str:
    calls.append('health')
    return 'observed'


@workflow.defn
class ReplaySpike:
    def __init__(self):
        self.health = None
        self.decision = None

    @workflow.run
    async def run(self) -> str:
        self.health = await workflow.execute_activity(read_health, start_to_close_timeout=timedelta(seconds=10))
        await workflow.wait_condition(lambda: self.decision is not None)
        return f'{self.health}:{self.decision}'

    @workflow.update
    def decide(self, value: str) -> str:
        if self.decision is not None or value not in ('approve', 'reject'):
            return 'rejected'
        self.decision = value
        return 'accepted'

    @workflow.query
    def phase(self) -> str:
        return 'waiting' if self.health else 'starting'


async def main():
    async with await WorkflowEnvironment.start_local() as env:
        queue = 'local-replay-spike'
        async with Worker(env.client, task_queue=queue, workflows=[ReplaySpike], activities=[read_health], plugins=[StrandsPlugin()]):
            handle = await env.client.start_workflow(ReplaySpike.run, id='replay-spike', task_queue=queue)
            for _ in range(100):
                if await handle.query(ReplaySpike.phase) == 'waiting':
                    break
                await asyncio.sleep(0.05)
            else:
                raise RuntimeError('Workflow did not reach approval wait')
        async with Worker(env.client, task_queue=queue, workflows=[ReplaySpike], activities=[read_health], plugins=[StrandsPlugin()]):
            assert await asyncio.wait_for(handle.execute_update(ReplaySpike.decide, 'approve'), timeout=15) == 'accepted'
            assert await asyncio.wait_for(handle.result(), timeout=15) == 'observed:approve'
        assert calls == ['health'], f'Activity was repeated: {len(calls)} calls'
        history = await handle.fetch_history()
        await Replayer(workflows=[ReplaySpike], plugins=[StrandsPlugin()]).replay_workflow(history)
        print('PASS: local Temporal worker replacement, update, activity reuse, and history replay; no model call')


if __name__ == '__main__':
    asyncio.run(main())
