#!/usr/bin/env bash
# T4 overnight build loop — one GOALS.md goal per Claude Code invocation. See RUN_OVERNIGHT.md.
#
#   bash scripts/overnight.sh            (re-execs itself under `caffeinate -dimsu`)
#
# Per goal: run Claude non-interactively → run `scripts/accept.sh Gn` + `scripts/guard.sh` → on pass, set DONE in
# .ai/STATUS.md and commit locally `T4-0n: <title>` (never push, never force). On fail, retry with the failure tail;
# after MAX_ATTEMPTS, mark BLOCKED, stash the partial work, and continue with the next goal that does not depend on
# it. Usage-limit / rate-limit / overloaded errors are not attempts: log, sleep LIMIT_RETRY_SEC, retry the same goal.
# Stops at HARD_STOP_IST, at TOTAL_BUDGET_USD, when no goal is eligible, or when logs/STOP exists.
# Always ends by writing MORNING_REPORT.md.
# macOS bash 3.2 compatible. Never sources .env (secrets stay out of Claude's environment).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -z "${T4_CAFFEINATED:-}" ]; then
  export T4_CAFFEINATED=1
  exec caffeinate -dimsu /bin/bash "$0" "$@"
fi

# shellcheck disable=SC1091
source ./overnight.conf
mkdir -p logs
LOG="logs/overnight.log"
SPEND="logs/spend.tsv"
LIMIT_RE='usage limit|hit your limit|limit reached|rate[ _-]?limit|overloaded|too many requests|\b429\b|\b529\b|resets at|try again later|quota'

log() { printf '%s  %s\n' "$(TZ=Asia/Kolkata date '+%Y-%m-%d %H:%M:%S IST')" "$*" | tee -a "$LOG"; }
now() { date +%s; }
fadd() { python3 -c "import sys; print(round(float(sys.argv[1]) + float(sys.argv[2]), 6))" "$1" "$2"; }
fmin() { python3 -c "import sys; print(min(float(a) for a in sys.argv[1:]))" "$@"; }
flt() { python3 -c "import sys; sys.exit(0 if float(sys.argv[1]) < float(sys.argv[2]) else 1)" "$1" "$2"; }

resolve_claude() {
  if [ -x "${CLAUDE_BIN:-}" ]; then return 0; fi
  local cand
  cand="$(ls -dt "$HOME/Library/Application Support/Claude/claude-code/"*/*/claude.app/Contents/MacOS/claude 2>/dev/null | head -n 1)"
  [ -n "$cand" ] && [ -x "$cand" ] && CLAUDE_BIN="$cand" && log "CLAUDE_BIN not found; using newest bundled: $CLAUDE_BIN"
  [ -x "${CLAUDE_BIN:-}" ]
}

STOP_EPOCH="$(python3 - "$HARD_STOP_IST" <<'PY'
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
tz = ZoneInfo("Asia/Kolkata")
hh, mm = (int(x) for x in sys.argv[1].split(":"))
now = datetime.now(tz)
stop = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
if stop <= now:
    stop += timedelta(days=1)
print(int(stop.timestamp()))
PY
)"
RESERVE=$(( STOP_RESERVE_MIN * 60 ))

spent_total() { [ -f "$SPEND" ] && awk -F'\t' '{s += $5} END {printf "%.4f", s + 0}' "$SPEND" || echo 0; }

finalize() {
  local rc=$?
  log "FINALIZE: final tests, acceptance sweep, morning report"
  if [ -d tests ]; then
    python3 -m unittest discover -s tests -t . > logs/final-tests.log 2>&1 && log "final unit tests: PASS" || log "final unit tests: FAIL (logs/final-tests.log)"
  else
    echo "no tests/ directory" > logs/final-tests.log
  fi
  bash scripts/accept.sh all > logs/final-accept.log 2>&1
  bash scripts/guard.sh > logs/final-guard.log 2>&1 || log "final guard: FAIL (logs/final-guard.log)"
  python3 scripts/morning_report.py > MORNING_REPORT.md 2>> "$LOG" && log "wrote MORNING_REPORT.md" || log "morning report FAILED"
  log "overnight loop exit (rc=$rc). Total Claude spend: \$$(spent_total)"
}
trap finalize EXIT
trap 'log "interrupted"; exit 130' INT TERM

# ---------------------------------------------------------------- start checks
[ -f logs/preflight.ok ] || { log "ABORT: logs/preflight.ok missing — run bash scripts/preflight.sh first"; exit 1; }
age=$(( $(now) - $(stat -f %m logs/preflight.ok) ))
[ "$age" -lt 10800 ] || { log "ABORT: preflight is older than 3 h — run it again"; exit 1; }
resolve_claude || { log "ABORT: Claude CLI not found"; exit 1; }
[ -z "$(git status --porcelain)" ] || { log "ABORT: git tree not clean at start"; exit 1; }
git rev-parse HEAD > logs/start_sha
python3 scripts/checks.py snapshot --write logs/outside_snapshot.json >/dev/null
python3 scripts/status.py init
log "START: hard stop $(TZ=Asia/Kolkata date -r "$STOP_EPOCH" '+%Y-%m-%d %H:%M IST'), run budget \$$RUN_BUDGET_USD, total budget \$$TOTAL_BUDGET_USD, model $CLAUDE_MODEL (fallback $CLAUDE_FALLBACK_MODEL)"

