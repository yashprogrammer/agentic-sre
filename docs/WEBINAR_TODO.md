# Webinar demo: working checklist

Work through these stages together. A checked item means it has been verified, not merely planned. Timing remains to be rehearsed.

## 1. Make the demo ready

- [x] Build the DemoShop catalog, server-side latency injection, measured alert, approval, restore, and recovery verification.
- [x] Connect the incident workflow to Temporal Cloud and use a local Qwen model through Strands to review gathered evidence.
- [x] Rehearse a full recovery: the same search returned correct results before, during, and after the fault; measured times were 5 ms, 4,007 ms, and 6 ms in one run. Five fresh fast requests verified recovery.
- [x] Prepare the [startup and presenter guide](DEMO_TODAY.md) and check the application tests and frontend build.
- [x] Move the application, probe, worker, and Qwen model to a temporary EC2 instance and verify a complete recovery over a private SSH tunnel.
- [ ] Run a fresh pre-demo check on the presentation machine, including network, Temporal connection, AWS-hosted model, browser, and presentation display.
- [ ] Confirm a fallback and reset procedure; rehearse the timing and restart process.
- [ ] Check actual cloud usage against the $3 budget. The launcher does not enforce a spending cap.

**Ready when:** We can start the demo, complete the live flow, and recover or reset safely if a step fails.

## 2. You test, validate, and iterate with me

- [ ] You run the walkthrough and share what is confusing, broken, slow, or missing.
- [ ] Together validate each step: baseline search; four-second server delay; measured alert; investigation; evidence and proposal; approval; same search after restore; five fresh recovery checks.
- [ ] Test rejection or failure handling and ensure no restore occurs without approval.
- [ ] Fix and retest issues, then repeat the complete walkthrough.
- [ ] Record realistic timings and agree on a final demo-ready version.

**Done when:** You are comfortable operating the complete flow and the last full run passes.

## 3. Understand the demo

### High level

- [ ] Explain the customer problem, the incident, and the recovery in everyday language.
- [ ] Draw a simple picture of DemoShop, monitoring, Temporal, the model, human approval, and verification.
- [ ] Explain what is actually running now versus the future architecture described in the HLD/LLD.

### Low level

- [ ] Trace a request and explain how the backend fault creates real latency and how the probe detects it.
- [ ] Trace the Temporal workflow: evidence, local model review, proposal, approval, restore, and fresh verification.
- [ ] Explain state, retries, approval binding, and the current local security boundary.
- [ ] Walk through the relevant code and practice answering technical questions.

**Done when:** You can explain the demo first without code, then follow one incident through its implementation.

## 4. Create the webinar throughline

- [ ] Identify the audience, the takeaway, and the time available.
- [ ] Build a story around customer impact, detection, investigation, human control, and verified recovery.
- [ ] Write the opening, transitions, live-demo narration, and closing in your own voice.
- [ ] Prepare responses for likely questions and a recovery plan if the live demo fails.
- [ ] Rehearse aloud, time the full presentation, and refine it together.

**Done when:** You can deliver a clear story while operating the demo without relying on a word-for-word script.

## 5. Prepare simple explanatory materials

- [ ] Create an audience-friendly one-page overview and architecture diagram.
- [ ] Prepare a presenter cheat sheet with commands, links, timing, and fallback steps.
- [ ] Prepare a concise technical reference and Q&A, including current limitations and future AWS components.
- [ ] Create slides or other webinar materials once the story and audience are agreed.
- [ ] Review the materials for clarity and consistency with the final tested demo.

**Done when:** The materials make the demo easy to follow and accurately describe what is implemented.

## Current position

The AWS rehearsal uses Temporal Cloud for orchestration; DemoShop, its probe and restore, SQLite, and Qwen inference run on a temporary EC2 instance. A separate local fallback remains available. The model reviews workflow-gathered evidence; it does not choose diagnostic tools. AWS Bedrock, AgentCore, and the planned AWS runbook are not connected. The existing design documents describe a broader target architecture and should be read with that distinction in mind.

Next: use the AWS session described in [AWS_DEMO.md](AWS_DEMO.md), then have you perform and validate the walkthrough.
