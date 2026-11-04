# Agentic SRE: DemoShop recovery demo

For today’s Temporal Cloud and local Qwen/Strands walkthrough, use [the presenter guide](docs/DEMO_TODAY.md). The instructions below describe the separate deterministic local-only fallback.

This local implementation exercises the customer-impact story in the [demo plan](docs/design/DEMO_PLAN.md): a real catalog, a server-side latency fault, measured alert, manually triggered investigation, explicit approval, configuration restore, and independent recovery verification. Diagnosis uses **local deterministic rules**, not an LLM. SQLite-backed local processes are not the planned Temporal Cloud, AWS, AgentCore, or Step Functions implementation. The local presenter token is not production authentication. Keep both servers bound to loopback and do not deploy this implementation as-is.

## Run locally

Use Python 3.11–3.14 and Node 20 or 22. Open four terminals in this directory.

**Terminal 1: catalog and control API** (the `read` command uses zsh):

```sh
python3.14 -m venv .venv  # or another supported Python version
source .venv/bin/activate
pip install -e '.[test]'
read -s "DEMOSHOP_PRESENTER_TOKEN?Choose a strong presenter token: "
export DEMOSHOP_PRESENTER_TOKEN
uvicorn sre_agent.catalog.app:app --host 127.0.0.1 --port 8000
```

**Terminal 2: frontend:**

```sh
cd apps/demo_shop
npm ci
npm run dev
```

**Terminal 3: independent HTTP probe:**

```sh
source .venv/bin/activate
python -m sre_agent.detection.probe
```

**Terminal 4: local investigation worker:**

```sh
source .venv/bin/activate
python -m sre_agent.workers.local
```

1. Open `http://127.0.0.1:5173/` and search `backpack` to establish the browser baseline. Open `http://127.0.0.1:5173/mission-control` and enter the presenter token.
2. Wait for **five successful probe requests below 1,000 ms**, all using the current configuration. These establish the known-good configuration needed for a proposed restore. The probe runs every five seconds and validates product IDs.
3. Open `http://127.0.0.1:5173/presenter` in a separate tab, enter the token, and inject latency. Repeat the same DemoShop search: the response waits on the server for approximately four seconds.
4. Mission Control opens an alert after five observations with at least three correct, slow requests. Select **Investigate with SRE**. The local worker correlates the samples and configuration, then proposes a specific previously verified restore. If the baseline is missing or the target changed, it requests manual review instead.
5. Review the proposal and approve or reject it. Approval binds the displayed hash and configuration generation. The local worker applies the approved restore once, then requires five new correct probe requests under 1,000 ms with the applied version before marking the incident resolved. Repeat the same browser search to feel and measure the change.
6. Stop the probe and worker with Ctrl-C. Use **Emergency reset** only as an audited manual teardown if a fault remains; it is not agent recovery. Stop the servers. The probe has a 15-minute maximum schedule and a SQLite lease that prevents duplicate runners.

Presenter actions, incident state, action receipts, and measurements remain in `.data/demoshop.sqlite3`. Delete it only when processes are stopped and you intentionally want a fresh demo. A stopped or missing probe appears as stale, never healthy. The local token is held in page memory, and the same local operator can investigate and approve; there is no separate identity or role enforcement. The worker can resume persisted local state after restart, but this is not Temporal replay and does not provide the production trust boundaries in the design.

The separate Temporal Cloud launcher connects the local application and SQLite-backed worker to a real Temporal workflow, with optional local Qwen/Strands evidence review. The planned AWS cloud agent, authenticated identity, separate execution role, signed grants, DynamoDB, AWS runbook, Gateway, Policy, Memory, Code Interpreter, hosted worker, and trace integrations remain unimplemented. The deterministic fallback instructions above create no cloud resources.

## Verify

```sh
pytest
cd apps/demo_shop && npm run build
```
