"""Local Temporal/Strands replay with fixture model and a read-only Activity tool."""
import asyncio
from datetime import timedelta
from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, Replayer
from temporalio.strands_agents import StrandsPlugin, TemporalAgent
from temporalio.strands_agents.workflow import activity_as_tool
from strands.models import Model

model_calls=[]
tool_calls=[]


@activity.defn
async def read_evidence(incident_id: str) -> dict:
    """Read the measured evidence for one incident.

    Args:
        incident_id: Identifier of the incident to inspect.
    """
    tool_calls.append(incident_id)
    return {'latency_ms':4000,'config_changed':True}


class FakeToolModel(Model):
    def update_config(self, **kwargs):pass
    def get_config(self):return {}
    async def structured_output(self,*args,**kwargs):
        if False:yield {}
    async def stream(self,*args,**kwargs):
        model_calls.append(1)
        yield {'messageStart':{'role':'assistant'}}
        if len(model_calls)==1:
            yield {'contentBlockStart':{'start':{'toolUse':{'toolUseId':'fixture-tool','name':'read_evidence'}}}}
            yield {'contentBlockDelta':{'delta':{'toolUse':{'input':'{"incident_id":"fixture"}'}}}}
            yield {'contentBlockStop':{}}
            yield {'messageStop':{'stopReason':'tool_use'}}
        else:
            yield {'contentBlockDelta':{'delta':{'text':'The measured delay followed a configuration change.'}}}
            yield {'contentBlockStop':{}}
            yield {'messageStop':{'stopReason':'end_turn'}}
        yield {'metadata':{'usage':{'inputTokens':12,'outputTokens':8,'totalTokens':20},'metrics':{'latencyMs':1}}}


@workflow.defn
class ToolReplay:
    def __init__(self):self.answer=None;self.done=False
    @workflow.run
    async def run(self):
        tool=activity_as_tool(read_evidence,start_to_close_timeout=timedelta(seconds=10))
        agent=TemporalAgent(model='fixture',tools=[tool],start_to_close_timeout=timedelta(seconds=15),callback_handler=None)
        result=await agent.invoke_async('Read the evidence for fixture, then summarize it.')
        self.answer=str(result)
        await workflow.wait_condition(lambda:self.done)
        return self.answer
    @workflow.update
    def finish(self):self.done=True;return True
    @workflow.query
    def ready(self):return self.answer is not None


async def main():
    plugin=StrandsPlugin(models={'fixture':lambda:FakeToolModel()})
    async with await WorkflowEnvironment.start_local() as env:
        args={'task_queue':'strands-tool-fixture','workflows':[ToolReplay],'activities':[read_evidence],'plugins':[plugin]}
        async with Worker(env.client,**args):
            handle=await env.client.start_workflow(ToolReplay.run,id='strands-tool-fixture',task_queue='strands-tool-fixture')
            for _ in range(200):
                if await handle.query(ToolReplay.ready):break
                await asyncio.sleep(.1)
            else:raise RuntimeError('Fixture agent did not finish')
        async with Worker(env.client,**args):
            assert await asyncio.wait_for(handle.execute_update(ToolReplay.finish),15)
            assert 'measured delay' in (await asyncio.wait_for(handle.result(),15)).lower()
        assert len(model_calls)==2 and tool_calls==['fixture'],(len(model_calls),len(tool_calls))
        await Replayer(workflows=[ToolReplay],plugins=[plugin]).replay_workflow(await handle.fetch_history())
    print('PASS: fixture Strands model and read-only Activity tool survived worker replacement and history replay')


if __name__=='__main__':asyncio.run(main())
