# AWS-hosted demo

The temporary EC2 instance in us-east-1 runs DemoShop, its backend fault and probe, SQLite, the Temporal worker, and the optional local Qwen model. Temporal Cloud coordinates the workflow. Strands asks the configured model to review facts gathered by a deterministic activity: Groq-hosted `openai/gpt-oss-20b` when a Groq key is supplied, or local Qwen when it is not. Synthetic incident facts are sent to Groq in Groq mode. AgentCore Code Interpreter analyzes five measured latencies, and an exporter sends measured latency and correctness to CloudWatch. A separate CloudWatch alarm evaluates latency; the in-app alert starts no investigation automatically. Bedrock inference and an AWS runbook are not connected. This is a demonstration and not a production deployment.

## Public access

The temporary public HTTPS storefront address is recorded in `.data/aws-demo-instance.json` as `public_host`. It uses a temporary `sslip.io` hostname and a Let's Encrypt certificate. The address stops working when the instance terminates or its IP changes.

The storefront and catalog endpoints are public. Mission Control, presenter pages, and presenter APIs require the browser login in `.data/aws-demo-web-login.txt` (local file permissions 0600), followed by the presenter token inside the application. Share neither control credential publicly. The API and model listen only on EC2 loopback behind the HTTPS proxy.

## Session lifetime

A supervisor on EC2 runs the application independently of the presenter's Mac and restarts it if a demo component stops. Connection credentials are sent over SSH and remain in the supervisor's process memory; the Temporal API key is not stored in a deployment file. The probe has a bounded six-hour runtime and the supervisor restarts the demo if the probe stops.

The CloudWatch alarm is scheduled for deletion at 10:04 p.m. India time on November 4, 2026; the deletion schedule removes itself. IAM resources remain until the teardown script is run. The EC2 operating-system shutdown is currently scheduled for **10:05 p.m. India time on November 4, 2026**. The instance is configured to terminate and delete its root volume on shutdown. This is a best-effort limit, not a spending cap; monitor AWS and Temporal charges. The public demo, database, and files on the instance disappear when it terminates. Temporal Cloud retains workflow history according to its own retention settings.

If the supervisor has stopped while the instance still exists, start it from this project folder:

```sh
.venv-temporal-demo/bin/python scripts/aws/start_daemon.py
```

Enter the Temporal namespace, existing API key, and the presenter token at the private prompts. Enter a Groq key at its hidden prompt to use GPT-OSS 20B, or leave it blank to use local Qwen. The supervisor holds the supplied keys in memory. If your public IP address has changed, the EC2 security group must allow your current IP for SSH. The temporary credentials and SSH private key in `.data/` must remain private.

To terminate this project's recorded temporary EC2 instance and remove its access resources early, run:

```sh
.venv-temporal-demo/bin/python scripts/aws/terminate.py --yes
```

Termination destroys the EC2 demo database and files.
