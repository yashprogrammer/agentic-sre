# Agentic SRE Demo: architecture explained

This document describes the implemented AWS-hosted demonstration as of November 4, 2026. The original HLD and LLD also describe a broader target architecture; Bedrock inference, AgentCore Runtime, Step Functions, and a production runbook are not connected. The implementation uses AgentCore Code Interpreter and publishes measured probe data to CloudWatch.

## High-level design

The demo shows an incident from the customer's perspective: a real catalog search becomes slow, measured requests trigger an alert, a human starts an investigation, a model reviews evidence, the human approves a configuration restore, and fresh requests verify recovery.

### Components

1. **DemoShop:** React frontend and Python FastAPI product catalog. Browser requests go through an HTTPS reverse proxy to the application on an EC2 instance.
2. **Presenter controls:** A protected page injects a four-second server-side delay into the catalog's configuration; emergency reset is a manual action.
3. **Monitoring probe:** A separate process on the same EC2 instance sends `GET /api/catalog?q=backpack` roughly every five seconds, measures elapsed time, and checks the expected products. SQLite stores observations and alerts.
4. **Mission Control:** Protected dashboard displaying probe data, alerts, investigation state, a proposal, approval controls, and a link to the Temporal workflow.
5. **Temporal Cloud:** Separately hosted managed workflow service for incident orchestration, history, timers, activities, and an approval update. It is not an AWS-managed service.
6. **EC2 worker and model:** The worker executes activities and connects to Temporal Cloud. A Strands `TemporalAgent` invokes Groq-hosted GPT-OSS 20B when configured, or Qwen through Ollama on EC2 otherwise. It reviews a small structured set of workflow-gathered facts; it does not choose tools or independently investigate.
7. **AgentCore and CloudWatch:** A Temporal activity invokes AgentCore Code Interpreter to calculate statistics from five measured latencies. A separate exporter publishes probe latency and correctness to CloudWatch, where an independent alarm evaluates latency. The CloudWatch alarm does not initiate the incident.
8. **Restore and verification:** An approved, bounded activity restores the known-good configuration in SQLite. The probe provides fresh observations used to verify recovery. Both probe and application run on the same EC2 instance, so they are separate processes, not independently hosted systems.

### Demonstration sequence

Healthy search → inject four-second backend delay → measured alert → investigate → evidence and proposal → Groq or local Qwen review → human approval → restore → five fresh correct fast checks → repeat the customer search.

## Low-level design

### 1. Request and fault

The frontend sends `GET /api/catalog?q=backpack`. The FastAPI service reads the current SQLite configuration at the beginning of the request, applies its `delay_ms`, looks up products, and returns JSON. The response includes request and configuration identifiers. The simulated fault changes the configured delay from 0 to 4,000 ms. This is a real delay in the demo backend; it is not an actual database failure.

Before injection, five recent correct probe observations faster than one second are used to record a known-good configuration and evidence. Injecting the fault updates the configuration version and fault generation.

### 2. Monitoring and alerting

The probe runs approximately every five seconds. It checks HTTP status and verifies that the response contains the expected backpack product IDs. In the latest five observations, at least three valid requests over 2,000 ms within a 60-second window create an alert for the current fault generation. An alert does not automatically launch an investigation.

### 3. Starting an investigation

The presenter clicks **Investigate with SRE**. The API checks presenter authorization, current fault generation, and probe freshness. It captures five recent observations, requiring at least three slow valid requests for the current configuration, and creates the incident. The original alert evidence is retained separately. The EC2 bridge starts or reconnects to a Temporal `IncidentWorkflow` using an incident-specific workflow ID.

### 4. Evidence, proposal, and model review

The workflow schedules `diagnose`, a read-only Temporal activity. It validates the current alert and generation, fresh evidence, the known-good configuration's digest, and its recorded fast baseline. It constructs a proposal bound to the incident, target, configuration version, generation, digest, evidence, and expiry.

