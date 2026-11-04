"""Start the local DemoShop + Temporal Cloud demo; Ctrl-C cleans up its processes."""
import asyncio
import getpass
import logging
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
import json
from pathlib import Path

from sre_agent.workers.temporal_local import run

ROOT = Path(__file__).resolve().parents[1]


async def supervise(namespace, key, children):
    worker = asyncio.create_task(run(namespace, key))
    try:
        while not worker.done():
            failed = next((name for name, proc in children if proc.poll() is not None), None)
            if failed:
                print(f'{failed} stopped; shutting down the demo. Restart to run another bounded probe.', flush=True)
                break
            await asyncio.sleep(1)
        if worker.done():
            worker.result()
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass


def main():
    namespace=input('Full Temporal Cloud namespace (name.account): ').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*\.[A-Za-z0-9][A-Za-z0-9-]*',namespace):
        print('Invalid namespace format.')
        return 2
    key=getpass.getpass('Temporal API key (hidden): ')
    token=getpass.getpass('Choose a local presenter token (hidden): ')
    if not key or not token:
        print('Both values are required; demo was not started.')
        return 2
    logging.disable(logging.CRITICAL)
    env=os.environ.copy()
    env['DEMOSHOP_DB']=os.environ.get('DEMOSHOP_TEMPORAL_DB',str(ROOT/'.data'/'temporal_demo.sqlite3'))
    env['DEMOSHOP_ORCHESTRATOR']='temporal'
    env['DEMOSHOP_DIAGNOSIS']=os.environ.get('DEMOSHOP_DIAGNOSIS','strands-local')
    env['DEMOSHOP_PRESENTER_TOKEN']=token
    child_env=env.copy()
    child_env.pop('DEMOSHOP_PRESENTER_TOKEN',None)
    os.environ['DEMOSHOP_DB']=env['DEMOSHOP_DB']
    os.environ['DEMOSHOP_ORCHESTRATOR']='temporal'
    os.environ['DEMOSHOP_DIAGNOSIS']=env['DEMOSHOP_DIAGNOSIS']
    children=[]
    try:
        if env['DEMOSHOP_DIAGNOSIS']=='strands-local':
            def model_ready():
                try:
                    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=1) as response:
                        return any(m.get('name')=='qwen3:0.6b' for m in json.load(response).get('models',[]))
                except (OSError,ValueError):
                    return False
            if not model_ready():
                ollama_env=child_env.copy()
                ollama_env['OLLAMA_HOST']='127.0.0.1:11434'
                ollama_env['OLLAMA_KEEP_ALIVE']='1m'
                children.append(('Ollama',subprocess.Popen(['ollama','serve'],cwd=ROOT,env=ollama_env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)))
                deadline=time.monotonic()+10
                while not model_ready():
                    if children[-1][1].poll() is not None or time.monotonic()>=deadline:
                        raise RuntimeError('Local Qwen model unavailable; install qwen3:0.6b or choose deterministic mode')
                    time.sleep(.2)
        children.append(('Catalog API',subprocess.Popen([sys.executable,'-m','uvicorn','sre_agent.catalog.app:app','--host','127.0.0.1','--port','8000'],cwd=ROOT,env=env)))
        children.append(('Frontend',subprocess.Popen(['npm','run','dev','--','--strictPort'],cwd=ROOT/'apps'/'demo_shop',env=child_env,start_new_session=True)))
        deadline=time.monotonic()+10
        while True:
            if next(proc for name,proc in children if name=='Catalog API').poll() is not None:
                raise RuntimeError('Catalog API did not start')
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/openapi.json',timeout=.5) as response:
                    if json.load(response).get('info',{}).get('title')=='DemoShop local catalog':
                        break
            except (OSError,ValueError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError('Catalog API readiness timed out')
            time.sleep(.1)
        children.append(('Probe',subprocess.Popen([sys.executable,'-m','sre_agent.detection.probe'],cwd=ROOT,env=child_env)))
        print('DemoShop: http://127.0.0.1:5173/  |  Mission Control: /mission-control  |  Presenter: /presenter',flush=True)
        print('The probe stops after 15 minutes. Ctrl-C stops the local demo processes.',flush=True)
        asyncio.run(supervise(namespace,key,children))
    except KeyboardInterrupt:
        print('\nStopping the demo.',flush=True)
    except Exception as exc:
        print('Demo stopped:',type(exc).__name__,flush=True)
        return 1
    finally:
        for name,process in reversed(children):
            if process.poll() is None:
                if name=='Frontend':
                    try: os.killpg(process.pid,signal.SIGTERM)
                    except ProcessLookupError: pass
                else:
                    process.terminate()
        for _,process in children:
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    return 0


if __name__=='__main__':
    sys.exit(main())
