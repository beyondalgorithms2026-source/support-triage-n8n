#!/usr/bin/env bash
# Pre-flight for the overnight run. Run before bed:  bash scripts/preflight.sh  [--no-claude-smoke]
# Checks every item, prints PASS/WARN/FAIL per line, exits 1 if any FAIL. On success writes logs/preflight.ok,
# which scripts/overnight.sh requires (max age 3 h). Never prints secret values.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
rm -f logs/preflight.ok
SMOKE=1; [ "${1:-}" = "--no-claude-smoke" ] && SMOKE=0
FAILS=0; WARNS=0
if [ -t 1 ]; then R=$'\033[31m'; Y=$'\033[33m'; Gc=$'\033[32m'; N=$'\033[0m'; else R=""; Y=""; Gc=""; N=""; fi
pass() { echo "${Gc}PASS${N}  $*"; }
warn() { echo "${Y}WARN${N}  $*"; WARNS=$((WARNS + 1)); }
fail() { echo "${R}FAIL${N}  $*"; FAILS=$((FAILS + 1)); }

# shellcheck disable=SC1091
source ./overnight.conf
REQUIRED_ENV="T4_TARGET N8N_BASE_URL N8N_CONTAINER OPENAI_API_KEY T4_WEBHOOK_TOKEN T4_WEBHOOK_PATH SINK_TOKEN SINK_PORT
SINK_BASE_URL JIRA_BASE_URL JIRA_SANDBOX_EMAIL JIRA_SANDBOX_API_TOKEN JIRA_PROJECT_KEY SLACK_BASE_URL SLACK_SANDBOX_BOT_TOKEN
SLACK_CHANNEL_TRIAGE SLACK_CHANNEL_REVIEW LLM_PRICE_IN_PER_MTOK LLM_PRICE_OUT_PER_MTOK RUN_USD_CAP DAILY_USD_CAP PROJECT_LLM_USD_CAP"

echo "== Mac"
pmset -g batt | grep -q "AC Power" && pass "on AC power" || fail "on battery — plug in the charger (caffeinate -s only holds on AC)"
if ioreg -r -k AppleClamshellState 2>/dev/null | grep -q '"AppleClamshellState" = Yes'; then fail "lid is closed"; else pass "lid open"; fi
command -v caffeinate >/dev/null && pass "caffeinate present" || fail "caffeinate missing"
pmset -g 2>/dev/null | grep -qE '^ *lowpowermode +1' && warn "Low Power Mode is on — turn it off" || pass "Low Power Mode off"
FREE_GB=$(df -g "$ROOT" | awk 'NR==2 {print $4}')
[ "${FREE_GB:-0}" -ge 5 ] && pass "disk free ${FREE_GB} GiB" || fail "disk free ${FREE_GB:-?} GiB (< 5)"

echo "== Tools"
for t in python3 node jq perl git docker; do command -v "$t" >/dev/null && pass "$t present" || fail "$t missing"; done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' && pass "python3 >= 3.9 ($(python3 -V 2>&1))" || fail "python3 < 3.9"
python3 -c 'import zoneinfo; zoneinfo.ZoneInfo("Asia/Kolkata")' 2>/dev/null && pass "zoneinfo Asia/Kolkata" || fail "zoneinfo unavailable"

echo "== Docker / n8n"
if docker info >/dev/null 2>&1; then pass "Docker daemon running"; else fail "Docker not running — open Docker Desktop"; fi
IMG="$(docker inspect -f '{{.Config.Image}}' n8n 2>/dev/null)"
[ "$IMG" = "n8nio/n8n:2.22.5" ] && pass "container n8n image $IMG" || fail "container n8n image '${IMG:-none}' (want n8nio/n8n:2.22.5)"
STATE="$(docker inspect -f '{{.State.Status}}' n8n 2>/dev/null)"
[ "$STATE" = "running" ] && pass "container n8n running" || fail "container n8n state '${STATE:-none}'"
VER="$(docker exec n8n n8n --version 2>/dev/null | tail -n 1)"
[ "$VER" = "2.22.5" ] && pass "n8n --version $VER" || fail "n8n --version '${VER:-?}' (want 2.22.5)"
RP="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' n8n 2>/dev/null)"
[ "$RP" = "always" ] || [ "$RP" = "unless-stopped" ] && pass "restart policy $RP" || warn "restart policy '${RP:-none}' — n8n will not come back after a Docker restart"
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:5678/healthz)"
[ "$CODE" = "200" ] && pass "n8n /healthz 200" || fail "n8n /healthz returned '$CODE'"
if lsof -iTCP:8790 -sTCP:LISTEN -t >/dev/null 2>&1; then fail "port 8790 already in use (sink port)"; else pass "port 8790 free"; fi

