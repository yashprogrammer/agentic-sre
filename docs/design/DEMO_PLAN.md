# Demo plan: feel the application slow down, then feel it recover

Status: design and implementation plan. No application behavior or timings below have been measured yet. The latency values are rehearsal targets.

## 1. Audience experience

The central story is **application → measured alert → agent investigation → human approval → actual recovery → application again**.

Open a small storefront, **DemoShop**, and search for a backpack. The product list normally appears promptly. Inject a controlled slow-dependency configuration and repeat the search: the browser now waits roughly four seconds for the server response. The audience experiences the delay before any dashboard or agent explanation.

Switch to Mission Control. It shows an alert generated from actual HTTP measurements, linked request traces, and the affected route. Click **Investigate with SRE**. The agent gathers evidence, correlates the slow requests with the changed dependency configuration, and proposes restoring the known-good configuration.

Approve the exact proposal. The runbook validates authorization and restores that configuration. Fresh probes verify that the same route is responsive and still returns the correct products. Return to DemoShop and perform the same search. The improvement must be visible in the real app and supported by retained request evidence.

Presenter wording: “This is a real application with a deliberately injected dependency fault. The delay is happening on the server. We will let the agent investigate it, approve its proposed configuration restore, and test the same request again.”

The injected fault is controlled; the network calls, waiting, telemetry, workflow, authorization, configuration change, and recovery verification are real. Do not describe this first scenario as repairing a naturally failing production database.

## 2. Screens and controls

| Surface | What the learner sees | What it must actually do |
|---|---|---|
| DemoShop | Product list, search, detail view, natural loading state | Call the real catalog HTTP backend; finish loading only when a response arrives |
| Optional request inspector | Last request elapsed time, status, request ID | Measure this browser request; enable Network tab for corroboration |
| Presenter controls | Inject latency; start/stop probes; emergency reset | Authenticated actions isolated from customer routes; reset is audited and never disguised as agent work |
| Mission Control | Measured alert, samples, “Investigate with SRE”, proposal and approval | Read actual evidence; explicitly trigger the workflow only when requested in manual mode |
| Temporal / CloudWatch | Durable execution, attempt state, trace correlation | Show the same incident/request/action identities as the app and dashboard |

Fault controls belong on a separate presenter surface. They should not clutter the storefront or expose arbitrary delay/target settings to customers. Keep the customer app visually credible and focused on its normal task.

## 3. Scenario specification

| Item | Proposed setting |
|---|---|
| Application | DemoShop product catalog |
| Canonical action | Search `backpack`, then open one known product |
| Normal request | Actual catalog lookup with no injected delay |
| Fault | `catalog_dependency_latency`; add 4,000 ms inside backend dependency adapter |
| Detection | At least 3 of last 5 measured requests exceed 2,000 ms; 5 observations within 60 seconds |
| Traffic | One independent HTTP probe every 5 seconds, concurrency 1, 15-minute maximum run |
| Investigation | Manual “Investigate with SRE” after the alert is shown |
| Proposed fix | Restore the exact verified known-good dependency configuration |
| Approval | Existing authenticated Update, proposal hash/version and expiry checks |
| Recovery gate | Runbook succeeds; 5 new correct requests each below 1,000 ms on the applied configuration |
| Audience proof | Repeat identical browser search; target below 1,500 ms, same products, new network request |

A slow dependency is an example of a latency incident, not a general claim that every latency issue is solved by a rollback. Later scenarios can implement cache failures, connection exhaustion, or real query regressions with their own diagnosis and safe remediation contracts.

## 4. Ten-minute core walkthrough

| Time | Presenter action | Required visible evidence |
|---|---|---|
| 0:00–1:00 | Open DemoShop and perform the canonical search in normal state | Real products and a measured baseline; pre-collected baseline samples clearly dated |
| 1:00–2:00 | Inject the latency profile, repeat search and product detail | Actual several-second wait; Network timing agrees; server fault injection disclosed |
| 2:00–3:00 | Open Mission Control after the detector has enough samples | Same target/route, real slow sample IDs, alert OPEN, investigation not yet running |
| 3:00–5:00 | Click “Investigate with SRE”; walk through evidence and proposal | One workflow, request/config trace correlation, memory/analysis evidence where enabled |
| 5:00–6:30 | Explain the proposal, wait briefly, then approve | Bound human decision; optional 90-second escalation if this slot permits |
| 6:30–8:00 | Show the runbook and independent recovery checks | Applied config version, action receipt, correct fast post-action requests; no premature RESOLVED |
| 8:00–9:30 | Return to the same DemoShop URL and repeat the same search/detail | Fresh HTTP calls are visibly faster and results are correct; improvement is felt |
| 9:30–10:00 | Compare before/after measurements and connect them to workflow/trace | Original slow evidence retained; comparable windows/counts; what changed and who approved |

