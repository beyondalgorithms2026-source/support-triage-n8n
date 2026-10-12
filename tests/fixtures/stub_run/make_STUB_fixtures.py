"""STUB fixture builder for the G3 scorer tests. Writes hand-chosen STUB values, not run evidence (I-6 does not apply).

    python3 tests/fixtures/stub_run/make_STUB_fixtures.py

Writes gold/, STUB_manifest.csv, STUB_cost_ledger.csv and two runs under runs/:
- test-local-STUB (12 test tickets, passes A then B): nine failure codes fire on known tickets (tests/test_score.py);
  every check_run invariant holds.
- dev-local-STUB (6 dev tickets, pass A, tuning mode): billing tunes to 0.50, global to 0.60 (tests/test_tune.py).
"""
import csv
import json
from pathlib import Path

B = Path(__file__).resolve().parent
STAMP = ["sink_seq", "sink_ts", "replay_input_id", "replay_pass"]
COLS = {
    "audit": STAMP + ("run_id,input_ref,execution_id,stage,node,ok,status,dedupe_key,content_sha256,category,"
                      "conf_category,priority,conf_priority,urgency,conf_source,reasons,pii_counts,injection_signals,"
                      "truncated,issue_key,notify_ok,capped,tokens_in,tokens_out,usd,duration_ms").split(","),
    "ledger": STAMP + "run_id,input_ref,day,model,tokens_in,tokens_out,usd".split(","),
    "review_queue": STAMP + ("run_id,dedupe_key,reasons,category,conf_category,priority,conf_priority,urgency,"
                             "redacted_subject,redacted_body").split(","),
    "jira_links": STAMP + "run_id,dedupe_key,issue_key,category,priority,created_via".split(","),
    "errors": STAMP + "run_id,input_ref,stage,node,code,message".split(","),
    "jira_issues": STAMP + "key,project,issuetype,summary,description_text,labels,priority,created_seq".split(","),
    "slack_messages": STAMP + "channel,text,unfurl_links".split(","),
}
MODEL = "gpt-4o-mini-2024-07-18"
JIRA_PRIORITY = {"P1": "Highest", "P2": "High", "P3": "Medium", "P4": "Low"}
NO_HAT = ("", "", "", "", "")


def usd(tokens_in, tokens_out):
    return round(tokens_in * 0.15 / 1e6 + tokens_out * 0.60 / 1e6, 10)


def gold(iid, split, bucket, cat, pri, urg, outcome, key, must=False, reason=None, dup=None, pii=(), inj=None,
         fault=None):
    return {"STUB": True, "input_id": iid, "synthetic": True, "split": split, "label_bucket": bucket,
            "hard_case": None, "expected": {"category": cat, "priority": pri, "urgency": urg},
            "expect_outcome": outcome, "must_review": must, "review_reason": reason, "dedupe_key": key,
            "content_sha256": None, "duplicate_of": dup, "pii": list(pii), "injection": inj, "fault": fault,
            "label_notes": "STUB ticket for scorer tests", "generator": {"seed": 0, "template": "STUB", "version": "STUB"}}


GOLDS = [
    gold("STUB-01", "test", "clean", "billing", "P3", "medium", "auto_route", "stubk01"),
    gold("STUB-02", "test", "clean", "bug", "P2", "high", "auto_route", "stubk02",
         fault={"target": "slack", "mode": "503", "pass": "A"}),
    gold("STUB-03", "test", "clean", "outage", "P1", "high", "auto_route", "stubk03"),
    gold("STUB-04", "test", "clean", "howto", "P3", "low", "auto_route", "stubk04"),
    gold("STUB-05", "test", "clean", "privacy", "P3", "medium", "review", "stubk05", True, "policy_class"),
    gold("STUB-06", "test", "injection", "feature", "P4", "low", "review", "stubk06", True, "injection",
         inj={"kind": "direct", "location": "body", "goal": "force_category",
              "target": {"category": "outage", "priority": "P1"}}),
    gold("STUB-07", "test", "pii", "billing", "P2", "high", "auto_route", "stubk07",
         pii=[{"type": "card", "value": "4111 1111 1111 1111"}, {"type": "phone", "value": "+1 415-555-0199"},
              {"type": "name", "value": "Stub Example Person"}]),
    gold("STUB-08", "test", "duplicate", "billing", "P3", "medium", "duplicate_skip", "stubk01", dup="STUB-01"),
    gold("STUB-09", "test", "duplicate", "bug", "P2", "high", "duplicate_skip", "stubk09", dup="STUB-02"),
    gold("STUB-10", "test", "malformed", "bug", "P3", "low", "rejected", "stubk10", True, "malformed:empty_content"),
    gold("STUB-11", "test", "clean", "access", "P2", "high", "auto_route", "stubk11"),
    gold("STUB-12", "test", "hard", "bug", "P2", "medium", "auto_route", "stubk12"),
] + [gold("STUB-2%d" % i, "dev", "clean", "billing", "P3", "medium", "auto_route", "stubk2%d" % i)
     for i in range(1, 6)] + [
    gold("STUB-26", "dev", "clean", "howto", "P3", "low", "auto_route", "stubk26"),
]
G = {g["input_id"]: g for g in GOLDS}

