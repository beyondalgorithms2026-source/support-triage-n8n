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


if __name__ == "__main__":
    unittest.main()