echo "== Network"
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 https://api.openai.com/v1/models)"
case "$CODE" in 200|401|403) pass "api.openai.com reachable (HTTP $CODE, no key sent)";; *) fail "api.openai.com unreachable (HTTP '$CODE')";; esac
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 https://api.anthropic.com/)"
[ -n "$CODE" ] && [ "$CODE" != "000" ] && pass "api.anthropic.com reachable (HTTP $CODE)" || fail "api.anthropic.com unreachable"

echo "== Git"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1 && [ "$(git rev-parse --show-toplevel)" = "$ROOT" ]; then
  pass "git repo at project root"
  git rev-parse HEAD >/dev/null 2>&1 && pass "HEAD exists ($(git rev-parse --short HEAD))" || fail "no commit yet — commit the plan first"
  [ -z "$(git status --porcelain)" ] && pass "working tree clean" || fail "working tree not clean: $(git status --porcelain | head -n 5 | tr '\n' ' ')"
  [ -n "$(git config user.email)" ] && pass "git user.email set" || fail "git user.email not set"
  [ -z "$(git remote)" ] && pass "no git remote (nothing can be pushed)" || warn "git remote exists: $(git remote | tr '\n' ' ') — the loop never pushes"
  git check-ignore -q .env && pass ".env is gitignored" || fail ".env is not gitignored"
  [ -z "$(git ls-files .env)" ] && pass ".env not tracked" || fail ".env is tracked"
else
  fail "not a git repo at $ROOT — run: git init && git add -A && git commit -m 'T4-00: plan'"
fi

echo "== .env (names only)"
python3 scripts/checks.py env-names $REQUIRED_ENV | sed 's/^ok:/PASS /; s/^FAIL:/FAIL /'
python3 scripts/checks.py env-names $REQUIRED_ENV >/dev/null || FAILS=$((FAILS + 1))
if [ -f .env ]; then
  P="$(stat -f %Lp .env)"; [ "$P" = "600" ] && pass ".env mode 600" || warn ".env mode $P (chmod 600 .env)"
  grep -qE '^OPENAI_API_KEY=sk-' .env && pass "OPENAI_API_KEY has the expected prefix" || fail "OPENAI_API_KEY empty or unexpected format"
  python3 - <<'PY' && pass "LLM caps numeric and ordered (run <= daily <= project)" || fail "RUN_USD_CAP / DAILY_USD_CAP / PROJECT_LLM_USD_CAP missing, non-numeric or out of order"
import re, sys
v = dict(l.split("=", 1) for l in open(".env").read().splitlines() if "=" in l and not l.startswith("#"))
try:
    r, d, p = (float(v[k].strip()) for k in ("RUN_USD_CAP", "DAILY_USD_CAP", "PROJECT_LLM_USD_CAP"))
    sys.exit(0 if 0 < r <= d <= p <= 5 else 1)
except (KeyError, ValueError):
    sys.exit(1)
PY
fi

