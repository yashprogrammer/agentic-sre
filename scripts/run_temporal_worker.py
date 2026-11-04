"""Run the local-demo Temporal worker; credentials remain in process memory."""
import asyncio
import getpass
import logging
import re
import sys
from sre_agent.workers.temporal_local import run


def main():
    namespace = input('Full Temporal Cloud namespace (name.account): ').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*\.[A-Za-z0-9][A-Za-z0-9-]*', namespace):
        print('Invalid namespace format.')
        return 2
    key = getpass.getpass('Temporal API key (input hidden): ')
    if not key:
        print('No key entered; worker not started.')
        return 2
    # Prevent client errors from printing connection metadata or credentials.
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(run(namespace, key))
    except KeyboardInterrupt:
        print('Temporal worker stopped.')
    except Exception as exc:
        print('Temporal worker stopped:', type(exc).__name__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
