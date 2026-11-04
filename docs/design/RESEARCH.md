# Integration research for the durable SRE agent

Checked: 3 November 2026 (Asia/Kolkata). Primary vendor documentation only. **Supported** means documented capability, not verified access in this AWS account. **Conditional** means preview, configuration, permissions, or integration validation is required. **Unverified** means this research did not establish it. No cloud changes or model invocations were performed.

The user-selected first stage is Temporal Cloud, a local worker for the crash demonstration, and a dedicated demo service with a simulated database incident. **The complete project must exercise every named feature.** AgentCore Runtime is a required later deployment after access validation; staging does not remove this completion requirement.

## 1. Strands and Temporal integration

**Conditional — Public Preview.** Current documentation uses the standalone `temporalio-strands-agents` distribution, with `StrandsPlugin`, `TemporalAgent`, and `TemporalMCPClient` in `temporalio.strands_agents`; workflow helpers including `activity_as_tool` are in `temporalio.strands_agents.workflow`. Pin dependency versions and verify the selected sample against the installed release. Older `contrib` imports should not be assumed current.

External I/O tools require Activities registered on the worker. Model operations are Activities; MCP client factories are configured on the worker. Strands model retries are disabled by `TemporalAgent`, so configure Temporal retry policies. Hook code executes in workflow context; use `activity_as_hook` for I/O. Human interrupts can return control to the workflow, which durably waits for a Signal before resuming. Structured output is supported.

