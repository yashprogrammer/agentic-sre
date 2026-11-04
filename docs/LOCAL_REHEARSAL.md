# Local end-to-end rehearsal

Date: 2026-11-03. This is a local SQLite/FastAPI rehearsal, not evidence of the planned AWS/Temporal/AgentCore deployment. Diagnosis was deterministic and the approval used a local shared presenter token.

The presenter established a known-good configuration with at least five independent correct probe requests, injected the four-second backend delay, and ran the same `backpack` search in the same browser. The detector opened an alert from measured requests, the presenter started investigation, and the local worker proposed a restore of the verified prior settings. After approval, the worker applied the configuration change and the detector observed five correct post-action requests under the recovery threshold. The incident then became RESOLVED. No emergency reset caused this recovery.

| Measurement | Browser search |
|---|---:|
| Before fault | 17 ms |
| Injected fault | 4,019 ms |
| After approved restore | 14 ms |

Both backpack products were present on each search. These are single local-browser observations, not a production latency claim. The five-sample probe medians were 5 ms for baseline, 4,006 ms for the mixed triggering window, and 7 ms for recovery. The triggering window contained both fast and slow requests. Probe and browser timing are distinct measurement scopes.

The API was restarted afterward; the incident, action receipt, verification evidence and comparison windows remained visible. The probe was stopped and Mission Control showed telemetry as stale. The local test database is separate from the normal `.data` database.

## Remaining design gates

The rehearsal does **not** demonstrate a model-driven Strands agent, Temporal Cloud workflow or history replay, worker roles, durable Temporal timers, Cognito authorization, independent grant enforcement, Step Functions, AWS catalog backend, DynamoDB, AgentCore Memory, Identity, Policy, Gateway, Code Interpreter, Runtime, CloudWatch traces, live retry tuning, or a cloud deployment. These remain required by the design. Model listing through the configured AWS identity succeeded, but that does not prove model invocation access. The Temporal Cloud namespace and region have not yet been established. No cloud resources were provisioned for this rehearsal.

## Temporal compatibility spike

A separate local Temporal development server (CLI 1.10.0, Server 1.32.2) was exercised with Python 3.14, Temporal SDK 1.35.0, `temporalio-strands-agents` 0.1.0, and Strands 1.63.0. A test workflow completed a read Activity, waited for a decision, resumed after the first worker shut down and another started, accepted a Workflow Update, reused the recorded read result without a second Activity call, and replayed its captured history. `StrandsPlugin` was registered and its current import paths loaded. The spike used no model or AWS calls, and its workflow is not connected to DemoShop. It does not prove Temporal Cloud connectivity, agent model/tool replay, process failure during an Activity, or the required cloud security controls.

To reproduce in a separate environment:

```sh
python3.14 -m venv .venv-temporal-spike
.venv-temporal-spike/bin/pip install -e '.[test]' -r requirements-temporal-spike.txt
.venv-temporal-spike/bin/python scripts/temporal_replay_spike.py
```

The first run downloads the Temporal development server. The test server runs locally with in-memory persistence and exits afterward.

The time-skipping test service did not complete the Workflow Update in the initial attempt; the successful run above used the current local development server. Time-skipping timer and decision tests remain unverified.

## Temporal incident workflow development

`src/sre_agent/workflows/temporal_incident.py` now contains a separate, unwired Temporal state machine. A local development-server contract run used fake diagnosis, restore, and verification Activities to check a stale decision, worker replacement while awaiting approval, approved execution, five verification calls, rejection, and history replay. Reproduce with `PYTHONPATH=src .venv-temporal-spike/bin/python scripts/test_temporal_incident.py` after installing the isolated spike requirements above. The test takes at least 20 seconds because verification calls are spaced five seconds apart.

This workflow is **not connected** to Mission Control, the actual catalog, Bedrock, Temporal Cloud, or a runbook. The test Activities are controlled test fixtures. It lacks independently enforced grants and real role-based identity, trusted runbook reconciliation, the actual Strands diagnosis and read tools, a working escalation notification, cancellation of in-flight Activities, and many failure, race, and replay scenarios in the LLD. It must not be used to operate a real environment.

The local Temporal contract test also invokes the read-only diagnostic Activity against isolated SQLite probe records, validates the proposal, and rejects it. The restore and recovery Activities remain test fixtures. The FastAPI pin was updated to 0.128.8 to resolve its Starlette dependency conflict with the Temporal/Strands plugin; the combined environment passed `pip check`.

The later Temporal contract run also covered expiry and cancellation while waiting, plus cancellation while a diagnostic Activity was in flight. The workflow ignores the eventual diagnostic result after cancellation; it does not yet cancel the Activity itself. The real local diagnostic Activity was tested against isolated recorded samples inside Temporal. The execution and verification Activities in that contract run remained fixtures, so it does not demonstrate a Temporal-driven restoration of DemoShop.