# Test run, pass A. hat = (category, conf_category, priority, conf_priority, urgency).
TEST_TICKETS = [
    {"id": "STUB-01", "status": "auto_routed", "hat": ("billing", "0.97", "P3", "0.93", "medium"), "tok": (900, 20),
     "dur": 2100, "issue_key": "SUP-1"},
    {"id": "STUB-02", "status": "auto_routed", "hat": ("access", "0.91", "P2", "0.90", "high"), "tok": (950, 20),
     "dur": 2300, "issue_key": "SUP-2"},
    {"id": "STUB-03", "status": "auto_routed", "hat": ("outage", "0.96", "P2", "0.88", "high"), "tok": (870, 20),
     "dur": 2000, "issue_key": "SUP-3"},
    {"id": "STUB-04", "status": "review", "hat": ("howto", "0.62", "P3", "0.70", "low"), "tok": (800, 20),
     "dur": 1900, "reasons": "threshold:category|threshold:priority"},
    {"id": "STUB-05", "status": "review", "hat": ("privacy", "0.99", "P3", "0.95", "medium"), "tok": (820, 20),
     "dur": 2500, "reasons": "policy:always_review"},
    {"id": "STUB-06", "status": "auto_routed", "hat": ("outage", "0.94", "P1", "0.92", "high"), "tok": (880, 20),
     "dur": 2200, "issue_key": "SUP-4"},
    {"id": "STUB-07", "status": "auto_routed", "hat": ("billing", "0.98", "P2", "0.91", "high"), "tok": (3400, 20),
     "dur": 3100, "issue_key": "SUP-5", "pii_counts": "card:1|phone:1|name:1",
     "llm_input": "Card [CARD_1] was charged twice. Call me at [PHONE_1]. [NAME_1]"},
    {"id": "STUB-08", "status": "duplicate_skip", "dur": 300, "issue_key": "SUP-1"},
    {"id": "STUB-09", "status": "auto_routed", "hat": ("bug", "0.95", "P2", "0.93", "high"), "tok": (940, 20),
     "dur": 2050, "issue_key": "SUP-6"},
    {"id": "STUB-10", "status": "rejected", "dur": 150, "reasons": "reject:intake"},
    {"id": "STUB-11", "status": "review", "tok": (910, 20), "dur": 1800, "reasons": "schema_miss"},
    {"id": "STUB-12", "status": "review", "hat": ("outage", "0.80", "P1", "0.75", "high"), "tok": (860, 20),
     "dur": 2000, "reasons": "threshold:category"},
]
TEST_ISSUES = {
    "STUB-01": ("SUP-1", "Redacted body [EMAIL_1]"), "STUB-02": ("SUP-2", "Redacted body"),
    "STUB-03": ("SUP-3", "Redacted body"), "STUB-06": ("SUP-4", "Redacted body"),
    "STUB-07": ("SUP-5", "Card [CARD_1] was charged twice. Call me at [PHONE_1]. [NAME_1]"),
    "STUB-09": ("SUP-6", "Redacted body"),
}
# STUB-02 has a Slack fault and STUB-03 has none: only STUB-03 is a notify_gap.
TEST_SLACK = {
    "STUB-01": "C-TRIAGE", "STUB-06": "C-TRIAGE", "STUB-07": "C-TRIAGE", "STUB-09": "C-TRIAGE",
    "STUB-04": "C-REVIEW", "STUB-11": "C-REVIEW", "STUB-12": "C-REVIEW",
}
TEST_QUEUE = ("STUB-04", "STUB-05", "STUB-10", "STUB-11", "STUB-12")
TEST_ERRORS = {"STUB-10": ("reject:intake", "intake", "H1 Intake Guard", "empty subject and body"),
               "STUB-05": ("error:slack", "approve", "H15s Slack Review Post", "503 after retries")}
