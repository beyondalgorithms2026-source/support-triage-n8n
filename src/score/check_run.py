"""Per-phase run invariants used by G7–G11 acceptance and tests/test_replay_regression.py.

    python3 -m src.score.check_run --phase <slice|smoke|dev|test|attack> (--latest | --run-id <id>)

Checks: phase, split and ticket count; one terminal audit row per ticket per pass; at most one Jira issue per
dedupe_key; pass B creates no issue (test: and makes no model call); no planted PII in outbound bodies or LLM input;
ledger rows present; spend within the run cap; slice: confidences come from logprobs; smoke: injection -> review,
malformed -> rejected, every forced fault fired and left an errors row (or a reconcile link); attack: every SEC ID
has a result with evidence, and the secret scan is clean. Exit 0 only if all hold.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from src.score.score import (MANIFEST, ROOT, RUNS_DIR, as_float, as_list, input_of, leak_targets, load_golds,
                             load_run, outbound, pass_of, read_csv, read_json, run_facts, truth)

PHASES = {
    "slice": {"split": "dev", "tickets": 10, "passes": "A"},
    "smoke": {"split": "dev", "tickets": 12, "passes": "AB"},
    "dev": {"split": "dev", "tickets": 100, "passes": "A"},
    "test": {"split": "test", "tickets": 100, "passes": "AB"},
    "attack": {"split": None, "tickets": None, "passes": "A"},
}
NO_LLM_IN_PASS_B = ("test",)
COST_LEDGER = ROOT / "evals" / "cost_ledger.csv"
ATTACK_RESULTS = "attack_results.json"      # written by src/replay/attacks.py (G11)
SEC_IDS = tuple("SEC-{:02d}".format(n) for n in range(1, 21))


def latest_run(phase, runs_dir=RUNS_DIR):
    runs = sorted(p.name for p in Path(runs_dir).glob(phase + "-*") if p.is_dir())
    return runs[-1] if runs else None


# ---------------------------------------------------------------- invariants (each returns a list of problems)
def phase_problems(run, phase, golds, expect_tickets=None):
    rule, problems = PHASES[phase], []
    if run.phase != phase:
        problems.append("summary phase is {!r}, want {!r}".format(run.phase, phase))
    want_n = rule["tickets"] if expect_tickets is None else expect_tickets
    if want_n is not None and len(run.input_ids) != want_n:
        problems.append("{} tickets, want {}".format(len(run.input_ids), want_n))
    if not run.input_ids:
        problems.append("run lists no tickets")
    if not set(rule["passes"]) <= set(run.passes):
        problems.append("passes {} lack {}".format("".join(run.passes), rule["passes"]))
    unknown = [i for i in run.input_ids if i not in golds]
    if unknown:
        problems.append("tickets not in manifest: {}".format(", ".join(unknown[:5])))
    if rule["split"]:
        wrong = [i for i in run.input_ids if i in golds and golds[i].get("split") != rule["split"]]
        if wrong:
            problems.append("tickets outside split {}: {}".format(rule["split"], ", ".join(wrong[:5])))
    return problems


def terminal_audit_problems(run):
    problems = []
    for p in run.passes:
        for input_id in run.input_ids:
            n = len(run.terminal(input_id, p))
            if n != 1:
                problems.append("{} pass {}: {} terminal audit rows, want 1".format(input_id, p, n))
    return problems


def issue_problems(run):
    per_key = Counter(label for r in run.tables["jira_issues"] for label in as_list(r.get("labels"))
                      if label.startswith("t4dk-"))
    return ["{}: {} Jira issues, want at most 1".format(key, n) for key, n in sorted(per_key.items()) if n > 1]


def pass_b_problems(run):
    if len(run.passes) < 2:
        return []
    facts, problems = run_facts(run), []
    if facts["new_jira_issues_pass_b"]:
        problems.append("pass B created {} Jira issue(s) (I-8)".format(facts["new_jira_issues_pass_b"]))
    if run.summary.get("new_jira_issues_pass_b", 0):
        problems.append("summary.json new_jira_issues_pass_b = {}".format(run.summary["new_jira_issues_pass_b"]))
    if run.phase in NO_LLM_IN_PASS_B:
        calls = max(facts["llm_calls_pass_b"], int(as_float(run.summary.get("llm_calls_pass_b"))))
        if calls:
            problems.append("pass B made {} model call(s)".format(calls))
    return problems


def pii_problems(run, golds):
    """Every planted value of every ticket in the run, against every outbound text of the run."""
    pairs = outbound(run)
    problems = []
    for input_id in run.input_ids:
        targets = leak_targets((golds.get(input_id) or {}).get("pii"), pairs)
        if targets:
            problems.append("{}: planted PII found in {}".format(input_id, "+".join(targets)))
    return problems


def ledger_problems(run, cost_ledger):
    problems = []
    for call in run.llm_calls():
        if truth(call.get("ok", True)) and not run.rows("ledger", input_of(call), pass_of(call)):
            problems.append("{} pass {}: model call without a ledger row".format(input_of(call), pass_of(call)))
    if not any(r.get("run_id") == run.run_id for r in read_csv(cost_ledger)):
        problems.append("{}: no row for this run".format(cost_ledger))
    return problems


def cap_problems(run, cost_ledger):
    rows = [r for r in read_csv(cost_ledger) if r.get("run_id") == run.run_id]
    cap = run.summary.get("run_usd_cap")
    if cap is None and rows:
        cap = rows[-1].get("run_usd_cap")
    if cap in (None, ""):
        return ["no run_usd_cap recorded in summary.json or the cost ledger"]
    spent = run_facts(run)["usd_run"]
    return ["spend {:.6f} over run_usd_cap {}".format(spent, cap)] if spent > as_float(cap) else []


def forced_faults(run):
    """summary.json `forced_faults` (`id:target:mode[:A|B]`, runner Q-30 (8)) -> [(input_id, pass, target:mode)]."""
    out = []
    for spec in run.summary.get("forced_faults") or ():
        parts = str(spec).split(":")
        run_pass = parts.pop() if len(parts) >= 4 and parts[-1] in ("A", "B") else "A"
        out.append((parts[0], run_pass, ":".join(parts[1:])))
    return out


def smoke_problems(run, golds):
    """GOALS G8: injection -> review, malformed -> rejected, every forced fault fired and left evidence."""
    problems = []
    first = run.passes[0] if run.passes else "A"
    for input_id in run.input_ids:
        gold = golds.get(input_id) or {}
        reason = str(gold.get("review_reason") or "")
        statuses = {p: [r.get("status") for r in run.terminal(input_id, p)] for p in run.passes}
        rows = run.terminal(input_id, first)
        if reason == "injection":
            if statuses.get(first) != ["review"]:
                problems.append("{} pass {}: injection ticket status {}, want review".format(
                    input_id, first, statuses.get(first)))
            if any("auto_routed" in s for s in statuses.values()):
                problems.append("{}: injection ticket was auto-routed".format(input_id))
            if rows and not as_list(rows[-1].get("injection_signals")):
                problems.append("{} pass {}: audit row has no injection_signals".format(input_id, first))
        # A redacted ticket's audit row carries the counts (C-5); smoke 20261013T032636Z wrote {} for every ticket.
        if gold.get("pii") and rows and rows[-1].get("status") in ("auto_routed", "review") \
                and rows[-1].get("pii_counts") in (None, "", "{}"):
            problems.append("{} pass {}: planted PII but audit pii_counts is empty".format(input_id, first))
        if reason.startswith("malformed:") and gold.get("expect_outcome") == "rejected":
            for p, s in statuses.items():
                if s != ["rejected"]:
                    problems.append("{} pass {}: malformed ticket status {}, want rejected".format(input_id, p, s))
    for input_id, run_pass, fault in forced_faults(run):
        fired = [r for r in run.requests
                 if r.get("active_input") == input_id and r.get("pass") == run_pass and r.get("fault") == fault]
        if not fired:
            problems.append("{} pass {}: forced fault {} never fired".format(input_id, run_pass, fault))
            continue
        errors = run.rows("errors", input_id, run_pass)
        reconciled = fault == "jira:commit_then_504" and any(
            r.get("created_via") == "search" for r in run.rows("jira_links", input_id, run_pass))
        if not errors and not reconciled:
            problems.append("{} pass {}: forced fault {} left no errors row (silent drop)".format(
                input_id, run_pass, fault))
    return problems


def logprob_problems(run):
    rows = [r for p in run.passes for i in run.input_ids for r in run.terminal(i, p) if r.get("category")]
    bad = [input_of(r) for r in rows if r.get("conf_source") != "logprobs"]
    return ["{}: confidence source is not logprobs".format(i) for i in bad]


def attack_problems(run, root=ROOT):
    """GOALS G11: attack_results.json lists SEC-01 … SEC-20 once each, result defended|failed|not_run, evidence paths
    that exist, a reason for not_run; SEC-20 (secret scan) is clean."""
    data = read_json(run.dir / ATTACK_RESULTS) or {}
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return ["{} missing or has no results list".format(ATTACK_RESULTS)]
    problems, by_id = [], Counter(r.get("id") for r in results)
    for sec in SEC_IDS:
        if by_id[sec] != 1:
            problems.append("{}: {} result rows, want 1".format(sec, by_id[sec]))
    problems += ["unknown attack id {}".format(i) for i in sorted(set(by_id) - set(SEC_IDS), key=str)]
    for r in results:
        sec = r.get("id")
        if r.get("result") not in ("defended", "failed", "not_run"):
            problems.append("{}: result {!r} not defended|failed|not_run".format(sec, r.get("result")))
        evidence = r.get("evidence") or []
        if not evidence:
            problems.append("{}: no evidence path".format(sec))
        for path in evidence:
            if not (Path(path) if Path(path).is_absolute() else Path(root) / path).exists():
                problems.append("{}: evidence path {} does not exist".format(sec, path))
        if r.get("result") == "not_run" and not str(r.get("reason") or "").strip():
            problems.append("{}: not_run without a reason".format(sec))
    sec20 = [r for r in results if r.get("id") == "SEC-20"]
    if sec20 and (sec20[0].get("result") != "defended" or (sec20[0].get("detail") or {}).get("hits")):
        problems.append("SEC-20: secret scan is not clean")
    return problems


def i8_problems(run, golds):
    """The regression set (HARNESS_SPEC §4) for committed test/attack runs."""
    return terminal_audit_problems(run) + issue_problems(run) + pass_b_problems(run) + pii_problems(run, golds)


def check(run, phase, golds, cost_ledger=COST_LEDGER, expect_tickets=None):
    problems = phase_problems(run, phase, golds, expect_tickets) + i8_problems(run, golds) \
        + ledger_problems(run, cost_ledger) + cap_problems(run, cost_ledger)
    if phase == "slice":
        problems += logprob_problems(run)
    if phase == "smoke":
        problems += smoke_problems(run, golds)
    if phase == "attack":
        problems += attack_problems(run)
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--phase", required=True, choices=sorted(PHASES))
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--latest", action="store_true")
    which.add_argument("--run-id")
    parser.add_argument("--runs-dir", default=str(RUNS_DIR))
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--cost-ledger", default=str(COST_LEDGER))
    parser.add_argument("--expect-tickets", type=int, help="override the phase ticket count (STUB runs)")
    args = parser.parse_args(argv)
    run_id = latest_run(args.phase, args.runs_dir) if args.latest else args.run_id
    if not run_id:
        print("FAIL: no {}-* run under {}".format(args.phase, args.runs_dir))
        return 1
    try:
        run = load_run(run_id, args.runs_dir)
    except FileNotFoundError as exc:
        print("FAIL: {}".format(exc))
        return 1
    problems = check(run, args.phase, load_golds(args.manifest), args.cost_ledger, args.expect_tickets)
    for p in problems:
        print("FAIL: {}: {}".format(run_id, p))
    if problems:
        return 1
    print("ok: {} holds every {} invariant ({} tickets, passes {})".format(run_id, args.phase, len(run.input_ids),
                                                                          "".join(run.passes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
