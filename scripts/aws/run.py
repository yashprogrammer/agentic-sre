"""Run demo services on EC2; connection credentials are read from stdin only."""
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from sre_agent.workers.temporal_local import run

root = Path(__file__).resolve().parents[2]
async def main(config=None, monitor_stdin=True):
    config = config if config is not None else json.loads(sys.stdin.readline())
    namespace, key, token = config['namespace'], config['key'], config['presenter_token']
    groq_key = config.get('groq_key', '')
    public_origin = config.get('public_origin', '')
    agentcore_enabled = config.get('agentcore_enabled') is True
    cloudwatch_enabled = config.get('cloudwatch_enabled') is True
    del config
    logging.disable(logging.CRITICAL)
    os.environ.update(DEMOSHOP_DB=str(root / '.data' / 'aws-demo.sqlite3'), DEMOSHOP_ORCHESTRATOR='temporal', DEMOSHOP_DIAGNOSIS='strands-groq' if groq_key else 'strands-local', DEMOSHOP_ALLOWED_ORIGIN='http://127.0.0.1:5174')
    os.environ['DEMOSHOP_PUBLIC_ORIGIN'] = public_origin
    os.environ['DEMOSHOP_PROBE_MAX_SECONDS'] = '21600'
    os.environ['DEMOSHOP_AGENTCORE'] = '1' if agentcore_enabled else '0'
    os.environ['DEMOSHOP_CLOUDWATCH'] = '1' if cloudwatch_enabled else '0'
    base = os.environ.copy()
    app_env = dict(base, DEMOSHOP_PRESENTER_TOKEN=token)
    children = []
    disconnected = asyncio.Event()
    loop = asyncio.get_running_loop()
    def check_stdin():
        if not os.read(0, 1):
            disconnected.set()
            loop.remove_reader(0)
    if monitor_stdin:
        loop.add_reader(0, check_stdin)
    try:
        children.append(subprocess.Popen(['ollama','serve'], env=dict(base, OLLAMA_HOST='127.0.0.1:11434', OLLAMA_KEEP_ALIVE='1m'), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        children.append(subprocess.Popen([sys.executable,'-m','uvicorn','scripts.aws.app:app','--host','127.0.0.1','--port','8000'],cwd=root,env=app_env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
        for _ in range(100):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/openapi.json',timeout=.5): break
            except OSError: await asyncio.sleep(.1)
        else: raise RuntimeError('API readiness failed')
        children.append(subprocess.Popen([sys.executable,'-m','sre_agent.detection.probe'],cwd=root,env=base,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
        if cloudwatch_enabled:
            children.append(subprocess.Popen([sys.executable,'-m','sre_agent.detection.cloudwatch_exporter'],cwd=root,env=base,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
        print('EC2 services started; connecting Temporal Cloud worker.',flush=True)
        worker=asyncio.create_task(run(namespace,key,groq_key))
        while not worker.done():
            if disconnected.is_set():
                worker.cancel()
                try: await worker
                except asyncio.CancelledError: pass
                break
            if any(p.poll() is not None for p in children):
                raise RuntimeError('A demo service stopped')
            await asyncio.sleep(1)
        if not worker.cancelled(): worker.result()
    finally:
        if monitor_stdin:
            loop.remove_reader(0)
        for process in reversed(children):
            if process.poll() is None: process.terminate()
        for process in children:
            try: process.wait(timeout=8)
            except subprocess.TimeoutExpired: process.kill(); process.wait()

if __name__=='__main__':
    def stop(_signal, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGHUP, stop)
    signal.signal(signal.SIGTERM, stop)
    try: asyncio.run(main())
    except KeyboardInterrupt: print('Demo stopped.',flush=True)
    except Exception as exc: print('Demo stopped:',type(exc).__name__,flush=True); sys.exit(1)
