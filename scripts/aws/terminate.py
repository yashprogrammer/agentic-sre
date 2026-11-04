"""Terminate only the temporary instance recorded by this project and clean its access resources."""
import json
import sys
from pathlib import Path
import boto3

root=Path(__file__).resolve().parents[2]
path=root/'.data'/'aws-demo-instance.json'
if sys.argv[1:] != ['--yes']:
    raise SystemExit('Run with --yes to terminate the recorded demo instance and remove its SSH access resources.')
if not path.exists():raise SystemExit('No AWS demo instance metadata found.')
m=json.loads(path.read_text())
c=boto3.client('ec2',region_name=m['region'])
i=c.describe_instances(InstanceIds=[m['instance_id']])['Reservations'][0]['Instances'][0]
tags={x['Key']:x['Value'] for x in i.get('Tags',[])}
if tags.get('Name') != m['key_name'] or tags.get('Project') != 'agentic-sre-demo':raise SystemExit('Instance tags do not match recorded demo; no action taken.')
if i['State']['Name'] != 'terminated':
    c.terminate_instances(InstanceIds=[m['instance_id']])
    c.get_waiter('instance_terminated').wait(InstanceIds=[m['instance_id']],WaiterConfig={'Delay':5,'MaxAttempts':30})
integrations_path=root/'.data'/'aws-demo-integrations.json'
if integrations_path.exists():
    x=json.loads(integrations_path.read_text())
    if not all(x[k].startswith(m['key_name']) for k in ('alarm','schedule','instance_role','instance_profile','cleanup_role')):
        raise SystemExit('Integration resource names do not match the recorded demo; review remaining resources manually.')
    scheduler=boto3.client('scheduler',region_name=m['region'])
    cloudwatch=boto3.client('cloudwatch',region_name=m['region'])
    iam=boto3.client('iam',region_name=m['region'])
    try: scheduler.delete_schedule(Name=x['schedule'])
    except scheduler.exceptions.ResourceNotFoundException: pass
    cloudwatch.delete_alarms(AlarmNames=[x['alarm']])
    iam.remove_role_from_instance_profile(InstanceProfileName=x['instance_profile'],RoleName=x['instance_role'])
    iam.delete_instance_profile(InstanceProfileName=x['instance_profile'])
    iam.delete_role_policy(RoleName=x['instance_role'],PolicyName='demo-metrics-and-agentcore')
    iam.delete_role(RoleName=x['instance_role'])
    iam.delete_role_policy(RoleName=x['cleanup_role'],PolicyName='delete-one-demo-alarm')
    iam.delete_role(RoleName=x['cleanup_role'])
    integrations_path.unlink()
c.delete_key_pair(KeyName=m['key_name'])
c.delete_security_group(GroupId=m['security_group'])
for p in (Path(m['key_path']),Path(m['key_path']+'.pub')):p.unlink(missing_ok=True)
path.unlink()
print('Temporary demo instance and access resources removed.')
