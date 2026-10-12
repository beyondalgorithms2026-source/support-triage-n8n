## ADR-002: The human review queue is a designed outcome, not an error
Status: Proposed (architecture session; human acceptance pending)
Date: 2026-10-12
Decision:
- `review` is a first-class terminal status with reasons (low confidence, rule conflict, injection signal, policy
  class, model error, cap). It writes a `review_queue` row and one Slack message to the review channel.
- `privacy` and `other` always go to review (policy, not confidence). Any future customer-facing action (auto-reply,
  status email) must pass through review first.
- "% routed to human" is a reported metric with a target (HARNESS_SPEC §2), not a failure code. Failures are only the
  12 codes; sending a ticket to review is never one of them.
- On any internal failure (LLM error, sink error, Jira unavailable after reconcile) the ticket goes to review.
Reason:
- For a Head of Support the cost of a wrong automatic route (lost P1, misfiled privacy request) is far higher than a
  reviewer spending 30 seconds. Fail-closed to a person is the safe default.
- Making review measurable stops the build from "improving" by hiding uncertainty.
Consequences:
- Early numbers will show a high % to human (everything is review until G9 tunes thresholds).
- The queue has no approval tooling in this build: a reviewer acts in Jira by hand. The approval webhook is cut
  (GOALS.md § Cut) and listed as a limitation.