# ---------------------------------------------------------------- loop
while true; do
  [ -f logs/STOP ] && { log "STOP file found — stopping"; break; }
  if [ $(( $(now) + RESERVE )) -ge "$STOP_EPOCH" ]; then log "hard stop reached — no new goal"; break; fi

  G="$(python3 scripts/status.py next)"
  [ -z "$G" ] && { log "no eligible goal left — stopping"; break; }
  TASK="$(python3 scripts/status.py get "$G" task)"
  TITLE="$(python3 scripts/status.py get "$G" title)"
  ATTEMPTS="$(python3 scripts/status.py get "$G" attempts)"

  if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then
    python3 scripts/status.py set "$G" BLOCKED --evidence "max attempts reached before restart"
    continue
  fi

  SPENT="$(spent_total)"
  REMAIN="$(python3 -c "import sys; print(round(float(sys.argv[1]) - float(sys.argv[2]), 4))" "$TOTAL_BUDGET_USD" "$SPENT")"
  if flt "$REMAIN" 1; then log "total budget reached (spent \$$SPENT of \$$TOTAL_BUDGET_USD) — stopping"; break; fi
  BUDGET="$(fmin "$RUN_BUDGET_USD" "$REMAIN")"

  ATTEMPT=$(( ATTEMPTS + 1 ))
  python3 scripts/status.py set "$G" IN_PROGRESS --evidence "attempt $ATTEMPT running"
  WALL=$(( STOP_EPOCH - RESERVE - $(now) )); [ "$WALL" -gt $(( GOAL_WALL_MIN * 60 )) ] && WALL=$(( GOAL_WALL_MIN * 60 ))
  OUT="logs/$TASK-a$ATTEMPT.json"; ERR="logs/$TASK-a$ATTEMPT.err"; ACC="logs/$TASK-a$ATTEMPT.accept.log"
  FAILFILE="logs/$TASK-last-fail.txt"

  PROMPT="You are the unattended T4 overnight build worker. Goal $G (task $TASK): $TITLE. Attempt $ATTEMPT of $MAX_ATTEMPTS.
Read in this order: HANDOFF.md, AGENTS.md, .ai/HANDOFF.md, .ai/STATUS.md, the '## $G' section of GOALS.md, then only the docs and files that section names.
Do only this goal. Done means: 'bash scripts/accept.sh $G' exits 0 and 'bash scripts/guard.sh' exits 0. Run both yourself before you stop.
Rules for this run: do not commit, push, stash, reset or delete (the loop commits); do not edit .ai/STATUS.md, GOALS.md, scripts/, AGENTS.md, CLAUDE.md or overnight.conf; never ask questions — record each decision in OPEN_QUESTIONS.md (dated, with cost to reverse) and continue with the most reversible option; never read .env or print secret values; stay inside this folder; Python stdlib only, no installs, no web access; make live model calls only through 'python3 -m src.replay.run', which enforces the spend caps.
Before you stop: overwrite .ai/HANDOFF.md and .ai/REVIEW.md as AGENTS.md § Closeout says.
The working tree may hold partial work from an earlier attempt of this goal: check 'git status' and 'git diff' first and build on it."
  if [ -f "$FAILFILE" ]; then
    PROMPT="$PROMPT