The workflow validates the proposal and may invoke AgentCore Code Interpreter to analyze five measured latencies. It then starts a model-review child workflow. A Strands `TemporalAgent` invokes the configured Groq GPT-OSS 20B or local Qwen model with structured facts and no tools. Groq mode sends those synthetic facts to Groq for inference. The output must match the supported cause and action. Failed, invalid, or unsupported review leads to manual review instead of an automatic restore. The model reviews a deterministic proposal; it does not freely create a runbook.

### 5. Approval and action

The workflow waits for the presenter. The proposal and its SHA-256 hash are shown in Mission Control. The presenter approves or rejects; the API records the decision in SQLite, and the bridge delivers a Temporal Update. The restore activity checks the recorded decision, matching request and proposal hash, expiry, target, current version and generation, and verified configuration digest.

A transactional action receipt makes retrying the same action return its existing result rather than applying it again. This is a local demo control backed by a shared database and token; it is not independently enforced production identity or authorization.

### 6. Verify recovery

After the restore, the `verify_catalog` activity reads new probe results. The workflow requires five distinct, consecutive correct observations started after the change, each below 1,000 ms and matching the applied configuration and generation. A changed configuration causes an unresolved outcome; missing observations are awaited within a bounded verification window. Only then does the workflow report `RESOLVED`. The presenter repeats the same browser search to verify the user-visible result; browser latency includes network time and can differ from the probe's EC2-local measurements.

### State and history

SQLite on EC2 holds product data, configuration, measurements, alerts, incident UI state, approvals, and receipts. Temporal Cloud holds workflow execution history, timers, updates, and activity results. The bridge synchronizes workflow snapshots into the local dashboard. Temporal can replay workflow history after a worker restart; the availability of the EC2 application, SQLite, model, and worker is a separate concern, and this demo does not establish production high availability.

### Access and hosting

The public storefront uses HTTPS and an EC2 reverse proxy. The presenter and Mission Control paths require browser login plus an application presenter token. The security group permits public HTTPS and HTTP redirect/certificate validation; SSH is limited to a configured presenter IP. The backend and model listen on loopback. This is a temporary, single-instance demonstration, not a production security architecture.

## What is implemented and what is planned

| Component | Current demo |
|---|---|
| AWS EC2 | Runs the application, worker, probe, SQLite, and Qwen/Ollama |
| Temporal Cloud | Runs and records the incident workflow |
| Strands | Invokes Groq GPT-OSS 20B or local Qwen for a constrained evidence review |
| Approval | Presenter-token and SQLite-backed demo approval, with Temporal Update |
| Amazon Bedrock / Claude | Not connected; preflight inference was unsuccessful |
| AgentCore Code Interpreter | Invoked by a Temporal activity to analyze five measured latencies |
| AgentCore Runtime, Gateway, Memory / Step Functions | Planned in the target design, not connected |
| CloudWatch metrics and alarm | Publishes measured probe data and separately alarms; the presenter starts the investigation from the app alert |
| Production identity, independent authorization, highly available data store | Not implemented |

## Code map

- `src/sre_agent/catalog/app.py`: API, controls, alert and incident operations, monitoring response.
- `src/sre_agent/activities/agentcore_analysis.py`: bounded AgentCore Code Interpreter analysis.
- `src/sre_agent/detection/cloudwatch_exporter.py`: measured CloudWatch metrics.
- `src/sre_agent/detection/probe.py`: probe, measurement, alert detection, and lease.
- `src/sre_agent/workflows/temporal_incident.py`: incident workflow, approval update, model-review child workflow, verification.
- `src/sre_agent/activities/local_diagnosis.py`: evidence checks and proposal.
- `src/sre_agent/activities/local_execution.py`: bounded restore, receipt, and verification activity.
- `src/sre_agent/workers/temporal_local.py`: Temporal worker and SQLite/dashboard bridge.
- `apps/demo_shop/src/main.tsx`: storefront, Mission Control, and presenter UI.
- `scripts/aws/daemon.py` and `scripts/aws/run.py`: supervised EC2 demo processes.

## Demo lifecycle

The EC2 instance is temporary. It was scheduled to terminate at 10:05 p.m. India time on November 4, 2026, with its root volume deleted. This shutdown is best-effort and does not enforce a spending limit. Check current state and schedule before presenting; do not assume an old rehearsal is still running.
