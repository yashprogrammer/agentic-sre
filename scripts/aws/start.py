"""Connect a private local browser tunnel and start the temporary EC2 demo."""
import getpass
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

root=Path(__file__).resolve().parents[2]
metadata=root/'.data'/'aws-demo-instance.json'

def main():
    if not metadata.exists():
        print('AWS demo instance metadata not found.')
        return 1
    m=json.loads(metadata.read_text())
    integration_path=root/'.data'/'aws-demo-integrations.json'
    integrations=json.loads(integration_path.read_text()) if integration_path.exists() else {}
    namespace=input('Full Temporal Cloud namespace (name.account): ').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*\.[A-Za-z0-9][A-Za-z0-9-]*',namespace):
        print('Invalid namespace.')
        return 2
    key=getpass.getpass('Temporal API key (hidden): ')
    token=getpass.getpass('Choose local presenter token (hidden): ')
    if not key or not token:
        print('Both values are required.')
        return 2
    ssh=['ssh','-i',m['key_path'],'-o','BatchMode=yes','-o','ExitOnForwardFailure=yes','-o','StrictHostKeyChecking=accept-new','-o',f'UserKnownHostsFile={root / ".data" / "aws-demo-known-hosts"}','ec2-user@'+m['public_ip']]
    tunnel=None; worker=None
    try:
        tunnel=subprocess.Popen(ssh[:-1]+['-N','-L','127.0.0.1:5174:127.0.0.1:8000',ssh[-1]],stdin=subprocess.DEVNULL)
        time.sleep(2)
        if tunnel.poll() is not None: raise RuntimeError('Tunnel failed to start')
        worker=subprocess.Popen(ssh+['cd ~/agentic-sre && .venv/bin/python -u scripts/aws/run.py'],stdin=subprocess.PIPE,text=True)
        public_origin = 'https://' + m['public_host'] if m.get('public_host') else ''
        worker.stdin.write(json.dumps({'namespace':namespace,'key':key,'presenter_token':token,'public_origin':public_origin,'agentcore_enabled':integrations.get('enabled') is True,'cloudwatch_enabled':integrations.get('enabled') is True})+'\n');worker.stdin.flush()
        print('AWS demo tunnel: http://127.0.0.1:5174/  |  Ctrl-C stops the demo and tunnel.',flush=True)
        while worker.poll() is None and tunnel.poll() is None:time.sleep(1)
        if worker.poll() is not None and worker.returncode:raise RuntimeError('Remote worker stopped')
        if tunnel.poll() is not None:raise RuntimeError('SSH tunnel stopped')
    except KeyboardInterrupt:
        print('\nStopping AWS demo.',flush=True)
    except Exception as e:
        print('AWS demo stopped:',type(e).__name__,flush=True)
        return 1
    finally:
        for p in (worker,tunnel):
            if p and p.poll() is None:p.terminate()
        for p in (worker,tunnel):
            if p:
                try:p.wait(timeout=8)
                except subprocess.TimeoutExpired:p.kill();p.wait()
    return 0

if __name__=='__main__':sys.exit(main())
