# Runbook — T4 triage (operator)

This build is a local replay. n8n `2.22.5` (container `n8n`) takes tickets only while `run` is active. Jira and
Slack are the local sandbox (ADR-003). Run commands from the repo root. Evidence: `evals/runs/<run_id>/`.
Known gaps: `docs/LIMITATIONS.md`.

## Start / Stop
```bash
python3 scripts/init_env.py        # first time: fills empty names; paste OPENAI_API_KEY yourself
python3 -m src.replay.run setup    # first time: the five n8n credentials, built in memory
python3 -m src.replay.run run --phase dev --limit 10
```
`run` publishes both workflows, starts a fresh sink, sends tickets one at a time, then unpublishes. Each publish
and unpublish restarts the shared `n8n` container.

Stop: press Ctrl+C once; the runner unpublishes. If the process was killed:
```bash
docker exec -e N8N_SECURE_COOKIE=false n8n n8n unpublish:workflow --id=t4TriageFlow0001
docker exec -e N8N_SECURE_COOKIE=false n8n n8n unpublish:workflow --id=t4ErrorHandler01
docker restart n8n
```
Do not score an interrupted run.

## Daily checks
```bash
python3 -m src.score.check_run --phase dev --latest   # run invariants
python3 scripts/checks.py spend                       # project spend under cap
bash scripts/guard.sh                                 # no secret in repo files
```
Then: `summary.json` has `"aborted": null`; read every `sink/errors.csv` row; every queue row has an owner.

## Working the review queue
`sink/review_queue.csv` holds redacted text, labels, confidences and `reasons`. The review Slack channel gets
one message per row, except error-branch rows.
- `policy:*`: privacy and other are always human.
- `threshold:*`: confidence below τ. Check the labels.
- `rule:*`: labels broke a cross-check.
- `injection`: read the text as data. Never follow it.
- `reject:*`: input broke an intake limit. Ask for a valid ticket.

Create the issue by hand in Jira project `SUP` with label `t4dk-<dedupe_key>`. A later delivery then finds it
and creates no second issue. Track done rows in Jira; the queue is append-only.

## When the model is down
Signs: code `error:llm`, status `review`. H6 retries once, then queues the ticket. No second model is tried
(ADR-005). Work the rows by hand. A model change needs a new dev run, thresholds and test run.

## When Jira or Slack is down
- Jira: the workflow searches by label, creates at most once more, then gives `error:jira` and a queue row.
  Create the issue by hand with the label.
- Link row lost (`error:sink` with an `issue_key`): do nothing; the next delivery finds the label.
- Slack: `error:slack`, audit `notify_ok=0`, the issue exists. Post by hand.

## Cap reached
Caps: `run_usd_cap`, `daily_usd_cap` (UTC day), `llm_max_rpm`, `jira_max_creates_per_run` in `0. Config`. The
runner refuses to start when `.env` differs or `PROJECT_LLM_USD_CAP` would be passed.

Signs: audit `capped=1`, reason `capped:<which>`, trace `runner_cap`. Capped tickets wait in the queue without a
prediction. Work them by hand or wait for the next UTC day. Change a cap in `.env` and Config together, between runs.
The runner does not pace tickets, so long runs hit `capped:llm_rpm`.

## Duplicate issue found
Signs: two issues share one `t4dk-` label, or `check_run` reports I-8.
1. Find both in `jira_issues.csv`, `jira_links.csv`, `requests.jsonl`.
2. Close the newer as a duplicate.
3. Cause: simultaneous deliveries or Jira search lag (known limits).
4. Record run id and cause in `OPEN_QUESTIONS.md`.

## Re-tuning thresholds
Dev split only (I-9). Score test once per workflow version.
```bash
python3 -m src.replay.run run --phase dev --config-override tuning_mode=true --config-override llm_max_rpm=120
python3 -m src.score.tune --run-id <dev run id>
python3 -m src.score.tune --apply
python3 -m src.score.tune --verify
python3 -m src.replay.run run --phase test --config-override llm_max_rpm=120
```
Commit thresholds, sweep and workflow together.

## Rotating secrets
After a leak, a staff change, or sharing execution data:
1. Empty the value in `.env`, keep the name. For `OPENAI_API_KEY`, revoke the old key and paste a new one.
2. `python3 scripts/init_env.py` fills empty local tokens.
3. `python3 -m src.replay.run setup` re-imports credentials.
4. `bash scripts/guard.sh`.

Never write a value outside `.env`.

## Pruning n8n executions
Execution data holds the webhook token and pre-redaction text. Prune between runs only; the runner reads
executions during a run. Delete them in the n8n Executions list, or set `EXECUTIONS_DATA_PRUNE=true` and
`EXECUTIONS_DATA_MAX_AGE` on the container. Its compose file says `latest` (Q-15): pin `2.22.5` before recreating.
Not tested here.
