# HANDOFF — start here (static)

Everything a fresh session needs to start at G1. This file does not change per session; the rolling per-session
note is `.ai/HANDOFF.md` (T2 convention). If they disagree, this file and `AGENTS.md` win.

## What T4 is
Support-ticket triage on self-hosted n8n `2.22.5`: webhook in → PII redaction → classify (category, priority,
urgency) with per-class confidence → validate → per-class thresholds → Jira issue (sandbox) + Slack, or human
review queue → audit + cost record. Buyer: Head of Support at a 20–200 person US/EU SaaS company. Synthetic data only.
Design: `docs/ARCHITECTURE.md`. Harness: `docs/HARNESS_SPEC.md`. Security: `docs/SECURITY_CONTROLS.md`.
Decisions: `docs/DECISIONS.md` (ADR-001…007). Plan: `GOALS.md` (G1…G14 = T4-01…T4-14).

## Layout (mirrors T2 `../rescue-diagnostic-t2/`)
```
AGENTS.md CLAUDE.md README.md THIN-LEDGER-v0.1.md GOALS.md HANDOFF.md OPEN_QUESTIONS.md RUN_OVERNIGHT.md overnight.conf
docs/  ARCHITECTURE.md HARNESS_SPEC.md SECURITY_CONTROLS.md DECISIONS.md adr/ (RUNBOOK.md LIMITATIONS.md at G12)
.ai/   STATUS.md (task table owned by scripts/status.py) HANDOFF.md (rolling) ROUTING.md REVIEW.md (closeout card)
specs/t4-triage/spec.md          outcome, scope, project acceptance
scripts/                          preflight, overnight loop, accept, guard, status, morning report, init_env (protected)
src/ tests/ workflows/ evals/     created by goals (ARCHITECTURE §2)
logs/                             overnight logs, gitignored
```

## T2 conventions kept (read `../rescue-diagnostic-t2/` read-only when a goal says "port")
- Thin Ledger: repo is memory; one goal per session; closeout card in `.ai/REVIEW.md`; HANDOFF overwrite.
- Python 3.9 stdlib only; `unittest`; STUB fixtures under `tests/fixtures/` with STUB in name or first line.
- Local append-only sink with row stamps `sink_seq, sink_ts, replay_input_id, replay_pass`; sink-side fault injection.
- n8n driven by `docker exec n8n n8n import:workflow|import:credentials|publish:workflow|unpublish:workflow`;
  executions read from SQLite read-only (T2 `src/replay/run.py` `LocalN8n`). No n8n public API.
- Placeholders substituted in memory at import; credentials built in memory from `.env`; never written to disk.
- run_id `"{phase}-local-{UTC %Y%m%dT%H%M%SZ}-{git short sha}"`; `evals/runs/<run_id>/` with `trace.jsonl`,
  `sink/`, `summary.json`; one `evals/cost_ledger.csv` row per run.
- Findings: numbers trace to run files; residual risk always stated; owner writes trace notes.
- Port numbers: T2 used 8787/8788 → T4 sink/sandbox uses **8790**.

## Env var NAMES (values live only in `.env`; create it with `python3 scripts/init_env.py`)
`T4_TARGET N8N_BASE_URL N8N_CONTAINER OPENAI_API_KEY T4_WEBHOOK_TOKEN T4_WEBHOOK_PATH SINK_TOKEN SINK_PORT
SINK_BASE_URL JIRA_BASE_URL JIRA_SANDBOX_EMAIL JIRA_SANDBOX_API_TOKEN JIRA_PROJECT_KEY SLACK_BASE_URL
SLACK_SANDBOX_BOT_TOKEN SLACK_CHANNEL_TRIAGE SLACK_CHANNEL_REVIEW LLM_PRICE_IN_PER_MTOK LLM_PRICE_OUT_PER_MTOK
RUN_USD_CAP DAILY_USD_CAP PROJECT_LLM_USD_CAP`
n8n credential names (frozen): `t4-llm`, `t4-webhook-auth` (header `X-T4-Token`), `t4-sink-auth` (`X-Sink-Token`),
`t4-jira` (HTTP Basic), `t4-slack` (Bearer).
Overnight settings (non-secret) are in `overnight.conf`, never in `.env`.

## Commands
```bash
python3 -m unittest discover -s tests -t . -v      # all tests
python3 -m compileall -q src tests                 # syntax
bash scripts/accept.sh G<n>                        # goal acceptance (plan | G1..G14 | all)
bash scripts/guard.sh                              # guardrails
python3 scripts/status.py check | next | get G<n> state | set G<n> DONE --evidence "…"
python3 -m src.replay.run setup                    # from G6: credentials + workflow import (in memory)
python3 -m src.replay.run run --phase slice --split dev --limit 10   # from G7: live, capped
python3 -m src.score.score --run-id <id> --out evals/scorecard.csv   # from G10
bash scripts/preflight.sh && bash scripts/overnight.sh               # overnight (RUN_OVERNIGHT.md)
```

## STATUS update rules
- `.ai/STATUS.md` task table is written only by `scripts/status.py` (the overnight loop, or the owner by hand).
- States: TODO → IN_PROGRESS → DONE | BLOCKED (3 failed acceptance attempts) | SKIPPED (dependency blocked).
- DONE requires `bash scripts/accept.sh Gn` = 0 **and** `bash scripts/guard.sh` = 0 in the same tree that is committed.
- A DONE goal is never re-run by the loop. To redo one, the owner sets it back by editing the table by hand.
- The milestone table above the markers is prose; the owner updates it.

## Stop conditions (overnight)
Stop and leave the tree for the morning when: the hard stop (`HARD_STOP_IST`, default 08:00 IST) is near; total
Claude spend would pass `TOTAL_BUDGET_USD`; no goal is eligible; `logs/STOP` exists; a local commit fails.
Per goal: 3 failed acceptance attempts → BLOCKED (work stashed), continue with goals that do not depend on it.
Usage-limit / rate-limit / overloaded errors are not attempts: wait 30 min and retry the same goal.
Inside a goal, never stop to ask: decide, record in `OPEN_QUESTIONS.md`, continue.

## Next
G1 (`T4-01`). Owner gates before G1: `git init` + first commit, `.env` with `OPENAI_API_KEY`, preflight green.
