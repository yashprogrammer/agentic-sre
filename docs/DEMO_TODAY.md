# Demo today: Temporal Cloud and local DemoShop

This rehearsal uses Temporal Cloud for workflow history and orchestration. DemoShop, the latency fault, the probe, SQLite, configuration restore, and Qwen inference run on this Mac. Strands invokes the local Qwen model to review facts gathered by a deterministic read activity; it does not choose or invoke diagnostic tools. This is not AWS Bedrock, AgentCore, Step Functions, or a production security implementation.

## Start

From the project folder, run:

```sh
.venv-temporal-demo/bin/python scripts/run_temporal_demo.py
```

Enter the full Temporal Cloud namespace shown in the Temporal console. Enter the existing API key when prompted; input is hidden. Choose a separate presenter token when prompted; this local token protects the controls. Keep the terminal open. The launcher starts the API, UI, probe and worker, and starts Ollama if necessary. It expects the already installed `qwen3:0.6b` model and does not download it. The probe runs for at most 15 minutes; restart the launcher for another session. Press Ctrl-C to stop its processes.

## Walkthrough

1. Open [DemoShop](http://127.0.0.1:5173/), search `backpack`, and note the results and response time. Open [Mission Control](http://127.0.0.1:5173/mission-control) and enter the presenter token. Wait until at least five successful fast probe samples appear. This establishes a verified configuration for the restore.
2. Open [Presenter controls](http://127.0.0.1:5173/presenter), enter the token, and inject latency. Repeat the same `backpack` search in DemoShop: the server waits roughly four seconds.
3. In Mission Control, wait for a measured latency alert, then select **Investigate with SRE**. The real Temporal Cloud workflow gathers measurements and asks the local Qwen model to review the evidence. Review the proposed restore and approve it.
4. Repeat the same DemoShop search and verify that the correct products return quickly. Wait for five fresh, correct fast probe requests before Mission Control marks the incident resolved. If model review, approval, restore, or verification fails, report the state shown; do not claim recovery from dashboard status alone.
5. Stop the launcher with Ctrl-C. If the fault remains, use the presenter **Emergency reset** before stopping; that is a manual reset, not agent remediation.

The approval is a local demo control backed by SQLite and a presenter token. It is not separate production identity or role enforcement. Keep the app on loopback and do not deploy it as-is. Temporal Cloud usage can incur charges; this launcher does not enforce a dollar limit. No successful AWS Bedrock inference was observed in preflight.

For a deterministic fallback when local Qwen is unavailable, start with `DEMOSHOP_DIAGNOSIS=deterministic .venv-temporal-demo/bin/python scripts/run_temporal_demo.py` and clearly say the diagnosis uses rules rather than an AI model. Restart the demo before changing modes.
