# Durable SRE Agent — design pack

Design date: 3 November 2026. Status: proposed design, ready for review; no application or infrastructure has been deployed by this design task.

## Agreed scope

- Build a working demonstration with a design that can evolve toward production.
- Use **Temporal Cloud from the start**.
- Demonstrate a **real, interactive product-catalog application** with an injected backend/dependency latency fault. HTTP requests really become slow, and remediation changes the configuration used by those requests. Do not restart a real database.
- Show the customer experience first, then the measured alert, manually trigger investigation, approve remediation, and repeat the same application interaction to prove recovery.
- Run the initial Python worker locally so its process can be killed and restarted visibly. AgentCore Runtime is a required later deployment stage with its own readiness gate.
- Cover **every named feature in the pitch**, allowing staged implementation. An architecture slide or recorded hypothetical path does not count as an implemented feature.

## Read in this order

1. [HLD.md](HLD.md): system architecture, responsibilities, trust, deployment, and tradeoffs.
2. [LLD.md](LLD.md): module interfaces, workflow state, data contracts, approval protocol, retries, runbook, and verification.
3. [RESEARCH.md](RESEARCH.md): primary-source checks and integration constraints.
4. [DEMO_PLAN.md](DEMO_PLAN.md): application experience, 10-minute walkthrough, implementation milestones, and proof of improvement.

## The design in one minute

Actual slow requests from the demo application produce measured telemetry and an alert. In presentation mode, the alert appears before any investigation starts; the presenter clicks **Investigate with SRE** to start one Temporal workflow for that alert. A Strands agent gathers evidence through durable Activities and proposes a structured action. Temporal persists the proposal and waits for an authorized human. A durable timer records escalation if the wait exceeds the threshold.

After approval, a constrained execution path creates an approval grant, starts a Step Functions Standard runbook through AgentCore Gateway, and tracks it to completion. The runbook checks the grant before restoring the application's last known good dependency configuration. Independent requests to the actual catalog route must show latency recovery before the incident is resolved. The presenter then repeats the original search in the same app; resetting a dashboard number or health flag cannot satisfy this requirement.

The workflow survives a worker process crash because Temporal Cloud retains its history. Completed Activity results are reused during replay. Work whose completion was not recorded can run again, including a model invocation, so external effects require idempotency and in-flight inference can incur another charge.

## Important corrections to the original pitch

| Original implication | Design position |
|---|---|
| Kill a worker during inference and the token counter never moves | An interrupted model call may run and be billed again. Demonstrate reuse of recorded completed calls separately from interruption of an in-flight call. |
| Waiting is free | No model request or blocked Activity is needed while waiting. Temporal Cloud, storage, observability, and any provisioned processes can still incur costs. |
| Every retry appears as a distinct history event | Show attempt numbers in Activity diagnostics and application traces; do not promise an individual history event per intermediate attempt. |
| A Step Functions tool returns the completed restart | Standard workflows start asynchronously; track the execution to a terminal state. |
| AgentCore Identity supplies every AWS tool credential | AWS service integrations use IAM execution roles. AgentCore Identity is for a deliberately scoped outbound credential use case. |
| An approval token merely needs to be present | The runbook must validate a server-issued grant bound to the incident, exact proposal, target, action, and expiry. |
| AgentCore Runtime must block the first working slice | A local worker connected to Temporal Cloud provides the crash demonstration; full feature completion still requires Runtime hosting after pre-release access and compatibility verification. |

## Defaults awaiting implementation validation

- AWS region: `us-east-1`, subject to model, quota, and feature availability checks. This is a proposed region, not a verified deployment decision.
- Frontend: React/TypeScript; application interface: FastAPI; workflow and Activity workers: Python.
- Authenticated approvals: Amazon Cognito user pool, with a designated approver group. The additional service and permission checks are still pending.
- Runbook: Step Functions **Standard**, with deterministic execution names.
- Escalation: 90 seconds for the demo; approval expiry: 10 minutes; post-remediation health verification: up to 2 minutes. All are configuration defaults, not measured timings.
- Secondary notification: dashboard entry by default. External Slack/email/paging integration is outside the baseline.

## Readiness is separate from design

Previous read-only account checks confirmed Bedrock catalog, Step Functions, and CloudWatch access in the two candidate regions. IAM simulation allowed selected Bedrock, AgentCore, Step Functions, and role operations. AgentCore calls, specific Claude invocation, Temporal Cloud access, quotas, Cognito, DynamoDB, encryption setup, and full deployment permissions remain to be tested. An IAM simulation is not an end-to-end readiness check.

The next implementation gates are the real application request path and Temporal connectivity: catalog search → injected backend delay → measured alert, then authenticated manual investigation → Temporal Cloud workflow → one durable diagnostic Activity. These prove the user-visible problem and orchestration before approvals and remediation are layered in.

## Full feature completion

| Stage | Deliverable | Completion evidence |
|---|---|---|
| 0 — Real application experience | Working catalog UI and HTTP backend, bounded latency injection, measured requests, alert awaiting investigation | The same uncached search is visibly slow under the fault; metrics agree with actual requests |
| 1 — Durable investigation | Temporal Cloud, Strands/Bedrock, read Activities, retries/timeouts, history/replay | A real worker crash resumes the same incident with completed tool results reused |
| 2 — Controlled recovery | Mission Control approval Update, durable timer, Gateway, Step Functions, idempotent configuration recovery | Unauthorized/stale actions denied; approved restore applied once; real requests and the browser become responsive |
| 3 — AgentCore coverage | Memory, Code Interpreter, Identity-backed authenticated diagnostics target, Policy enforcement, Observability | Each feature exercised in a recorded test; authenticated target fails without valid credentials; policy denies forbidden calls |
| 4 — Hosted and operational controls | AgentCore Runtime + Temporal Serverless Workers; live Update Activity Options | Preview access confirmed; hosted workflow resumes after worker/session replacement; live retry change demonstrated |

Stages 1–3 can proceed while preview access is pending. Stage 4 remains an explicit blocker to **full feature completion**; a local worker or architecture slide is not a substitute. The kill demonstration can continue using the local-worker deployment even after the hosted deployment is complete.
