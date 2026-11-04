# Webinar walkthrough: from slow search to verified recovery

## Before you share your screen

1. Start the AWS demo session using [AWS_DEMO.md](AWS_DEMO.md) if it is not already running. The application is supervised on EC2. Check that the temporary instance and its scheduled termination time will cover your presentation.
2. Open the public DemoShop storefront, Mission Control, and Presenter controls in separate tabs. Get the current public hostname from `.data/aws-demo-instance.json`, or use the links in your chat if the instance has not changed.
3. Sign in to Mission Control and Presenter controls with the private browser login from `.data/aws-demo-web-login.txt`. Enter your presenter token in both pages. On Mission Control click **View monitoring**; on Presenter controls click **Connect / refresh**. Do this privately, before screen sharing. Do not show either credential on screen.
4. Confirm Mission Control shows **Probe: Running**, **Telemetry: Receiving**, and at least five recent correct, fast samples for the current configuration. Confirm Presenter controls say the configuration is normal. If the probe is stopped or telemetry is stale, restart the session and recheck before injecting a fault.
5. Search `backpack` once in DemoShop and verify that **Trail Backpack** and **Commuter Backpack** appear. Keep the three tabs ready.

## The story

**Opening:** “Let’s look at what an incident feels like to a customer, and then see how a workflow can help an SRE investigate and safely restore the service.”

### 1. Show a healthy customer experience

- In DemoShop, search `backpack` and point to the two products and **Last request** time.
- Say: “This is a real catalog request. I’ll use this same search before and after the incident so we can judge the customer experience.”

### 2. Introduce the fault

- In Presenter controls, click **Inject latency**. Explain that this intentionally adds a four-second server-side delay for the demonstration.
- Return to DemoShop and run the same `backpack` search. Wait for the results and point to the new **Last request** time.
- Say: “The products still return correctly, but the customer now waits roughly four extra seconds. The delay is happening in the backend.”

### 3. Show measured detection

- Switch to Mission Control. Wait for **Catalog search latency** under **Alerts**. The independent probe runs about every five seconds; the alert requires at least three correct requests over two seconds in its latest five-sample window. Timing depends on requests and the network.
- Point out the recent probe measurements. Use **View CloudWatch alarms** to show the separate AWS alarm, which evaluates the same measured latency with a different rule and may update at a different time.
- Say: “This alert comes from measured requests, rather than a button changing a dashboard status.”

### 4. Investigate and keep a human in control

- Click **Investigate with SRE**. Wait for **WAITING APPROVAL** and the **Proposed configuration restore**.
- Point to the AgentCore analysis, model-review message, and the current and proposed configuration versions. Explain that the workflow gathers the measured facts; the configured model reviews those facts through Strands (Groq-hosted GPT-OSS 20B when configured, otherwise Qwen on EC2); Temporal Cloud coordinates the workflow.
- Say: “The proposed action is to restore a previously verified configuration. The demo waits for a person to review and approve that specific proposal.”
- Click **Approve restore**. The proposal is bound to the incident and configuration; this is a demo approval control, not a production identity system.

### 5. Prove recovery in the application

- Return to DemoShop and repeat the same `backpack` search. Confirm the same two products return and compare **Last request** with the slow request.
- Return to Mission Control. Show **VERIFYING**, then **RESOLVED** after five new correct, fast probe requests. This takes time; do not promise an exact number of seconds until rehearsed.
- Say: “We don’t call this recovered just because the action ran. We check new requests, and we also return to the same customer interaction.”

### Closing

“Today’s demo shows a real application slowdown, measured detection, a model-assisted investigation, human approval, and independently verified recovery. Temporal Cloud runs the workflow; the application and restore run on a temporary AWS EC2 instance, while Groq hosts the model when Groq mode is enabled.”

## If something goes wrong

- **Probe stopped or telemetry stale:** restart the AWS demo session and wait for five correct fast baseline samples. Avoid injecting before the baseline exists.
- **No alert:** check that the latency fault is active and that probe requests are fresh; wait for the five-observation window.
- **Manual review or model failure:** explain that the workflow stopped for manual review. Do not claim an automated fix.
- **Fault remains active:** use **Emergency reset** in Presenter controls to return the app to normal. Clearly label it a manual reset, not agent recovery.
- **Public page unavailable:** the supervised application may be restarting, or the temporary EC2 instance may have terminated. Follow [AWS_DEMO.md](AWS_DEMO.md).

Bedrock inference is not connected. AgentCore Code Interpreter analyzes the measured latency samples; AgentCore Runtime and the other proposed AgentCore components are not connected. CloudWatch receives the real probe metrics and has a separate latency alarm; that alarm does not start the workflow. The configured model reviews workflow-gathered evidence; it does not independently select diagnostic tools. Browser timings include network and can differ from the EC2 probe timings.
