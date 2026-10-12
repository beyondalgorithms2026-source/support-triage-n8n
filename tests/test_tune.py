"""Tests for src/score/tune.py (HARNESS_SPEC §3) on the STUB runs and on in-memory sweeps."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.score import tune
from tests.test_score import DEV_RUN, MANIFEST, RUNS, TEST_RUN, quiet


def items(*pairs):
    return [(conf, ok) for conf, ok in pairs]


class SweepTest(unittest.TestCase):
    def test_lowest_tau_with_target_and_min_selected(self):
        data = items((0.52, False), (0.71, True), (0.80, True), (0.86, True), (0.91, True), (0.96, True))
        rows, tau = tune.sweep(data, "category", "bug", 0.95)
        self.assertEqual(tau, 0.55)                       # 5 selected, 5 correct
        self.assertEqual(len(rows), len(tune.TAUS))
        self.assertEqual((rows[0]["n_selected"], rows[0]["n_correct"]), (6, 5))
        self.assertAlmostEqual(rows[0]["coverage"], 1.0)

    def test_too_few_selected_means_always_human(self):
        _, tau = tune.sweep(items(*[(0.99, True)] * 4), "category", "bug", 0.95)
        self.assertEqual(tau, tune.NEVER)

    def test_precision_below_target_means_always_human(self):
        _, tau = tune.sweep(items(*([(0.99, True)] * 9 + [(0.99, False)])), "category", "bug", 0.95)
        self.assertEqual(tau, tune.NEVER)

    def test_empty_class(self):
        rows, tau = tune.sweep([], "category", "other", 0.95)
        self.assertEqual(tau, tune.NEVER)
        self.assertIsNone(rows[0]["precision"])

    def test_wilson_lower_bound(self):
        self.assertAlmostEqual(tune.wilson_low(5, 5), 0.6489, places=4)
        self.assertAlmostEqual(tune.wilson_low(9, 10), 0.6523, places=4)
        self.assertIsNone(tune.wilson_low(0, 0))

    def test_rule_reasons_leave_the_sweep(self):
        row = {"category_hat": "bug", "conf_category": "0.9"}
        self.assertEqual(len(tune.eligible([dict(row, _reasons=["threshold:category", "policy:x"])])), 1)
        self.assertEqual(tune.eligible([dict(row, _reasons=["R3"])]), [])
        self.assertEqual(tune.eligible([dict(row, category_hat="", _reasons=[])]), [])


class TuneCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.thresholds, self.sweep = self.dir / "thresholds.json", self.dir / "threshold_sweep.csv"
        self.workflow = self.dir / "t4-triage.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_tune(self, *args):
        return quiet(tune.main, list(args) + ["--runs-dir", str(RUNS), "--manifest", str(MANIFEST),
                                              "--thresholds", str(self.thresholds), "--sweep", str(self.sweep),
                                              "--workflow", str(self.workflow)])

    def test_refuses_test_split_run(self):
        rc, out = self.run_tune("--run-id", TEST_RUN)
        self.assertNotEqual(rc, 0)
        self.assertIn("REFUSED", out)
        self.assertFalse(self.thresholds.exists())
        self.assertFalse(self.sweep.exists())

    def test_dev_run_thresholds_and_sweep(self):
        rc, _ = self.run_tune("--run-id", DEV_RUN)
        self.assertEqual(rc, 0)
        doc = json.loads(self.thresholds.read_text(encoding="utf-8"))
        self.assertEqual((doc["source_run_id"], doc["split"]), (DEV_RUN, "dev"))
        self.assertEqual(doc["tau_category"]["billing"], 0.50)
        self.assertEqual(doc["tau_category"]["feature"], tune.NEVER)
        self.assertEqual((doc["tau_category"]["privacy"], doc["tau_category"]["other"]), (tune.NEVER, tune.NEVER))
        self.assertEqual(doc["tau_priority"], {"P1": tune.NEVER, "P2": tune.NEVER, "P3": 0.50, "P4": tune.NEVER})
        self.assertEqual(doc["global_tau"], 0.60)   # the wrong feature prediction at 0.55 holds the pool back
        with self.sweep.open(newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0], tune.SWEEP_HEADER)
        self.assertEqual(len(rows) - 1, 156)        # 13 classes x 12 tau values (G9 acceptance)
        self.assertIn(["category", "billing", "0.50", "5", "5", "1.0000", "1.0000", "0.6489"], rows)

    def test_apply_without_workflow_is_a_noop(self):
        self.run_tune("--run-id", DEV_RUN)
        rc, out = self.run_tune("--apply")
        self.assertEqual(rc, 0)
        self.assertIn("does not exist yet", out)
        self.assertFalse(self.workflow.exists())

    def test_apply_then_verify(self):
        self.run_tune("--run-id", DEV_RUN)
        self.workflow.write_text(json.dumps({"nodes": [
            {"name": "0. Config", "type": "n8n-nodes-base.set", "parameters": {"assignments": {"assignments": [
                {"id": "tau_category", "name": "tau_category", "value": "{}", "type": "object"},
                {"id": "llm_model", "name": "llm_model", "value": "gpt-4o-mini-2024-07-18", "type": "string"}]}}}]}),
            encoding="utf-8")
        self.assertEqual(self.run_tune("--apply")[0], 0)
        values = tune.config_values(tune.config_node(json.loads(self.workflow.read_text(encoding="utf-8"))))
        doc = json.loads(self.thresholds.read_text(encoding="utf-8"))
        self.assertEqual((values["tau_category"], values["tau_priority"]), (doc["tau_category"], doc["tau_priority"]))
        self.assertEqual(values["llm_model"], "gpt-4o-mini-2024-07-18")
        self.assertEqual(self.run_tune("--verify")[0], 0)

    def test_verify_detects_drift(self):
        self.run_tune("--run-id", DEV_RUN)
        self.assertEqual(self.run_tune("--verify")[0], 0)
        doc = json.loads(self.thresholds.read_text(encoding="utf-8"))
        doc["tau_category"]["billing"] = 0.40
        self.thresholds.write_text(json.dumps(doc), encoding="utf-8")
        rc, out = self.run_tune("--verify")
        self.assertEqual(rc, 1)
        self.assertIn("tau_category differs", out)

    def test_verify_detects_config_mismatch(self):
        self.run_tune("--run-id", DEV_RUN)
        self.workflow.write_text(json.dumps({"nodes": [{"name": "0. Config", "parameters": {}}]}), encoding="utf-8")
        rc, out = self.run_tune("--verify")
        self.assertEqual(rc, 1)
        self.assertIn("0. Config", out)


if __name__ == "__main__":
    unittest.main()
