"""Tests for src/score/check_run.py: the STUB runs hold every invariant; each edit of a temporary copy breaks one."""
import shutil
import tempfile
import unittest
from pathlib import Path

from src.score import check_run
from tests.test_score import (COST_LEDGER, DEV_RUN, MANIFEST, RUNS, TEST_RUN, append_jsonl, append_row, copy_runs,
                              edit_json, edit_rows, quiet)


def run_check(phase, runs_dir=RUNS, cost_ledger=COST_LEDGER, *which):
    which = list(which) or ["--latest"]
    return quiet(check_run.main, ["--phase", phase, "--runs-dir", str(runs_dir), "--manifest", str(MANIFEST),
                                  "--cost-ledger", str(cost_ledger)] + which)


class StubRunsHoldTest(unittest.TestCase):
    def test_test_run_holds(self):
        rc, out = run_check("test", RUNS, COST_LEDGER, "--run-id", TEST_RUN, "--expect-tickets", "12")
        self.assertEqual(rc, 0, out)

    def test_latest_picks_the_phase_run(self):
        rc, out = run_check("dev", RUNS, COST_LEDGER, "--latest", "--expect-tickets", "6")
        self.assertEqual(rc, 0, out)
        self.assertIn(DEV_RUN, out)

    def test_default_ticket_count_applies(self):
        rc, out = run_check("dev", RUNS, COST_LEDGER, "--latest")
        self.assertEqual(rc, 1)
        self.assertIn("6 tickets, want 100", out)

    def test_wrong_phase_and_split(self):
        rc, out = run_check("smoke", RUNS, COST_LEDGER, "--run-id", TEST_RUN, "--expect-tickets", "12")
        self.assertEqual(rc, 1)
        self.assertIn("summary phase is 'test'", out)
        self.assertIn("tickets outside split dev", out)

    def test_no_run_for_phase(self):
        rc, out = run_check("attack")
        self.assertEqual(rc, 1)
        self.assertIn("no attack-* run", out)

    def test_slice_needs_logprob_confidence(self):
        run = check_run.load_run(TEST_RUN, RUNS)
        self.assertEqual(check_run.logprob_problems(run), [])


class BrokenCopyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runs = copy_runs(self.tmp.name)
        self.run = self.runs / TEST_RUN
        self.ledger = Path(shutil.copy(str(COST_LEDGER), str(Path(self.tmp.name) / "cost_ledger.csv")))

    def tearDown(self):
        self.tmp.cleanup()

    def assert_fails(self, text):
        rc, out = run_check("test", self.runs, self.ledger, "--run-id", TEST_RUN, "--expect-tickets", "12")
        self.assertEqual(rc, 1, out)
        self.assertIn(text, out)

    def test_two_issues_one_key(self):
        append_row(self.run / "sink" / "jira_issues.csv", sink_seq=999, replay_input_id="STUB-08",
                   replay_pass="A", key="SUP-99", labels="t4|t4dk-stubk01")
        self.assert_fails("t4dk-stubk01: 2 Jira issues")

    def test_pass_b_issue(self):
        append_row(self.run / "sink" / "jira_issues.csv", sink_seq=999, replay_input_id="STUB-04",
                   replay_pass="B", key="SUP-99", labels="t4|t4dk-stubk04")
        self.assert_fails("pass B created 1 Jira issue")

    def test_pass_b_model_call(self):
        edit_json(self.run / "summary.json", llm_calls_pass_b=2)
        self.assert_fails("pass B made 2 model call")

    def test_missing_terminal_row(self):
        edit_rows(self.run / "sink" / "audit.csv",
                  keep=lambda r: (r["replay_input_id"], r["replay_pass"]) != ("STUB-03", "B"))
        self.assert_fails("STUB-03 pass B: 0 terminal audit rows")

    def test_planted_pii_outbound(self):
        append_row(self.run / "sink" / "slack_messages.csv", sink_seq=999, replay_input_id="STUB-01",
                   replay_pass="A", text="call +1 415-555-0199")
        self.assert_fails("STUB-07: planted PII found in slack")

    def test_planted_pii_in_llm_input(self):
        append_jsonl(self.run / "trace.jsonl", {"input_id": "STUB-07", "pass": "A", "node": "H6 LLM Classify",
                                                "ok": True, "llm_input": "Card 4111 1111 1111 1111"})
        self.assert_fails("planted PII found in llm_input")

    def test_model_call_without_ledger_row(self):
        edit_rows(self.run / "sink" / "ledger.csv", keep=lambda r: r["replay_input_id"] != "STUB-02")
        self.assert_fails("STUB-02 pass A: model call without a ledger row")

    def test_no_cost_ledger_row(self):
        edit_rows(self.ledger, keep=lambda r: r["run_id"] != TEST_RUN)
        self.assert_fails("no row for this run")

    def test_spend_over_cap(self):
        edit_json(self.run / "summary.json", run_usd_cap=0.001)
        self.assert_fails("over run_usd_cap 0.001")


