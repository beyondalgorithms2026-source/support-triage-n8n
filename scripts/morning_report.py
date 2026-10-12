"""Write MORNING_REPORT.md content to stdout from STATUS, logs and evals. Stdlib only; never prints secrets."""
from __future__ import annotations

import csv
import json
import random
import re
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
IST = ZoneInfo("Asia/Kolkata")


def sh(*args):
    r = subprocess.run(list(args), cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip()


def read(path, default=""):
    p = ROOT / path
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else default


def main():
    rows = json.loads(sh("python3", "scripts/status.py", "json") or "[]")
    start_sha = read("logs/start_sha").strip()
    out = ["# Morning report — T4 overnight run", "",
           "Generated {} by `scripts/morning_report.py` from `.ai/STATUS.md`, `logs/`, `evals/`. "
           "Read **Check first** before anything else.".format(datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")), ""]

    done = [r for r in rows if r["state"] == "DONE"]
    blocked = [r for r in rows if r["state"] == "BLOCKED"]
    skipped = [r for r in rows if r["state"] == "SKIPPED"]
    todo = [r for r in rows if r["state"] in ("TODO", "IN_PROGRESS")]

    # spend and limits
    spend_rows = []
    if (LOGS / "spend.tsv").exists():
        for line in (LOGS / "spend.tsv").read_text().splitlines():
            parts = line.split("\t")
            if len(parts) >= 5:
                spend_rows.append(parts)
    claude_usd = sum(float(p[4] or 0) for p in spend_rows)
    log = read("logs/overnight.log")
    limit_hits = [l for l in log.splitlines() if "LIMIT HIT" in l]
    protected = [l for l in log.splitlines() if "PROTECTED FILES MODIFIED" in l]
    llm_usd, llm_runs = 0.0, []
    ledger = ROOT / "evals" / "cost_ledger.csv"
    if ledger.exists():
        with ledger.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                llm_usd += float(r.get("usd") or 0)
                llm_runs.append(r)

    # check first
    out += ["## Check first", ""]
    n = 1
    for r in blocked:
        out.append("{}. **{} BLOCKED** — {} — `{}`. Partial work is in `git stash list`.".format(
            n, r["task"], r["title"], r["evidence"])); n += 1
    if skipped:
        out.append("{}. Skipped because a dependency is blocked: {}.".format(
            n, ", ".join(r["task"] for r in skipped))); n += 1
    if protected:
        out.append("{}. The worker modified protected files ({} time(s)); the loop restored them. See `logs/overnight.log`."
                   .format(n, len(protected))); n += 1
    guard = read("logs/final-guard.log")
    if "FAIL" in guard:
        out.append("{}. **Guard failed at the end** — `logs/final-guard.log`.".format(n)); n += 1
    sec = ROOT / "evals" / "security_findings.json"
    if sec.exists():
        try:
            data = json.loads(sec.read_text())
            items = data.get("findings", data) if isinstance(data, dict) else data
            failed = [f.get("id") or f.get("finding_id") for f in items if str(f.get("result", "")).lower() == "failed"]
            if failed:
                out.append("{}. Security attacks that **failed** (control did not hold): {}.".format(n, ", ".join(map(str, failed)))); n += 1
        except (ValueError, AttributeError):
            pass
    manifest = ROOT / "evals" / "inputs" / "manifest.csv"
    if manifest.exists():
        with manifest.open(newline="", encoding="utf-8") as f:
            ids = [r["input_id"] for r in csv.DictReader(f)]
        sample = sorted(random.Random(20261013).sample(ids, min(30, len(ids))))
        out.append("{}. Spot-check these 30 gold labels against `docs/HARNESS_SPEC.md` §1.2 (written by the model, not "
                   "by you): {}.".format(n, ", ".join(sample))); n += 1
    oq_diff = sh("git", "diff", start_sha, "HEAD", "--", "OPEN_QUESTIONS.md") if start_sha else ""
    new_q = [l[1:].strip() for l in oq_diff.splitlines() if l.startswith("+") and re.match(r"\+\s*##", l)]
    if new_q:
        out.append("{}. New decisions recorded overnight in `OPEN_QUESTIONS.md`: {}.".format(n, "; ".join(new_q))); n += 1
    if (ROOT / "evals" / "thresholds.json").exists():
        out.append("{}. Thresholds: read `evals/threshold_sweep.csv` — any class at 1.01 always goes to a human.".format(n)); n += 1
    out.append("{}. Before publishing anything: write § Trace notes in `evals/findings.md` yourself, accept or edit "
               "ADR-001…007, and get a cross-family review (the overnight author and its checks are both Claude).".format(n))
    out.append("")

    # goals
    out += ["## Goals", "", "| Task | Goal | State | Attempts | Evidence |", "|---|---|---|---|---|"]
    for r in rows:
        out.append("| {} | {} | {} | {} | {} |".format(r["task"], r["title"], r["state"], r["attempts"], r["evidence"]))
    out += ["", "Done {} · blocked {} · skipped {} · not started {} (of {}).".format(
        len(done), len(blocked), len(skipped), len(todo), len(rows)), ""]
    commits = sh("git", "log", "--oneline", "{}..HEAD".format(start_sha)) if start_sha else ""
    out += ["Commits this run (local, not pushed):", "", "```", commits or "(none)", "```", ""]

    # tests
    out += ["## Test results", ""]
    tests = read("logs/final-tests.log")
    tail = [l for l in tests.splitlines() if re.match(r"^(Ran \d+ tests|OK|FAILED)", l)]
    out.append("Unit tests (`python3 -m unittest discover -s tests -t .`): {}".format(" · ".join(tail) or "not run"))
    acc = read("logs/final-accept.log").strip()
    out += ["", "Acceptance sweep (`bash scripts/accept.sh all`):", "", "```", acc or "(not run)", "```", ""]

    # scorecard
    out += ["## Scorecard numbers", ""]
    rep = ROOT / "evals" / "eval_report.json"
    if rep.exists():
        report = json.loads(rep.read_text())
        for key in ("quality", "routing", "operations", "cost", "metric_status"):
            if key in report:
                out.append("- **{}**: `{}`".format(key, json.dumps(report[key], sort_keys=True)[:600]))
    elif (ROOT / "evals" / "scorecard.csv").exists():
        with (ROOT / "evals" / "scorecard.csv").open(newline="", encoding="utf-8") as f:
            sc = list(csv.DictReader(f))
        auto = [r for r in sc if r.get("outcome_hat") == "auto_route"]
        correct = [r for r in auto if r.get("category_hat") == r.get("category_gold")]
        out.append("- test tickets scored: {}; auto-routed: {}; auto-route category correct: {}; routed to human: {}"
                   .format(len(sc), len(auto), len(correct), sum(1 for r in sc if r.get("outcome_hat") == "review")))
        codes = {}
        for r in sc:
            for c in filter(None, (r.get("failure_codes") or "").split("|")):
                codes[c] = codes.get(c, 0) + 1
        out.append("- failure codes: {}".format(codes or "none"))
    else:
        out.append("No scorecard yet (G10 not done).")
    out.append("")

    # spend
    out += ["## Spend", "",
            "- Claude Code (overnight worker): **${:.2f}** over {} invocation(s) (`logs/spend.tsv`).".format(claude_usd, len(spend_rows)),
            "- Workflow model calls (OpenAI, `evals/cost_ledger.csv`): **${:.4f}** over {} run(s).".format(llm_usd, len(llm_runs)),
            "- Usage/rate-limit waits: {}.".format(len(limit_hits) or "none")]
    for l in limit_hits:
        out.append("  - " + l)
    out += ["", "## Where to look", "",
            "`logs/overnight.log` (timeline) · `logs/T4-NN-aK.json` (each Claude result) · `logs/T4-NN-aK.accept.log` · "
            "`.ai/HANDOFF.md` and `.ai/REVIEW.md` (last worker's closeout) · `git stash list` (blocked work)."]
    print("\n".join(out))


if __name__ == "__main__":
    main()
