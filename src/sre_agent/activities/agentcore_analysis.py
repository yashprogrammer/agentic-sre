"""Bounded AgentCore Code Interpreter analysis of measured synthetic latency."""
import json
import asyncio
import math
import statistics

import boto3
from botocore.config import Config
from temporalio import activity


@activity.defn(name='analyze_latency_with_agentcore')
async def analyze_latency_with_agentcore(samples: list[float]) -> dict:
    return await asyncio.to_thread(_analyze, samples)


def _analyze(samples: list[float]) -> dict:
    if not isinstance(samples, list) or len(samples) != 5 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 60000 for x in samples):
        raise ValueError('Invalid measured sample window')
    values = [round(float(x), 2) for x in samples]
    code = ('import json,statistics\nvalues=' + json.dumps(values) + '\n'
            'print(json.dumps({"count":len(values),"median_ms":statistics.median(values),"min_ms":min(values),"max_ms":max(values)}))')
    client = boto3.client('bedrock-agentcore', region_name='us-east-1', config=Config(connect_timeout=4, read_timeout=20, retries={'total_max_attempts': 1}))
    identifier = 'aws.codeinterpreter.v1'
    session_id = None
    try:
        session_id = client.start_code_interpreter_session(codeInterpreterIdentifier=identifier, name='sre-latency-analysis', sessionTimeoutSeconds=60)['sessionId']
        response = client.invoke_code_interpreter(codeInterpreterIdentifier=identifier, sessionId=session_id, name='executeCode', arguments={'language':'python','code':code})
        results = []
        for event in response['stream']:
            if 'result' in event:
                result = event['result']
                if result.get('isError') or result.get('structuredContent', {}).get('exitCode', 0) != 0:
                    raise ValueError('AgentCore analysis failed')
                results.extend(c.get('text', '') for c in result.get('content', []) if c.get('type') == 'text')
        if len(results) != 1:
            raise ValueError('Invalid AgentCore output')
        data = json.loads(results[0])
        expected = {'count':5,'median_ms':statistics.median(values),'min_ms':min(values),'max_ms':max(values)}
        if data != expected:
            raise ValueError('AgentCore output does not match measured input')
        return {'provider':'AgentCore Code Interpreter', **data}
    finally:
        if session_id:
            try:
                client.stop_code_interpreter_session(codeInterpreterIdentifier=identifier, sessionId=session_id)
            except Exception:
                # The short-lived session is also bounded by its 60-second timeout.
                pass
