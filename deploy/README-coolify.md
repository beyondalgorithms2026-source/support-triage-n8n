# Running the T4 triage workflow on Coolify (n8n)

Branch `deploy/coolify` (made from `main`). This repo has no web app to build, so there is **no Dockerfile**. The deployable part is two n8n workflow files. You run n8n itself as a Coolify one-click service and import them.

## 1. Read this first: the workflow is not "import and go"

- The workflow was built to run against a **local test sandbox**, not real Jira and Slack. Its JSON holds placeholders that the test tool fills in memory when it imports (`python3 -m src.replay.run`). A plain import in the n8n screen keeps the placeholders and the calls fail.
- The workflow also calls a small helper web service, the **sink** (`src/sink/server.py`), for the ledger, duplicate check, rate counts and review queue (nodes `H2`, `H5`, `H7`, `H11`, `H13`, `H15`, `E`, `H16`). That helper is a Python script with no Dockerfile and no hosting set-up. Without it, the nodes that use `__SINK_BASE_URL__` fail.
- Because of both points, an online "live" triage demo needs extra work (host the sink, replace the placeholders). Until then the safe use of this branch is to bring n8n up and import the files for a look. Nothing here calls a real Jira or Slack by itself.

## 2. Coolify fields (n8n one-click service)

| Field | Value |
|---|---|
| Resource type | Service > n8n, the **SQLite** variant (not the Postgres one) |
| Domain | https://triage.spanfold.com |
| Persistent storage | the volume the template creates for `/home/node/.n8n` (holds the database and credentials) |
| Memory limit | 512 MB |
| Replicas | 1 |

DNS: add an A record `triage` pointing at the server.

## 3. Environment variable names (type them in Coolify)

| Name | What it is | Notes |
|---|---|---|
| `N8N_ENCRYPTION_KEY` | key that encrypts the credentials inside n8n | **BA must create and store it** (password manager). Set it before the first start and never change it: losing or changing it makes every saved credential unreadable. |
| `N8N_HOST` | `triage.spanfold.com` | normally filled in by the template |
| `N8N_PROTOCOL` | `https` | |
| `WEBHOOK_URL` | `https://triage.spanfold.com/` | so webhook addresses show the public domain |
| `GENERIC_TIMEZONE` | your time zone | |

Names the T4 project itself uses (from `.env.example`; only for the replay tool, **not** for n8n): `T4_TARGET`, `N8N_BASE_URL`, `N8N_CONTAINER`, `OPENAI_API_KEY`, `T4_WEBHOOK_TOKEN`, `T4_WEBHOOK_PATH`, `SINK_TOKEN`, `SINK_PORT`, `SINK_BASE_URL`, `JIRA_BASE_URL`, `JIRA_SANDBOX_EMAIL`, `JIRA_SANDBOX_API_TOKEN`, `JIRA_PROJECT_KEY`, `SLACK_BASE_URL`, `SLACK_SANDBOX_BOT_TOKEN`, `SLACK_CHANNEL_TRIAGE`, `SLACK_CHANNEL_REVIEW`, `LLM_PRICE_IN_PER_MTOK`, `LLM_PRICE_OUT_PER_MTOK`, `RUN_USD_CAP`, `DAILY_USD_CAP`, `PROJECT_LLM_USD_CAP`. The workflow files use **no** `$env` values on purpose.

## 4. Files to import

| File | Name inside n8n | Import order |
|---|---|---|
| `workflows/t4-error-handler.json` | T4 triage — error handler (4 nodes) | first |
| `workflows/t4-triage.json` | T4 triage — full controls (47 nodes) | second (its settings name the error workflow by id `t4ErrorHandler01`; check that the imported handler has that id) |

Both are exported inactive. Keep them inactive until the placeholders and credentials below are done.

Placeholders to replace before activating (field = where they sit):

| Placeholder | Replace with | Where |
|---|---|---|
| `__WEBHOOK_PATH__` | a long random path you choose | node `0. Webhook — Ticket Intake`, parameter `path` |
| `__SINK_BASE_URL__` | address of the hosted sink | 12 places in the file (ledger, dedupe, rate, review, audit nodes) |
| `__JIRA_BASE_URL__` | your Jira sandbox address | 4 nodes `H11 Jira Search`, `H12 Jira Create`, `H12r Reconcile`, `H12b Jira Create (retry once)` |
| `__SLACK_BASE_URL__` | Slack API address | nodes `H14`, `H15s` |

## 5. Credentials to create in n8n (types and names only)

| Credential name | Type | Used by |
|---|---|---|
| `t4-webhook-auth` | Header Auth | the intake webhook |
| `t4-sink-auth` | Header Auth | every call to the sink, and the error handler |
| `t4-llm` | Header Auth (bearer key for the model API) | node `H6 LLM Classify` |
| `t4-jira` | Basic Auth | the four Jira nodes |
| `t4-slack` | Header Auth (bot token) | the two Slack nodes |

Create them with exactly these names: the nodes find them by name. Type the secret values in the n8n screen only.

## 6. Webhook paths

- Intake: `POST https://triage.spanfold.com/webhook/<your path>` (the value you put in place of `__WEBHOOK_PATH__`). It needs the Header Auth credential above. The test path form `/webhook-test/<path>` only works while you press "Listen for test event".
- The workflow answers with the last node's reply (`responseMode: lastNode`).
- Error workflow: no public path (error trigger).

## 7. Flags found in the workflow JSON (paths and field names only, no values)

| File | Path | Finding |
|---|---|---|
| `workflows/t4-triage.json` | `nodes[15].parameters.url` (node `H6 LLM Classify`) | A hard-coded model API host (`api.openai.com`, `/v1/chat/completions`). It is the only real address in the file. It is a host name, not a secret. |
| `workflows/t4-triage.json` | `nodes[0].parameters.path` | Placeholder `__WEBHOOK_PATH__`, not a real path. |
| both files | `nodes[*].credentials` | Credentials are referenced by name only. |

No token, key or password was found in either file: a field-name scan (`token`, `secret`, `password`, `api key`, `authorization`, `bearer`) and a pattern scan for token-shaped text both came back empty. The scan was a script, so this is a check for obvious cases, not a security audit.

Not in the workflow files but in this repo: a local `.env` file exists (not opened, git-ignored) and `logs/` is in the working tree. Check `logs/` holds nothing sensitive before this repo is ever published.

## 8. What BA must do

1. Create `N8N_ENCRYPTION_KEY` and store it safely before the first start.
2. Add the `triage` A record, then deploy the Coolify n8n service (SQLite variant).
3. Create the n8n owner account and the five credentials above.
4. Decide whether the live demo is wanted. If yes, the sink needs a host and the placeholders need real addresses.
5. Import the two workflow files (error handler first), fill the placeholders, then activate.