echo "== Overnight budgets and time (overnight.conf)"
python3 - "$RUN_BUDGET_USD" "$TOTAL_BUDGET_USD" <<'PY' && pass "Claude budgets: \$$RUN_BUDGET_USD per goal, \$$TOTAL_BUDGET_USD total" || fail "RUN_BUDGET_USD / TOTAL_BUDGET_USD invalid (need 0 < run <= total)"
import sys
r, t = float(sys.argv[1]), float(sys.argv[2])
sys.exit(0 if 0 < r <= t else 1)
PY
HOURS="$(python3 - "$HARD_STOP_IST" <<'PY'
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
tz = ZoneInfo("Asia/Kolkata"); now = datetime.now(tz)
hh, mm = (int(x) for x in sys.argv[1].split(":"))
stop = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
stop = stop + timedelta(days=1) if stop <= now else stop
print(round((stop - now).total_seconds() / 3600, 1))
PY
)"
python3 -c "import sys; sys.exit(0 if float(sys.argv[1]) >= 3 else 1)" "$HOURS" && pass "hard stop $HARD_STOP_IST IST is in $HOURS h" || warn "hard stop $HARD_STOP_IST IST is only $HOURS h away"

echo "== Claude Code CLI"
if [ ! -x "${CLAUDE_BIN:-}" ]; then
  CAND="$(ls -dt "$HOME/Library/Application Support/Claude/claude-code/"*/*/claude.app/Contents/MacOS/claude 2>/dev/null | head -n 1)"
  [ -n "$CAND" ] && CLAUDE_BIN="$CAND" && warn "CLAUDE_BIN in overnight.conf missing; using newest bundled $CLAUDE_BIN"
fi
if [ -x "${CLAUDE_BIN:-}" ]; then
  pass "claude $("$CLAUDE_BIN" --version 2>/dev/null)"
  HELP="$("$CLAUDE_BIN" --help 2>&1)"
  for flag in "--print" "--output-format" "--permission-mode" "dontAsk" "--permission-prompts" "--max-budget-usd" \
              "--settings" "--model" "--fallback-model" "--effort" "--name"; do
    echo "$HELP" | grep -q -- "$flag" && pass "claude --help lists $flag" || fail "claude --help does not list $flag"
  done
  python3 -c "import json; json.load(open('scripts/claude-overnight-settings.json'))" && pass "claude settings JSON valid" || fail "claude settings JSON invalid"
  if [ "$SMOKE" = 1 ]; then
    OUT="$(perl -e 'alarm 120; exec @ARGV' "$CLAUDE_BIN" -p "Reply with exactly the word OK." --output-format json \
          --model "$CLAUDE_MODEL" --permission-mode dontAsk --permission-prompts none --tools "" --max-budget-usd 0.5 \
          --no-session-persistence < /dev/null 2>&1)"
    if echo "$OUT" | jq -e '(.is_error == false) and (.result | test("OK"))' >/dev/null 2>&1; then
      pass "claude -p smoke call OK (cost \$$(echo "$OUT" | jq -r '.total_cost_usd // "?"'))"
    else
      fail "claude -p smoke call failed — check login ('\"\$CLAUDE_BIN\" auth') : $(echo "$OUT" | tail -c 300)"
    fi
  else
    warn "claude smoke call skipped (--no-claude-smoke)"
  fi
else
  fail "Claude CLI not found (set CLAUDE_BIN in overnight.conf)"
fi

echo "== Repo checks"
bash scripts/accept.sh plan > logs/preflight-plan.log 2>&1 && pass "accept.sh plan" || fail "accept.sh plan (logs/preflight-plan.log)"
if [ -d tests ]; then
  python3 -m unittest discover -s tests -t . > logs/preflight-tests.log 2>&1 && pass "unit tests pass" || fail "unit tests fail (logs/preflight-tests.log)"
else
  pass "no tests/ yet (expected before G1); test runner: python3 -m unittest discover -s tests -t ."
fi
bash scripts/guard.sh > logs/preflight-guard.log 2>&1 && pass "guard.sh clean" || fail "guard.sh (logs/preflight-guard.log)"
NEXT="$(python3 scripts/status.py next)"
[ -n "$NEXT" ] && pass "next goal: $NEXT" || warn "no eligible goal in .ai/STATUS.md"

echo
if [ "$FAILS" -eq 0 ]; then
  date +%s > logs/preflight.ok
  echo "${Gc}PREFLIGHT PASSED${N} ($WARNS warning(s)). Start: bash scripts/overnight.sh"
  exit 0
fi
echo "${R}PREFLIGHT FAILED: $FAILS failure(s), $WARNS warning(s). Fix and re-run.${N}"
exit 1
