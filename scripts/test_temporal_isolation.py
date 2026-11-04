"""Prove local demo databases do not share a Temporal task queue."""
import os
import tempfile
from sre_agent.catalog.app import initialize
from sre_agent.workers.temporal_local import queue_name

with tempfile.TemporaryDirectory() as root:
    os.environ['DEMOSHOP_ORCHESTRATOR']='temporal'
    os.environ['DEMOSHOP_DB']=root+'/first.sqlite'
    initialize()
    first=queue_name()
    assert queue_name()==first
    os.environ['DEMOSHOP_DB']=root+'/second.sqlite'
    initialize()
    assert queue_name()!=first
    os.environ['DEMOSHOP_DB']=root+'/first.sqlite'
    assert queue_name()==first
print('PASS: stable task queue per database and isolation between demo environments')
