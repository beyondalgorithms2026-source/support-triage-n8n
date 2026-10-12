# Run overnight

The loop builds G1…G14 unattended, one goal per Claude Code invocation, commits each passing goal locally, and
writes `MORNING_REPORT.md`. Default hard stop: **08:00 IST**. You need about 15 minutes before bed.

## 1. Mac checklist (you)

- [ ] **Charger plugged in.** `caffeinate -s` only holds the Mac awake on AC power. (At planning time the Mac was on battery.)
- [ ] **Lid open.** A closed lid sleeps the Mac without an external display, whatever `caffeinate` says.
- [ ] System Settings → Battery → Options: **Prevent automatic sleeping on power adapter when the display is off = On**;
      Low Power Mode = Never. Display may sleep; the Mac may not.
- [ ] System Settings → General → Software Update → Automatic updates: turn off "Install macOS updates" tonight (no
      restart at 3 a.m.).
- [ ] Do not log out, do not switch users, leave Wi-Fi on (the loop needs api.anthropic.com and api.openai.com).
- [ ] **Docker Desktop running**; Settings → Resources → Resource Saver **off** (it can pause the VM).
- [ ] **n8n container up on the pinned version:** `docker ps --format '{{.Names}} {{.Image}} {{.Status}}'` shows
      `n8n n8nio/n8n:2.22.5 Up …` (preflight checks image, `n8n --version`, `/healthz`).
- [ ] **Disk**: ≥ 5 GiB free (preflight checks; 45 GiB free at planning time).
- [ ] Close other heavy apps. Leave **Terminal.app** open with the loop's tab (Option A) or just the log tail (Option B).
- [ ] Claude desktop app may update itself overnight; the loop then picks the newest bundled `claude` binary.

## 2. One-time setup (you, ~5 min)

```bash
cd "/Users/Work/Projects/Non RAG Repos/support-triage-t4"
```
```bash
git init -b main && git add -A && git commit -m "T4-00: plan"
```
```bash
python3 scripts/init_env.py
```
Then open `.env` in your editor and paste your OpenAI key after `OPENAI_API_KEY=` (the same key T2 used is fine).
Everything else is filled with random local tokens or defaults. Review the budgets in `overnight.conf` (§5).

## 3. Pre-flight (you, before bed)

```bash
bash scripts/preflight.sh
```
It checks: AC power, lid, Low Power Mode, disk; python3/node/jq/perl/git/docker; Docker daemon, container `n8n` on
`n8nio/n8n:2.22.5`, `n8n --version`, restart policy, `/healthz`, port 8790 free; reachability of api.openai.com and
api.anthropic.com (no key sent); git repo, clean tree, user.email, no remote, `.env` ignored and untracked; every
`.env` name present (names only, never values), key prefix, cap ordering; `overnight.conf` budgets and hours until
the hard stop; the Claude CLI version and every flag the loop uses (from `claude --help`); a small `claude -p`
smoke call (capped at $0.50) to prove login; `accept.sh plan`, unit tests (none before G1), `guard.sh`, next goal. Any FAIL → exit 1.
On success it writes `logs/preflight.ok` (the loop refuses to start without one younger than 3 h).

## 4. Start (Option A: you, in Terminal.app — recommended)

```bash
cd "/Users/Work/Projects/Non RAG Repos/support-triage-t4" && bash scripts/overnight.sh
```
The script re-executes itself under `caffeinate -dimsu`. Leave the window open. Watch with
`tail -f logs/overnight.log` in a second tab if you like.

**Option B (what Claude does in Phase 2):** start it detached so it survives the chat session:
```bash
cd "/Users/Work/Projects/Non RAG Repos/support-triage-t4" && nohup bash scripts/overnight.sh > logs/overnight.console 2>&1 &
```
Then `tail -f logs/overnight.log` in Terminal.app.