Source: [Temporal Strands integration](https://docs.temporal.io/develop/python/integrations/strands-agents).

**Design implication:** keep approval, escalation, and remediation state transitions in deterministic workflow code. Give the reasoning agent read-only investigation tools; pass its typed proposal to the workflow for validation and authorization.

## 2. Crash recovery and token claims

**Supported:** completed Activity results recorded in history are reused during workflow replay. **Unsupported as a general promise:** exactly-once execution of an external API or an in-flight model request. Activities must tolerate repeated execution; if the worker dies after a remote side effect but before completion is durably recorded, a retry can repeat that effect.

Source: [Temporal Activity definition and idempotency](https://docs.temporal.io/activity-definition).

**Design inference:** an interrupted Bedrock invocation can incur tokens and then be retried. Do not promise that token usage never increases after killing a worker during an LLM call. Demonstrate unchanged completed health/metrics invocation counts; separately explain possible in-flight model retry cost. For a clean no-repeat-model demonstration, crash only after its completion event is recorded. Model usage accounting should distinguish recorded successful usage from uncertain consumption by interrupted requests.

## 3. AgentCore Runtime and serverless workers

**Conditional — Pre-release.** Temporal Cloud access for AgentCore Runtime workers requires a support ticket or account-team access. A standard worker runs inside a Runtime session and polls Temporal. Serverless deployment requires Worker Versioning; use a named Runtime endpoint pinned to one Runtime version per Worker Deployment Version, not the mutable `DEFAULT` endpoint.

The default Runtime session idle timeout is 15 minutes; Temporal polling does not reset it. It is separate from the worker's idle/drain policy. Runtime compute has an eight-hour maximum lifetime. Durable waits do not require worker compute to stay running, but surviving workflow state belongs in Temporal, not process memory.

Source: [Temporal serverless workers on AgentCore](https://docs.temporal.io/serverless-workers/agentcore).

**Design implication:** the approved local-worker/Temporal-Cloud first stage can proceed while hosted-worker access is arranged. Label the required hosted stage conditional until its gate passes. “No active worker needed during approval” is accurate; “the whole system costs nothing while waiting” is not. Temporal Cloud actions, storage, and other deployed infrastructure can still incur charges. [Temporal Cloud actions](https://docs.temporal.io/evaluate/cloud/actions).

## 4. Gateway → Step Functions contract

**Supported.** Connector `states` exposes pinned state-machine operations. Use Standard `StartExecution`, then `DescribeExecution`; `StartSyncExecution` is Express-only. The gateway calls Step Functions in its own Region under its **Gateway service role**. Scope execution-read permissions as well as the pinned state-machine start permission.

`StartExecution` exposes `input` by default. Explicitly expose optional `name` using `parameterOverrides` with `visible: true` for deterministic execution naming. Input is serialized JSON. Start returns `executionArn` and `startDate`, not completion. MCP results contain serialized API JSON in `result.content[].text`; check `result.isError` before parsing. `DescribeExecution` defaults to `METADATA_ONLY`; request `ALL_DATA` when output is needed. Test the deployed `tools/list` schema rather than guessing it.

Source: [AWS Step Functions connector](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-connector-step-functions.html).

**Supported idempotency boundary:** Standard starts with identical name and input return the original response while that execution is running. A closed execution or different input produces `ExecutionAlreadyExists`; names can be reused after 90 days. Express starts are not idempotent. [StartExecution API](https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html).

**Recommended adapter behavior:** derive the execution name from an immutable remediation operation ID. Preserve canonical input bytes across retries. On an ambiguous response or name conflict, reconcile the known execution ARN and verify the operation identity/input before treating it as the same run; never generate a fresh name automatically. Independently enforce idempotency in the simulated restart target.

`DescribeExecution` is eventually consistent. Status can be `RUNNING`, `SUCCEEDED`, `FAILED`, `TIMED_OUT`, `ABORTED`, or `PENDING_REDRIVE`; output is populated only on success. [DescribeExecution API](https://docs.aws.amazon.com/step-functions/latest/apireference/API_DescribeExecution.html).

**Recommended polling:** each status request is a short Activity separated by a durable Temporal timer. Treat start acceptance as `REMEDIATION_RUNNING`; require successful execution plus fresh service health evidence before `RESOLVED`. Bound polling time; transient missing/stale status merits bounded reconciliation. Failed, timed-out, aborted, or pending-redrive outcomes require explicit handling, never assumed success. Avoid a long-lived Activity that sleeps while polling.

## 5. Approval enforcement and AgentCore Policy

**Supported:** Policy can enforce principal/tool/input conditions outside the model. Default-deny and explicit-forbid precedence apply. Use `ENFORCE` for enforcement; `LOG_ONLY` is observation. [Policy getting started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-getting-started.html).

**Conditional:** current documentation also supports session-history policies in Dogwood (Cedar-compatible), including prior approval events. These “temporal policies” are an AgentCore authorization feature, distinct from Temporal workflows. They need a policy session header, appropriate workload-token permissions/propagation, and same-account/Region AgentCore hops. Mumbai and N. Virginia are documented as supported. History-dependent windows are limited to 24 hours; changing temporal policies invalidates existing policy sessions. [AgentCore temporal policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html).

**Unverified:** a generic caller-supplied `approvalToken` field is not documented as automatically validating human authorization. A nonempty token/boolean is not proof. Also, the native Step Functions connector takes `input` as a JSON string; do not assume nested business fields become directly addressable structured Policy attributes.

**Design recommendation:** authenticated approval API, immutable proposal hash/version, approver identity, expiry, and one-use authorization record; the runbook validates the record against operation and target before any mutation. Approval authority must be outside the model's permissions. Gateway Policy is defense in depth; richer per-operation policy can use a typed wrapper/verified approval action after a schema and session spike. Keep credentials and bearer capabilities out of workflow history and model prompts.

## 6. Identity boundary

**Supported:** AgentCore Identity provides outbound OAuth/API-key credentials for supported resource providers. Runtime inbound authentication and resource authorization are separate. Derive end-user identity from verified authentication; caller-supplied user IDs are not independently verified. [Runtime inbound/outbound authentication](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html).

**Design implication:** use AWS IAM roles for AWS service calls and the native Step Functions connector. The required AgentCore Identity demonstration uses the concrete diagnostics path below. Do not describe every AWS credential as originating in the Identity token vault. Resolve credentials within the Gateway/Activity boundary, without returning them to the workflow or trace payloads.

### Verified minimal Identity path: diagnostics OpenAPI target

**Supported:** an OpenAPI Gateway target can use an API-key credential provider configured in AgentCore Identity in the same account and Region as the Gateway. This is real Identity integration, not merely an IAM role renamed as Identity. [OpenAPI target authorization](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-schema-openapi.html).

Recommended concrete implementation:

1. Host a dedicated HTTPS diagnostics API with only `check_health`, `get_metrics`, and `query_logs` routes for the demo service. Define its OpenAPI schema without credential values or key inputs in model-visible tool arguments.
2. Generate a random service credential during provisioning, pass it through a secure SDK/secret-input path, and register it in an AgentCore Identity API-key provider. Keep only the returned provider ARN in infrastructure references. Identity supports both service-managed secret storage and a reference to an existing Secrets Manager secret. [Identity credential providers](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-providers.html), [CreateApiKeyCredentialProvider](https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_CreateApiKeyCredentialProvider.html).
3. Configure the OpenAPI target with the following shape. This contains a placeholder ARN, never an actual credential:

```json
{
  "credentialProviderConfigurations": [
    {
      "credentialProviderType": "API_KEY",
      "credentialProvider": {
        "apiKeyCredentialProvider": {
          "providerArn": "<returned-identity-api-key-provider-arn>",
          "credentialLocation": "HEADER",
          "credentialParameterName": "X-SRE-Diagnostics-Key"
        }
      }
    }
  ]
}
```

The header name is an application choice; `credentialPrefix` is optional and omitted here. Use the actual provider ARN returned by the API rather than constructing one from inconsistent example ARN prefixes. [Gateway target credential configuration](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-building-adding-targets-authorization.html).

4. Grant the Gateway service role narrowly scoped workload-token retrieval, `bedrock-agentcore:GetResourceApiKey`, and the associated Secrets Manager read permission required by the documented API-key setup. Gateway retrieves the Identity-held key and injects it into the outbound request; the worker and LLM receive diagnostic results, not the key. [Gateway outbound authorization](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-outbound-auth.html).
5. Enforce that header at the diagnostics API authentication boundary. For an API Gateway-hosted endpoint, use a dedicated Lambda authorizer validating the injected secret and limiting access to these read-only routes. Do not treat an API Gateway usage-plan key as authentication; AWS explicitly distinguishes usage plans from authorization. [API Gateway API-key guidance](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-api-usage-plans.html).

**Acceptance evidence:** a real authenticated MCP diagnostics call succeeds with Identity injection; direct calls without the header or with an invalid key fail; mismatched provider configuration fails closed in a dedicated negative test; schema, prompts, history, and logs contain no key value. Demonstrate rotation/revocation using the provider and downstream validator without exposing the credential. Do not assume each call causes an uncached vault fetch; the observable contract is provider-backed outbound authentication. A configured but unused provider does not satisfy coverage.

**Scope boundary:** this service credential authenticates the gateway workload to the diagnostics API, not a human approver, and grants no restart authority. The Step Functions connector continues to use its Gateway IAM role.

## 7. Memory and Code Interpreter

**Supported:** Memory stores interaction events and asynchronously extracts long-term records; semantic retrieval uses `RetrieveMemoryRecords`. [Memory types](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-types.html).

**Design implication:** pre-seed and verify retrievable historical incidents before the demo. Treat returned incidents as context/evidence, not an approval source or workflow checkpoint. A Memory outage should degrade diagnosis context rather than erase incident state. Write resolved incident summaries asynchronously with bounded retries.

**Supported:** Code Interpreter uses isolated sessions; default session timeout is 15 minutes and configurable up to eight hours. State exists within the session lifetime. Explicitly stop sessions after use. [Session characteristics](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-session-characteristics.html), [resource/session management](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-resource-session-management.html).

**Design implication:** send sanitized metric windows and an approved bounded analysis script, receive compact statistics, persist required evidence outside ephemeral sessions, and rerun analysis safely if the session expires. It needs no remediation credentials.

## 8. Live retry tuning and visibility

**Conditional — Public Preview:** Activity Operations are exposed via CLI, UI, and gRPC operational APIs. Capability-check the namespace and pinned CLI before rehearsal. [Activity Operations](https://docs.temporal.io/activity-operations).

Update Options changes supported retry/timeouts/task-queue settings. For a waiting retry, new configuration applies immediately and regenerates its retry timer. For an in-flight attempt, settings apply to the next execution. Completed Activities cannot be updated. The operation does **not** create a workflow Event History event. [Update Activity Options](https://docs.temporal.io/activity-operations/update-options).

Intermediate Activity retries also do not each create separate history events; attempt count is recorded on the eventual start event. [Temporal Cloud action accounting](https://docs.temporal.io/evaluate/cloud/actions).

**Demo correction:** use pending Activity state plus per-attempt application logs/metrics to show backoff and tuning. Keep a separate operator audit record for the change. Do not promise that Event History alone displays every retry and options update.

## 9. Observability setup

**Supported:** CloudWatch Transaction Search must be enabled to view AgentCore spans/traces. Current AgentCore CLI deployment can enable it automatically unless configured otherwise. Non-Runtime agents require suitable OpenTelemetry/ADOT instrumentation and trace export. Initial Transaction Search availability may take ten minutes. [AgentCore Observability getting started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html).

**Design implication:** configure this deliberately, verify a complete rehearsal trace, and correlate `incident_id`, Temporal workflow/run/activity IDs, remediation operation ID, and Step Functions execution ARN. Separate business identifiers from ephemeral runtime-session IDs. Redact tool data, logs, prompts, and token material before exporting. A missing trace does not mean a workflow step never executed; Temporal history remains the execution evidence.

## 10. Account readiness remains unverified here

This research establishes public integration contracts. It does not establish this account's model entitlement/invocation, AgentCore endpoint authorization, selected Region quotas, Temporal Cloud namespace connectivity, preview enrollment, or actual trace ingestion. Earlier chat claims are not reproduced verification evidence. Keep these as explicit preflight gates before building/deploying the corresponding integration.

## 11. Mandatory staged completion gates

These gates reflect the user's full-coverage requirement. Stages allow sequencing; mock adapters, architecture slides, or local fallback behavior do not count as delivery of a named cloud feature.

| Stage | Required coverage | Completion evidence |
| --- | --- | --- |
| Durable first slice | Temporal Cloud, Strands `TemporalAgent`, Claude on Bedrock, workflows/Activities, timeouts/retries, Event History/replay, approval Signal or Update, durable escalation timer | Real incident run against the dedicated demo service; completed calls reused after local-worker kill; observed transient retry; approval and timeout races tested; no unauthorized restart |
| Governed AWS integrations | AgentCore Gateway, native Step Functions Standard connector, AgentCore Identity, Memory, Code Interpreter, Policy, Observability | Actual connector start/status/output and post-restart health; provider-backed diagnostics calls; retrieved seeded incident; Code Interpreter result; Policy in **ENFORCE** with both allowed and denied tool calls; correlated CloudWatch trace and Temporal history |
| Operational control | Live Update Activity Options | Change a pending diagnostic Activity's retry interval in the running Temporal Cloud workflow; verify next scheduling behavior from pending Activity state and timestamped attempt evidence; preserve operator audit |
| Hosted worker | AgentCore Runtime, Temporal Serverless Workers, worker versioning and cloud-native infrastructure | Pre-release access granted; named immutable Runtime endpoint registered to Worker Deployment Version; actual hosted workflow execution; no-worker approval wait followed by successful wake-up/resumption and trace correlation |

Policy delivery does not require adopting every optional Dogwood feature: enforced identity/tool boundaries plus authoritative runbook approval validation satisfy the designed defense layers. If the specific teaching claim is that **Policy itself** checks approval state, separately implement and test a trusted approval action/session or typed wrapper; ordinary role restrictions alone do not prove that stronger claim.

Live Activity Operations and hosted worker access must be capability-tested early. If unavailable, record the affected gate as **blocked/not delivered** while completing independent stages. The full project is not complete until all gates have evidence or the user explicitly changes scope.