These are pacing targets, not execution guarantees. Rehearse model latency and the measured detection/verification windows. If a step takes longer, show the actual pending state; do not skip verification or switch silently to canned results.

The core walkthrough prioritizes the customer problem and visible recovery. Use an extended 20-minute walkthrough or separately recorded chapters for the worker kill/replay, live Activity option changes, complete escalation wait, and hosted-worker session replacement. Every named feature remains in the project acceptance scope; compressing the presentation does not remove its implementation gate.

## 5. Implementation milestones

| Milestone | Work | Exit gate |
|---|---|---|
| A — Usable customer application | Build catalog UI, seed products, deploy real request-serving backend, add request IDs/timing | Browser search/details return expected products; actual baseline measured |
| B — Feelable fault | Add versioned dependency config, privileged latency injection, uncached request comparison | Same request becomes slow; UI has no fake delay; app independent of agent processes |
| C — Detection before action | Add bounded probe, trusted request evidence, thresholds, alert store, manual trigger | Measured alert appears; no workflow before click; duplicate clicks start only one |
| D — Durable investigation | Connect Temporal/Strands read tools to real requests/logs/config history | Agent explains evidence and proposes only the bound known-good restore |
| E — Authorized recovery | Extend grant and runbook contract with config version/digest, atomic restore, latency verification | Unapproved/stale action denied; approved action applied once; real application improves |
| F — Audience proof | Add comparison panel, browser acceptance flow, trace links, repeatable reset/seed scripts | Same-browser before/after reproduced; correct data; no fake success when fault persists |
| G — Full feature chapters | Complete Memory, Identity, Code Interpreter, Policy, Observability, Runtime and live retry controls | Existing full-feature gates passed alongside the customer-impact scenario |

Integrate these milestones with [HLD.md](HLD.md)'s staged plan. Build the app and fault before polishing an alert dashboard; otherwise the presentation has no user-visible failure to repair.

## 6. Evidence and rehearsal rules

- Rehearse from the presenter's actual laptop/network and deployment region. Region latency and cold starts can affect targets; record them, and choose stable thresholds before the presentation.
- Record the same route, normalized query, expected result IDs, and measurement scope across baseline, fault, and recovery windows. Capture at least 10 baseline samples before the demo when practical.
- Warm up both normal and faulty paths consistently; do not compare a cold baseline with a warmed recovered path and attribute all improvement to remediation.
- Use browser `no-store` requests and verify a network request occurred. Preserve historical telemetry; show sample counts and median/range rather than presenting a few observations as reliable production p99.
- Keep fault injection active until the authorized recovery. No auto-expiring fault or hidden manual reset may produce the claimed improvement.
- If the agent proposes the wrong action, the runbook is denied, or the request stays slow, show that outcome. It is not a successful demonstration merely because an alert turns green.
- Label recorded fallback footage and rehearsal traces. Never present them as the current live app state.
- Keep probes low-rate and short-lived. Stop probe, worker, and Code Interpreter/Runtime sessions during teardown and account for retained resources separately.

## 7. Acceptance scenarios for implementation

1. A browser search is slow because the backend response is delayed, confirmed by independent request timing.
2. Changing the dashboard display cannot change actual application response time or measured evidence.
3. The detector opens an alert from real measurements, but the agent remains idle until the presenter's trigger.
4. Rejecting/expiring approval leaves the injected fault active and the app slow.
5. A valid grant restores only the approved target/config generation and leaves product data intact.
6. A repeated runbook/Activity delivery returns the same action receipt and does not apply another config change.
7. A successful runbook with a persistently slow route ends UNRESOLVED, not RESOLVED.
8. In-flight requests from the old config remain identified as old; only new requests prove the recovery.
9. A new injected fault invalidates an older action, even if approval was previously granted.
10. The same browser query visibly improves after recovery, and trusted probe evidence agrees without being confused with browser/server timing.
11. Stopping the SRE worker does not stop the customer app; workflow replay can be demonstrated while the app remains slow.
12. Cleanup stops the probe and removes/restores the fault under an explicitly audited teardown operation.

## 8. Scope and cost impact

This expands the original dashboard-oriented simulation into an actual customer-facing application and measured HTTP workload. It adds application/frontend work, request-serving Lambda/API usage, catalog/evidence storage, and bounded probe traffic. It does not require a real database cluster, continuous high-rate load test, or an always-on container fleet.

The earlier approximate demo budget is provisional until this request path is built and rehearsed. Recalculate using actual model tokens, backend duration (including injected delay), request volume, tracing, and session lifetime. The ten-minute on-stage duration does not include preparation, rehearsals, or forgotten background traffic.
