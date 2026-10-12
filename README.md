# Support Ticket Triage & Routing on n8n

> **Status: plan only — not built.** No workflow, data or results exist yet. Numbers below will come from replay runs.

For a Head of Support at a 20–200 person SaaS company: every new ticket is read, classified by category, priority
and urgency, and either filed in Jira and posted to Slack, or held for a person to review. Nothing is guessed silently.

What it will show, on 200 labelled synthetic tickets:

- accuracy per category and priority, with confusion matrices
- per-category confidence cut-offs, and the share of tickets left for a human
- personal data removed before the model, Jira or Slack sees it
- the same ticket sent twice never creates two Jira issues
- cost per ticket and per 1,000 tickets
- 20 named attacks (prompt injection, data leakage, oversized input, cost spikes, duplicate writes) and their results

Runs on self-hosted n8n 2.22.5, OpenAI `gpt-4o-mini`, and a local Jira/Slack-compatible sandbox.
All tickets are synthetic.

Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Plan: [GOALS.md](GOALS.md) ·
Security: [docs/SECURITY_CONTROLS.md](docs/SECURITY_CONTROLS.md)