**Stop early:** `touch logs/STOP` (finishes the current goal's checks, then writes the morning report), or Ctrl-C in
Option A (the report is still written).

## 5. What runs, exactly

Per goal the loop calls (flags verified against `claude --help`, Claude Code 2.1.295 on this Mac):
```
"$CLAUDE_BIN" -p "<goal prompt>" \
  --output-format json \
  --model opus --fallback-model sonnet --effort high \
  --permission-mode dontAsk --permission-prompts none \
  --settings scripts/claude-overnight-settings.json \
  --max-budget-usd <min(RUN_BUDGET_USD, remaining total)> \
  -n "T4 T4-0N aK"
```
wrapped in `perl -e 'alarm …'` for the wall-clock limit (macOS has no `timeout`). The goal prompt names the goal,
the files to read, the done-condition (`accept.sh Gn` + `guard.sh` = 0), the overnight rules, and — on a retry — the
tail of the last failure. Each invocation is a fresh session (Thin Ledger: the repo is memory); `--resume` /
`--continue` exist but are not used, so a half-finished attempt is picked up from `git diff`, not from chat.

Then: `bash scripts/accept.sh Gn` and `bash scripts/guard.sh` → pass: `.ai/STATUS.md` → DONE, `git commit`
`T4-0N: <goal title>` (local; never push, never force) → next goal. Fail: retry (max 3) → BLOCKED, partial work goes
to `git stash`, a status-only commit is made, and the loop continues with the next goal that does not depend on it
(dependents are marked SKIPPED). Everything is appended to `logs/overnight.log`.

**Usage limits:** if Claude exits with a usage-limit, rate-limit, 429/529 or "overloaded" error, the loop logs the
time, sleeps 30 min (`LIMIT_RETRY_SEC`), and retries the same goal until it succeeds or the hard stop arrives. These
waits are not attempts. A goal already DONE is never repeated (`scripts/status.py` refuses to reopen it).

| Setting (`overnight.conf`) | Proposed | Meaning |
|---|---|---|
| `RUN_BUDGET_USD` | 12 | `--max-budget-usd` per goal invocation |
| `TOTAL_BUDGET_USD` | 100 | loop stops before an invocation that could pass it (spend read from each result's `total_cost_usd`; a killed run counts its full budget) |
| `HARD_STOP_IST` | 08:00 | nothing starts after 07:50; a running goal is killed at 07:50; report by 08:00 |
| `GOAL_WALL_MIN` | 90 | wall-clock limit per invocation |
| `MAX_ATTEMPTS` | 3 | failed acceptance attempts before BLOCKED |
| `LIMIT_RETRY_SEC` | 1800 | wait after a usage/rate limit |

Model spend inside the workflow (OpenAI) is capped separately in `.env`: `RUN_USD_CAP` 0.25, `DAILY_USD_CAP` 1.00,
`PROJECT_LLM_USD_CAP` 2.00. The runner refuses to start a run that could pass the project cap.

## 6. Guardrails during the night

| Guardrail | How it is enforced |
|---|---|
| Per-run and total Claude budget | `--max-budget-usd` + loop arithmetic on `logs/spend.tsv` |
| Hard stop | computed from `HARD_STOP_IST` (Asia/Kolkata); start check + `alarm` kill |
| 3 failures → BLOCKED, move on | `scripts/status.py next` skips dependents of blocked goals |
| No paid API calls outside the cap | workflow caps (ADR-007) + runner project cap; the worker may call models only via `src.replay.run`; `WebFetch`/`WebSearch`/`curl` denied |
| No new dependencies | `pip`/`npm`/`brew`/`venv` denied; `guard.sh` fails on any manifest or non-stdlib import |
| No secrets printed or committed | `.env` never sourced into Claude's environment; `Read(.env)` denied (T4 and T2); `guard.sh` scans every non-ignored file for secret patterns **and** every `.env` value, and redacts values found in `logs/` |
| No changes outside this folder | file tools limited to `./**` (plus read-only T2 / two reference files); `guard.sh` compares T2's git HEAD + status, `~/Projects/n8n-local/docker-compose.yml` and the n8n image with the start snapshot |
| Contract files stay intact | `scripts/`, `GOALS.md`, `AGENTS.md`, `CLAUDE.md`, `overnight.conf` are write-denied and hash-checked after every goal; a change is restored by the loop and the attempt fails |
| Commits local only | `git commit/push/reset/checkout/stash` denied to the worker; the loop commits; preflight warns if a remote exists |

Residual risk: `Bash(python3 *)` is allowed (tests and the runner need it), and Python can do anything the user can.
The checks above detect the likely failures after each goal; they cannot prevent a deliberate misuse inside one goal.

## 7. In the morning

Open `MORNING_REPORT.md` first: goals done / blocked / skipped, test results, acceptance sweep, scorecard numbers,
Claude and OpenAI spend, limit waits, and **Check first** (blocked goals, protected-file events, failed attacks,
30 gold labels to spot-check, new decisions in `OPEN_QUESTIONS.md`, owner-only steps). Then:
`git log --oneline`, `git stash list`, `.ai/REVIEW.md`.
