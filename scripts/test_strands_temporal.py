"""Local Temporal/Strands replay test with a fake model; no cloud model calls."""
import asyncio
from datetime import timedelta
from temporalio import workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, Replayer
from temporalio.strands_agents import StrandsPlugin, TemporalAgent
from strands.models import Model

model_calls=[]


class FakeModel(Model):
    def update_config(self, **kwargs): pass
    def get_config(self): return {}
    async def structured_output(self, *args, **kwargs):
        if False: yield {}
    async def stream(self, *args, **kwargs):
        model_calls.append(1)
        yield {'messageStart':{'role':'assistant'}}
        yield {'contentBlockStart':{'start':{}}}
        yield {'contentBlockDelta':{'delta':{'text':'Measured latency coincides with the configuration change.'}}}
        yield {'contentBlockStop':{}}
        yield {'messageStop':{'stopReason':'end_turn'}}
        yield {'metadata':{'usage':{'inputTokens':12,'outputTokens':8,'totalTokens':20},'metrics':{'latencyMs':1}}}


@workflow.defn
class ModelReplay:
    def __init__(self):
        self.assessment=None
        self.done=False

    @workflow.run
    async def run(self):
        agent=TemporalAgent(model='fixture',start_to_close_timeout=timedelta(seconds=15),callback_handler=None)
        result=await agent.invoke_async('Review the measured test incident.')
        self.assessment=str(result)
        await workflow.wait_condition(lambda:self.done)
        return self.assessment

    @workflow.update
    def finish(self):
        self.done=True
        return True

    @workflow.query
    def ready(self):return self.assessment is not None


async def main():
    plugin=StrandsPlugin(models={'fixture':lambda:FakeModel()})
    async with await WorkflowEnvironment.start_local() as env:
        args={'task_queue':'strands-fixture-test','workflows':[ModelReplay],'plugins':[plugin]}
        async with Worker(env.client,**args):
            handle=await env.client.start_workflow(ModelReplay.run,id='strands-fixture',task_queue='strands-fixture-test')
            for _ in range(150):
                if await handle.query(ModelReplay.ready):break
                await asyncio.sleep(.1)
            else:raise RuntimeError('Model fixture did not complete')
        async with Worker(env.client,**args):
            assert await asyncio.wait_for(handle.execute_update(ModelReplay.finish),15)
            assert 'Measured latency' in await asyncio.wait_for(handle.result(),15)
        assert len(model_calls)==1, 'Model operation was repeated'
        await Replayer(workflows=[ModelReplay],plugins=[plugin]).replay_workflow(await handle.fetch_history())
    print('PASS: Strands model Activity recorded and reused across worker replacement and history replay; model was a fixture')


if __name__=='__main__':asyncio.run(main())
