## ADR-004: Redact PII before the model and before every outbound write
Status: Proposed (architecture session; human acceptance pending)
Date: 2026-10-12
Decision:
- H3 Redact runs before H6 and replaces emails, phones, Luhn-valid card numbers, IBANs, US SSN-format numbers, IPv4
  addresses, URLs with query strings, and the sender's display name with typed placeholders (`[EMAIL_1]`, …).
- After H3 the raw text is dropped from the n8n item. Model, Jira, Slack, review queue and audit get redacted text or
  derived labels only (I-4). Audit stores counts per PII type, never values.
- One algorithm, two implementations: `src/common/redact.py` (reference + tests) and `src/js/redact.js` (embedded in
  H3). A parity test runs the JS under `node` on shared vectors.
- Redaction failure fails closed: no model call, ticket to review with reason `redact_error`.
Reason:
- The buyer's customers' personal data should not go to a model provider or into Jira descriptions that a wider team
  can read. Redacting at intake is one control point instead of many.
- Category, priority and urgency do not depend on the literal email or card number.
Consequences:
- Reviewers see redacted text in Jira and the queue; the original stays in the source system (inbox / helpdesk),
  referenced by `ticket_ref`.
- Pattern-based redaction misses free-text names, addresses and account numbers. `pii_leak` measures only planted
  values. Stated as residual risk.
- A placeholder can change meaning slightly ("[PHONE_1] keeps calling me"); measured indirectly by model metrics.
