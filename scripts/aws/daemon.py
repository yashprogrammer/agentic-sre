"""Supervise the temporary EC2 demo independently of the presenter's SSH session.

Connection credentials arrive through stdin and remain in process memory.
"""
import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path
from run import main


def stop(_signum, _frame):
    raise KeyboardInterrupt


def launch():
    config = json.loads(sys.stdin.readline())
    if not all(config.get(k) for k in ('namespace', 'key', 'presenter_token')):
        raise SystemExit('Required connection details are missing.')
    if os.fork():
        print('Demo supervisor starting.', flush=True)
        return
    os.setsid()
    if os.fork():
        os._exit(0)
    os.chdir(Path(__file__).resolve().parents[2])
    input_fd = os.open('/dev/null', os.O_RDONLY)
    log_fd = os.open('/tmp/sre-demo-supervisor.log', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.dup2(input_fd, 0); os.dup2(log_fd, 1); os.dup2(log_fd, 2)
    os.close(input_fd); os.close(log_fd)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    while True:
        try:
            asyncio.run(main(config, monitor_stdin=False))
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print('Demo service restarting:', type(exc).__name__, flush=True)
        time.sleep(5)


if __name__ == '__main__':
    launch()
