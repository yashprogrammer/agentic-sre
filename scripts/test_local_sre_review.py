"""Check real local Qwen evidence classification inside a Temporal Strands workflow."""
import asyncio
import json
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from temporalio.strands_agents import StrandsPlugin, TemporalAgent
from strands.models.ollama import OllamaModel

SCHEMA={'type':'object','properties':{'cause':{'type':'string','enum':['injected_dependency_delay','unknown']},'action':{'type':'string','enum':['restore_verified_config','manual_review']}},'required':['cause','action']}

@workflow.defn
class ReviewTest:
    @workflow.run
    async def run(self, facts: dict) -> str:
        agent=TemporalAgent(model='local_qwen',tools=[],start_to_close_timeout=timedelta(seconds=30),schedule_to_close_timeout=timedelta(seconds=35),retry_policy=RetryPolicy(maximum_attempts=1),callback_handler=None,system_prompt='Classify only the supplied facts. If injected_delay_ms is greater than zero AND verified_good_available is true AND verified_good_delay_ms is zero, return cause injected_dependency_delay and action restore_verified_config. Otherwise return cause unknown and action manual_review. Return JSON only.')
        return str(await agent.invoke_async(json.dumps(facts,sort_keys=True)))

async def main():
    plugin=StrandsPlugin(models={'local_qwen':lambda:OllamaModel(host='http://127.0.0.1:11434',model_id='qwen3:0.6b',temperature=0,max_tokens=100,keep_alive='1m',additional_args={'think':False,'format':SCHEMA})})
    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(env.client,task_queue='local-model-review',workflows=[ReviewTest],plugins=[plugin]):
            cases=[({'injected_delay_ms':4000,'verified_good_available':True,'verified_good_delay_ms':0,'slow_requests':3},'restore_verified_config'),({'injected_delay_ms':4000,'verified_good_available':False,'verified_good_delay_ms':None,'slow_requests':3},'manual_review'),({'injected_delay_ms':0,'verified_good_available':True,'verified_good_delay_ms':0,'slow_requests':0},'manual_review')]
            for i,(facts,expected) in enumerate(cases):
                result=await asyncio.wait_for(env.client.execute_workflow(ReviewTest.run,facts,id=f'local-model-review-{i}',task_queue='local-model-review'),60)
                data=json.loads(result)
                print('case',i,'action:',data.get('action'),flush=True)
                assert data['action']==expected,(i,data)
    print('PASS: real local model reviewed three evidence cases inside Temporal/Strands')

if __name__=='__main__':asyncio.run(main())