The previous attempt failed. Last lines of its acceptance/guard output:
$(tail -n 60 "$FAILFILE")"
  fi

  log "$TASK ($G) attempt $ATTEMPT: start (budget \$$BUDGET, wall ${WALL}s)"
  perl -e 'alarm shift @ARGV; exec @ARGV or die "exec failed: $!"' "$WALL" \
    "$CLAUDE_BIN" -p "$PROMPT" \
      --output-format json \
      --model "$CLAUDE_MODEL" \
      --fallback-model "$CLAUDE_FALLBACK_MODEL" \
      --effort "$CLAUDE_EFFORT" \
      --permission-mode dontAsk \
      --permission-prompts none \
      --settings scripts/claude-overnight-settings.json \
      --max-budget-usd "$BUDGET" \
      -n "T4 $TASK a$ATTEMPT" \
    > "$OUT" 2> "$ERR" < /dev/null
  RC=$?

  COST="$(jq -r '.total_cost_usd // empty' "$OUT" 2>/dev/null)"
  IS_ERR="$(jq -r '.is_error // false' "$OUT" 2>/dev/null || echo true)"
  SUBTYPE="$(jq -r '.subtype // "none"' "$OUT" 2>/dev/null || echo unparsed)"
  SESSION="$(jq -r '.session_id // "none"' "$OUT" 2>/dev/null || echo none)"
  if [ -z "$COST" ]; then COST="$BUDGET"; log "$TASK: no cost reported (rc=$RC); counting the full run budget \$$BUDGET"; fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$TASK" "$ATTEMPT" "$RC" "$COST" "$SUBTYPE" "$SESSION" >> "$SPEND"
  log "$TASK attempt $ATTEMPT: claude rc=$RC subtype=$SUBTYPE is_error=$IS_ERR cost=\$$COST session=$SESSION"

  # usage limit / rate limit / overloaded → not an attempt; wait and retry the same goal
  if { [ "$RC" -ne 0 ] || [ "$IS_ERR" = "true" ]; } && cat "$OUT" "$ERR" 2>/dev/null | grep -Eiq "$LIMIT_RE"; then
    python3 scripts/status.py set "$G" TODO --attempts "$ATTEMPTS" --evidence "usage/rate limit at $(TZ=Asia/Kolkata date '+%H:%M IST'); waiting"
    WAIT="$LIMIT_RETRY_SEC"; LEFT=$(( STOP_EPOCH - RESERVE - $(now) ))
    if [ "$LEFT" -le 60 ]; then log "LIMIT HIT at $(TZ=Asia/Kolkata date '+%H:%M IST'); no time left before hard stop"; break; fi
    [ "$LEFT" -lt "$WAIT" ] && WAIT="$LEFT"
    log "LIMIT HIT ($TASK) at $(TZ=Asia/Kolkata date '+%H:%M IST'); sleeping ${WAIT}s, then retrying the same goal"
    sleep "$WAIT"
    continue
  fi

  python3 scripts/status.py set "$G" IN_PROGRESS --attempts "$ATTEMPT" --evidence "attempt $ATTEMPT checking"

  # protected files: restore by the loop, count as a failed attempt
  PROT_FAIL=""
  CHANGED="$(python3 scripts/checks.py protected-changed)"
  if [ -n "$CHANGED" ]; then
    log "PROTECTED FILES MODIFIED by $TASK — restoring: $(echo "$CHANGED" | tr '\n' ' ')"
    echo "$CHANGED" | while IFS= read -r f; do [ -n "$f" ] && git checkout -- "$f"; done
    PROT_FAIL="protected files were modified (restored): $(echo "$CHANGED" | tr '\n' ' ')"
  fi

  { bash scripts/accept.sh "$G"; A=$?; bash scripts/guard.sh; GU=$?; echo "accept=$A guard=$GU"; } > "$ACC" 2>&1
  A_RC="$(tail -n 1 "$ACC")"
  if [ "$A_RC" = "accept=0 guard=0" ] && [ -z "$PROT_FAIL" ]; then
    python3 scripts/status.py set "$G" DONE --attempts "$ATTEMPT" --evidence "accept+guard pass (attempt $ATTEMPT, \$$COST)"
    git add -A
    if git commit -q -m "$TASK: $TITLE" -m "Goal $G, attempt $ATTEMPT. scripts/accept.sh $G and scripts/guard.sh passed. Overnight loop commit (local only)." \
         -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; then
      log "$TASK DONE — commit $(git rev-parse --short HEAD)"
      rm -f "$FAILFILE"
    else
      log "$TASK: git commit FAILED — stopping so the tree can be inspected"; break
    fi
  else
    { [ -n "$PROT_FAIL" ] && echo "$PROT_FAIL"; grep -E "ACCEPT FAIL|FAIL:|Error|Traceback|AssertionError" "$ACC" | tail -n 40; tail -n 20 "$ACC"; } > "$FAILFILE"
    if [ "$ATTEMPT" -ge "$MAX_ATTEMPTS" ]; then
      FIRST="$(grep -m 1 -E "ACCEPT FAIL|FAIL:|Error" "$FAILFILE" | cut -c1-200)"
      git stash push -u -q -m "$TASK blocked: partial work from $MAX_ATTEMPTS attempts" || true
      python3 scripts/status.py set "$G" BLOCKED --attempts "$ATTEMPT" --evidence "${FIRST:-acceptance failed}; work in git stash; see $FAILFILE"
      git add .ai/STATUS.md && git commit -q -m "$TASK: BLOCKED after $MAX_ATTEMPTS attempts — $TITLE (status only)" \
        -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" || true
      log "$TASK BLOCKED after $ATTEMPT attempts: ${FIRST:-see $FAILFILE}"
    else
      python3 scripts/status.py set "$G" TODO --attempts "$ATTEMPT" --evidence "attempt $ATTEMPT failed acceptance; retrying"
      log "$TASK attempt $ATTEMPT failed acceptance — retrying with failure context"
    fi
  fi
done
