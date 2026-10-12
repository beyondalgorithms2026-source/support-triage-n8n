## ADR-006: Idempotent Jira writes — two keys, Jira label as second source of truth, reconcile before retry
Status: Proposed (architecture session; human acceptance pending)
Date: 2026-10-12
Decision:
- `dedupe_key` = sha256(source | source_message_id)[:20]; `content_sha256` over normalised sender + subject + body.
- Order (ARCHITECTURE §8): sink `jira_links` lookup → content lookup in audit → Jira search on label
  `t4dk-<dedupe_key>` → create with that label → on create error search again (reconcile) and create at most once
  more → append `jira_links` row (commit marker).
- The Jira create node has `retryOnFail: false`; n8n never blind-retries a create.
- Duplicate checks run before redaction cost and model spend: replays cost $0 in model calls.
Reason:
- Webhooks and email are at-least-once. A lost response after Jira committed is the classic duplicate-issue cause;
  only a lookup in Jira itself catches it.
- T2 showed retry settings on a write node duplicate rows (T2 B-1). Reconcile-then-retry fixes that class of bug.
Consequences:
- Lookup-then-create is not atomic; concurrent deliveries can both create. Real Jira search has index lag. Both are
  measured where possible (SEC-17) and stated as residual risk.
- Every issue carries a machine label; the buyer's Jira shows `t4dk-…` labels.
- A follow-up email with different wording is a new ticket (no semantic dedupe).
