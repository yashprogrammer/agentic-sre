"""Interactive, read-only Temporal Cloud connection check; never writes a key."""
import asyncio
import getpass
import re
import sys

from temporalio.client import Client


async def main():
    namespace = input('Full Temporal namespace (name.account): ').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*\.[A-Za-z0-9][A-Za-z0-9-]*', namespace):
        print('Invalid namespace format. Use the full name shown by Temporal Cloud.')
        return 2
    key = getpass.getpass('Temporal API key (input hidden): ')
    if not key:
        print('No key entered; no connection attempted.')
        return 2
    try:
        client = await asyncio.wait_for(Client.connect(f'{namespace}.tmprl.cloud:7233', namespace=namespace, api_key=key, tls=True), timeout=20)
        # A successful authenticated list request verifies access without
        # displaying workflow details or starting a billable workflow.
        async def verify():
            async for _ in client.list_workflows(page_size=1):
                break
        await asyncio.wait_for(verify(), timeout=20)
    except Exception as exc:
        print(f'Connection or read-only access check failed ({type(exc).__name__}). No credential was printed.')
        return 1
    finally:
        key = None
    print('SUCCESS: authenticated Temporal Cloud connection and read-only workflow access verified.')
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
