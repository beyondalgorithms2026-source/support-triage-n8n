## ADR-003: Jira and Slack are a local, contract-compatible sandbox in the sink process
Status: Proposed (architecture session; human acceptance pending)
Date: 2026-10-12
Decision:
- `src/sink/server.py` serves three route groups on one port: sink tables (`X-Sink-Token`), a Jira Cloud REST v3
  subset (`GET /rest/api/3/search/jql`, `POST /rest/api/3/issue`, HTTP Basic), and Slack `POST /api/chat.postMessage`
  (Bearer). Everything append-only; every other path → 403/404 and a request-log row.
- The workflow uses HTTP Request nodes against `__JIRA_BASE_URL__` / `__SLACK_BASE_URL__` with credentials `t4-jira`
  and `t4-slack`, not the n8n Jira/Slack nodes.
- Real Jira Cloud (free site, project `SUP`) and a real Slack workspace are a documented swap: base URL + two
  credentials. Not run in this build.
Reason:
- The overnight build and every replay must run without accounts, tokens or writes to an external system.
- The sandbox can inject the faults that matter for idempotency (lost response after commit, search lag), which a
  real Jira cannot do on demand.
- HTTP nodes show the exact REST contract and least-privilege surface to a buyer; the n8n Jira node also calls
  metadata endpoints at design time that the sandbox would need to fake.
Consequences:
- Results prove the workflow's behaviour against the contract, not against Atlassian's servers. Real-Jira differences
  (rate limits, ADF validation, search index lag timing, custom required fields) are residual risk.
- The sandbox must stay small: it is test equipment, not a Jira clone. New endpoints need an OPEN_QUESTIONS entry.