class FakeRun:
    """STUB in-memory run for smoke_problems: audit/errors/jira_links rows and request-log rows by hand."""

    def __init__(self, audit, requests=(), errors=(), links=(), faults=()):
        self.passes, self.input_ids = ["A", "B"], sorted({r["replay_input_id"] for r in audit})
        self.summary = {"forced_faults": list(faults)}
        self.requests = list(requests)
        self.tables = {"audit": list(audit), "errors": list(errors), "jira_links": list(links)}

    def rows(self, table, input_id=None, run_pass=None):
        return [r for r in self.tables[table] if r["replay_input_id"] == input_id and r["replay_pass"] == run_pass]

    def terminal(self, input_id, run_pass):
        return self.rows("audit", input_id, run_pass)


def stub_row(input_id, run_pass, **values):
    return dict(values, replay_input_id=input_id, replay_pass=run_pass)


class SmokeChecksTest(unittest.TestCase):
    GOLDS = {"STUB-I": {"review_reason": "injection"},
             "STUB-M": {"review_reason": "malformed:body_too_long", "expect_outcome": "rejected"},
             "STUB-F": {"review_reason": None}}

    def run_with(self, inj=("review", "duplicate_skip"), mal=("rejected", "rejected"), requests=(), errors=(),
                 links=(), faults=(), signals='["role_override"]'):
        audit = [stub_row("STUB-I", p, status=s, injection_signals=signals) for p, s in zip("AB", inj)]
        audit += [stub_row("STUB-M", p, status=s) for p, s in zip("AB", mal)]
        audit += [stub_row("STUB-F", p, status="review") for p in "AB"]
        return check_run.smoke_problems(FakeRun(audit, requests, errors, links, faults), self.GOLDS)

    def test_clean_smoke_holds(self):
        fired = [{"active_input": "STUB-F", "pass": "A", "fault": "jira:503"}]
        self.assertEqual(self.run_with(requests=fired, errors=[stub_row("STUB-F", "A", code="error:jira")],
                                       faults=["STUB-F:jira:503"]), [])

    def test_injection_and_malformed_routes(self):
        problems = self.run_with(inj=("auto_routed", "duplicate_skip"), mal=("rejected", "error"))
        self.assertTrue(any("injection ticket status ['auto_routed'], want review" in p for p in problems))
        self.assertTrue(any("STUB-I: injection ticket was auto-routed" in p for p in problems))
        self.assertTrue(any("STUB-M pass B: malformed ticket status ['error']" in p for p in problems))

    def test_fault_must_fire_and_leave_evidence(self):
        self.assertEqual(self.run_with(faults=["STUB-F:sink:jira_links:503"]),
                         ["STUB-F pass A: forced fault sink:jira_links:503 never fired"])
        fired = [{"active_input": "STUB-F", "pass": "A", "fault": "slack:503"}]
        self.assertEqual(self.run_with(requests=fired, faults=["STUB-F:slack:503:A"]),
                         ["STUB-F pass A: forced fault slack:503 left no errors row (silent drop)"])

    def test_audit_must_record_signals_and_pii_counts(self):
        self.assertEqual(self.run_with(signals="[]"), ["STUB-I pass A: audit row has no injection_signals"])
        golds = dict(self.GOLDS, **{"STUB-F": {"pii": [{"type": "card", "value": "4111 1111 1111 1111"}]}})
        audit = [stub_row("STUB-F", p, status="review", pii_counts="{}") for p in "AB"]
        self.assertEqual(check_run.smoke_problems(FakeRun(audit), golds),
                         ["STUB-F pass A: planted PII but audit pii_counts is empty"])
        audit = [stub_row("STUB-F", p, status="review", pii_counts='{"card":1}') for p in "AB"]
        self.assertEqual(check_run.smoke_problems(FakeRun(audit), golds), [])

    def test_commit_then_504_reconcile_counts_as_evidence(self):
        fired = [{"active_input": "STUB-F", "pass": "A", "fault": "jira:commit_then_504"}]
        links = [stub_row("STUB-F", "A", created_via="search")]
        self.assertEqual(self.run_with(requests=fired, links=links, faults=["STUB-F:jira:commit_then_504"]), [])


if __name__ == "__main__":
    unittest.main()
