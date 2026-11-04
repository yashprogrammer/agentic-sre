"""Start the temporary EC2 supervisor without saving Temporal credentials."""
import getpass
import json
import re
import subprocess
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[2]
path=root/'.data'/'aws-demo-instance.json'
if not path.exists():raise SystemExit('AWS demo instance metadata not found.')
m=json.loads(path.read_text())
integration_path=root/'.data'/'aws-demo-integrations.json'
integrations=json.loads(integration_path.read_text()) if integration_path.exists() else {}
namespace=input('Full Temporal Cloud namespace (name.account): ').strip()
if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*\.[A-Za-z0-9][A-Za-z0-9-]*',namespace):raise SystemExit('Invalid namespace.')
key=getpass.getpass('Temporal API key (hidden): ')
token=getpass.getpass('Presenter token (hidden): ')
groq_key=getpass.getpass('Groq API key (hidden; leave blank to use local Qwen): ')
if not key or not token:raise SystemExit('Both values are required.')
ssh=['ssh','-i',m['key_path'],'-o','BatchMode=yes','-o','ConnectTimeout=8','-o','StrictHostKeyChecking=accept-new','-o',f'UserKnownHostsFile={root / ".data/aws-demo-known-hosts"}','ec2-user@'+m['public_ip']]
command="if pgrep -f '^.venv/bin/python -u scripts/aws/daemon.py$' >/dev/null; then echo 'Demo supervisor is already running.'; else cd ~/agentic-sre && exec .venv/bin/python -u scripts/aws/daemon.py; fi"
payload=json.dumps({'namespace':namespace,'key':key,'presenter_token':token,'groq_key':groq_key,'public_origin':'https://'+m['public_host'],'agentcore_enabled':integrations.get('enabled') is True,'cloudwatch_enabled':integrations.get('enabled') is True})+'\n'
r=subprocess.run(ssh+[command],input=payload,text=True,capture_output=True,timeout=30)
print(r.stdout.strip())
if r.returncode:print('Could not start AWS demo supervisor.',file=sys.stderr)
sys.exit(r.returncode)