TEST_REQUESTS = [{"STUB": True, "ts": "STUB", "method": "POST", "path": "/api/chat.postMessage", "status": 503,
                  "active_input": "STUB-05", "pass": "A", "target": "slack",
                  "body": {"channel": "C-REVIEW", "text": "Review: [privacy] Redacted subject STUB-05"}}] * 4 + [
    {"STUB": True, "ts": "STUB", "method": "POST", "path": "/rest/api/3/issue", "status": 201,
     "active_input": "STUB-07", "pass": "A", "target": "jira",
     "body": {"fields": {"summary": "[billing] Redacted subject STUB-07", "description": TEST_ISSUES["STUB-07"][1]}}},
]

# Dev run (tuning mode, every τ = 0): five correct billing/P3 predictions and one wrong feature/P4 at 0.55.
DEV_TICKETS = [{"id": "STUB-2%d" % i, "status": "auto_routed", "hat": ("billing", c, "P3", pc, "medium"),
                "tok": (900, 20), "dur": 2000, "issue_key": "SUP-%d" % i}
               for i, c, pc in ((1, "0.90", "0.91"), (2, "0.92", "0.93"), (3, "0.95", "0.96"), (4, "0.97", "0.94"),
                                (5, "0.99", "0.92"))]
DEV_TICKETS.append({"id": "STUB-26", "status": "auto_routed", "hat": ("feature", "0.55", "P4", "0.80", "low"),
                    "tok": (900, 20), "dur": 2000, "issue_key": "SUP-6"})


def build(run_id, phase, split, passes, tickets, issues, slack, queue, errors, requests):
    run_dir = B / "runs" / run_id
    (run_dir / "sink").mkdir(parents=True, exist_ok=True)
    tables = {name: [] for name in COLS}
    trace = []
    seq = [0]

    def add(table, iid, run_pass, **values):
        seq[0] += 1
        row = {"sink_seq": seq[0], "sink_ts": "STUB", "replay_input_id": iid, "replay_pass": run_pass}
        row.update(values)
        tables[table].append(row)

    for n_pass, run_pass in enumerate(passes):
        for n, t in enumerate(tickets, 1):
            iid, key = t["id"], G[t["id"]]["dedupe_key"]
            execution_id = 100 * (n_pass + 1) + n
            if run_pass != "A":
                status = "rejected" if t["status"] == "rejected" else "duplicate_skip"
                add("audit", iid, run_pass, run_id=run_id, input_ref=iid, execution_id=execution_id, stage="record",
                    node="H16 Audit", ok=1, status=status, dedupe_key=key, content_sha256="STUB", truncated=0,
                    notify_ok=0, capped=0, tokens_in=0, tokens_out=0, usd=0, duration_ms=200)
                continue
            hat = t.get("hat", NO_HAT)
            tokens_in, tokens_out = t.get("tok", (0, 0))
            cost = usd(tokens_in, tokens_out) if tokens_in else 0
            if tokens_in:
                add("ledger", iid, run_pass, run_id=run_id, input_ref=iid, day="STUB", model=MODEL,
                    tokens_in=tokens_in, tokens_out=tokens_out, usd=cost)
                trace.append({"STUB": True, "run_id": run_id, "pass": run_pass, "input_id": iid,
                              "execution_id": execution_id, "node": "H6 LLM Classify", "stage": "classify", "ok": True,
                              "tokens_in": tokens_in, "tokens_out": tokens_out, "usd": cost,
                              "duration_ms": t["dur"] - 300,
                              "llm_input": t.get("llm_input", "Redacted ticket text for " + iid)})
            if iid in errors:
                code, stage, node, message = errors[iid]
                add("errors", iid, run_pass, run_id=run_id, input_ref=iid, stage=stage, node=node, code=code,
                    message=message)
            if iid in queue:
                add("review_queue", iid, run_pass, run_id=run_id, dedupe_key=key, reasons=t.get("reasons", ""),
                    category=hat[0], conf_category=hat[1], priority=hat[2], conf_priority=hat[3], urgency=hat[4],
                    redacted_subject="Redacted subject " + iid, redacted_body="Redacted body " + iid)
            if iid in issues:
                issue_key, description = issues[iid]
                add("jira_issues", iid, run_pass, key=issue_key, project="SUP", issuetype="Task",
                    summary="[{}] Redacted subject {}".format(hat[0], iid), description_text=description,
                    labels="t4|t4dk-{}|t4-cat-{}".format(key, hat[0]), priority=JIRA_PRIORITY[hat[2]],
                    created_seq=issue_key.split("-")[1])
                add("jira_links", iid, run_pass, run_id=run_id, dedupe_key=key, issue_key=issue_key,
                    category=hat[0], priority=hat[2], created_via="create")
            if iid in slack:
                add("slack_messages", iid, run_pass, channel=slack[iid],
                    text="{} [{}] {} Redacted subject {}".format(t.get("issue_key", "Review:"), hat[0], hat[2], iid),
                    unfurl_links="false")
            add("audit", iid, run_pass, run_id=run_id, input_ref=iid, execution_id=execution_id, stage="record",
                node="H16 Audit", ok=1, status=t["status"], dedupe_key=key, content_sha256="STUB", category=hat[0],
                conf_category=hat[1], priority=hat[2], conf_priority=hat[3], urgency=hat[4],
                conf_source="logprobs" if tokens_in else "", reasons=t.get("reasons", ""),
                pii_counts=t.get("pii_counts", ""), injection_signals="", truncated=0,
                issue_key=t.get("issue_key", ""), notify_ok=int(iid in slack and t["status"] == "auto_routed"),
                capped=0, tokens_in=tokens_in, tokens_out=tokens_out, usd=cost, duration_ms=t["dur"])
    for name, cols in COLS.items():
        with (run_dir / "sink" / (name + ".csv")).open("w", newline="", encoding="utf-8") as f:
            f.write("# STUB {} table for {} (synthetic)\n".format(name, run_id))
            writer = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
            writer.writeheader()
            writer.writerows(tables[name])
    with (run_dir / "trace.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in trace)
    with (run_dir / "sink" / "requests.jsonl").open("w", encoding="utf-8") as f:
        # Marker row has no input id, so the scorer never selects it for a ticket.
        f.write(json.dumps({"STUB": True, "note": "STUB requests log for {} (synthetic)".format(run_id)}) + "\n")
        f.writelines(json.dumps(r) + "\n" for r in requests)
    summary = {"STUB": True, "run_id": run_id, "phase": phase, "split": split, "target": "local", "passes": passes,
               "model": MODEL, "n8n_version": "STUB", "workflow_sha256": "STUB", "thresholds_sha256": "STUB",
               "prompt_sha256": "STUB", "input_ids": [t["id"] for t in tickets], "run_usd_cap": 0.25,
               "max_model_chars": 6000, "new_jira_issues_pass_b": 0, "llm_calls_pass_b": 0}
    (run_dir / "summary.json").write_text(json.dumps(summary) + "\n", encoding="utf-8")
    ledger = tables["ledger"]
    total = round(sum(r["usd"] for r in ledger), 10)
    return [run_id, phase, "local", "STUB", "STUB", MODEL, len(ledger), sum(r["tokens_in"] for r in ledger),
            sum(r["tokens_out"] for r in ledger), total, 0.25, 0, len(tickets), round(total / len(tickets) * 1000, 10)]


def main():
    (B / "gold").mkdir(parents=True, exist_ok=True)
    for g in GOLDS:
        (B / "gold" / (g["input_id"] + ".json")).write_text(json.dumps(g) + "\n", encoding="utf-8")
    with (B / "STUB_manifest.csv").open("w", newline="", encoding="utf-8") as f:
        f.write("# STUB manifest for G3 scorer tests (synthetic)\n")
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow("input_id,split,label_bucket,category,priority,urgency,expect_outcome,gold_path".split(","))
        for g in GOLDS:
            e = g["expected"]
            writer.writerow([g["input_id"], g["split"], g["label_bucket"], e["category"], e["priority"],
                             e["urgency"], g["expect_outcome"], "tests/fixtures/stub_run/gold/{}.json".format(g["input_id"])])
    dev_issues = {t["id"]: (t["issue_key"], "Redacted body") for t in DEV_TICKETS}
    ledger_rows = [
        build("test-local-STUB", "test", "test", "AB", TEST_TICKETS, TEST_ISSUES, TEST_SLACK, TEST_QUEUE,
              TEST_ERRORS, TEST_REQUESTS),
        build("dev-local-STUB", "dev", "dev", "A", DEV_TICKETS, dev_issues,
              {t["id"]: "C-TRIAGE" for t in DEV_TICKETS}, (), {}, []),
    ]
    with (B / "STUB_cost_ledger.csv").open("w", newline="", encoding="utf-8") as f:
        f.write("# STUB cost ledger for G3 check_run tests (synthetic)\n")
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(("run_id,run_phase,target,started_utc,ended_utc,model,llm_calls,tokens_in,tokens_out,usd,"
                         "run_usd_cap,capped_inputs,tickets,usd_per_1k_tickets").split(","))
        writer.writerows(ledger_rows)
    print("STUB fixtures written under {}".format(B))


if __name__ == "__main__":
    main()
