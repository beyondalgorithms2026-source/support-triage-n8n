"""G11 attack run tests: ticket choice, burst tickets, secret scan, the attack_results check, and one fake attack run
through the real runner and sink (fake n8n, no model calls, no network beyond localhost)."""
import csv
import functools
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.checks.static_checks import check_file
from src.common.inject import scan
from src.replay import attacks, run
from src.score import check_run
from src.score.score import MANIFEST, ROOT, Run, load_golds, read_csv
from tests.test_replay import ENV, HANDLER, WORKFLOW, FakeWorkflow, RecordingSink


class TicketChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = read_csv(MANIFEST)
        cls.golds = load_golds()

    def test_select_ids_takes_attack_buckets_and_duplicate_originals_in_manifest_order(self):
        ids = attacks.select_ids(self.rows, lambda row: self.golds[row["input_id"]])
        buckets = {r["input_id"] for r in self.rows if r["label_bucket"] in attacks.ATTACK_BUCKETS}
        originals = {g["duplicate_of"] for g in self.golds.values() if g.get("duplicate_of")}
        self.assertEqual(set(ids), buckets | originals)
        self.assertEqual(ids, [r["input_id"] for r in self.rows if r["input_id"] in set(ids)])
        for g in self.golds.values():
            if g.get("duplicate_of"):
                self.assertLess(ids.index(g["duplicate_of"]), ids.index(g["input_id"]))
        self.assertEqual({self.golds[i]["split"] for i in ids}, {"dev", "test"})

    def test_write_path_tickets_have_the_named_roles(self):
        ids, roles = attacks.write_path_ids(self.golds)
        retry = self.golds[roles["retry"]]
        self.assertEqual(retry["ticket"]["source_message_id"],
                         self.golds[retry["duplicate_of"]]["ticket"]["source_message_id"])
        self.assertEqual(self.golds[roles["commit_then_504"]]["fault"]["mode"], "commit_then_504")
        self.assertEqual(self.golds[roles["lost_link"]]["fault"]["target"], "sink:jira_links")
        self.assertEqual(self.golds[roles["search_lag"]]["fault"]["mode"], "search_lag")
        for role in ("retry", "search_lag"):
            original = self.golds[roles[role]]["duplicate_of"]
            self.assertLess(ids.index(original), ids.index(roles[role]))

    def test_burst_tickets_are_distinct_near_cap_and_scan_clean(self):
        tickets = attacks.burst_tickets("sec12", 6000, "2026-10-13T00:00:00Z")
        self.assertEqual(len(tickets), attacks.BURST_SIZE)
        for key in ("source_message_id", "subject", "body_text"):
            self.assertEqual(len({t["ticket"][key] for t in tickets}), len(tickets))
        for t in tickets:
            body = t["ticket"]["body_text"]
            self.assertTrue(5700 <= len(body) <= 6000, len(body))
            self.assertEqual(scan(t["ticket"]["subject"], body), [])
            self.assertTrue(t["ticket"]["from_email"].endswith("@example.com"))
        self.assertEqual(attacks.burst_tickets("sec12", 6000, "x"), attacks.burst_tickets("sec12", 6000, "x"))

    def test_max_in_window(self):
        ts = ["2026-10-13T00:00:{:02d}+00:00".format(s) for s in (0, 10, 59)] + ["2026-10-13T00:01:00+00:00"]
        self.assertEqual(attacks.max_in_window(ts), 3)
        self.assertEqual(attacks.max_in_window([]), 0)

    def test_committed_workflow_paths_stay_inside_the_sandbox_allow_list(self):
        paths = check_file(str(ROOT / "workflows" / "t4-triage.json"))["paths"]
        self.assertTrue(paths)
        for p in paths:
            allowed = attacks.JIRA_PATHS if p["target"] == "jira" else attacks.SLACK_PATHS
            self.assertIn((p["method"], p["path"]), allowed)


class SecretScanTests(unittest.TestCase):
    def test_reports_names_and_lines_never_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "evals").mkdir()
            (root / "src" / "checks").mkdir(parents=True)
            (root / "evals" / "a.txt").write_text("ok\nleaked tok-value-123456 here\n", encoding="utf-8")
            (root / "evals" / "b.txt").write_text("Bearer " + "A" * 24 + "\n", encoding="utf-8")
            (root / "src" / "checks" / "static_checks.py").write_text("Bearer " + "B" * 24 + "\n", encoding="utf-8")
            result = attacks.secret_scan(root, {"SINK_TOKEN": "tok-value-123456", "SHORT": "abc"})
        self.assertEqual(result["env_names"], ["SINK_TOKEN"])
        self.assertIn({"file": "evals/a.txt", "line": 2, "env_name": "SINK_TOKEN"}, result["hits"])
        self.assertEqual([h["file"] for h in result["hits"] if "pattern" in h], ["evals/b.txt"])
        self.assertNotIn("tok-value-123456", json.dumps(result))


class AttackResultsCheckTests(unittest.TestCase):
    def test_attack_problems_bite(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "attack-local-20261013T000000Z-stub"
            run_dir.mkdir()
            (run_dir / "summary.json").write_text("{}", encoding="utf-8")
            (run_dir / "proof.txt").write_text("STUB\n", encoding="utf-8")
            good = str(run_dir / "proof.txt")
            results = [{"id": s, "result": "defended", "evidence": [good]} for s in attacks.SEC_IDS[:18]]
            results += [{"id": "SEC-19", "result": "not_run", "evidence": [str(run_dir / "missing.json")]},
                        {"id": "SEC-20", "result": "defended", "evidence": [good], "detail": {"hits": [{"file": "x"}]}},
                        {"id": "SEC-05", "result": "maybe", "evidence": []}]
            (run_dir / check_run.ATTACK_RESULTS).write_text(json.dumps({"results": results}), encoding="utf-8")
            problems = check_run.attack_problems(Run(run_dir))
            (run_dir / check_run.ATTACK_RESULTS).unlink()
            missing = check_run.attack_problems(Run(run_dir))
        self.assertIn("SEC-05: 2 result rows, want 1", problems)
        self.assertIn("SEC-05: result 'maybe' not defended|failed|not_run", problems)
        self.assertIn("SEC-05: no evidence path", problems)
        self.assertTrue(any(p.startswith("SEC-19: evidence path") for p in problems))
        self.assertIn("SEC-19: not_run without a reason", problems)
        self.assertIn("SEC-20: secret scan is not clean", problems)
        self.assertEqual(missing, ["attack_results.json missing or has no results list"])

    def test_committed_attack_runs_hold(self):
        runs = sorted(p for p in (ROOT / "evals" / "runs").glob("attack-*") if p.is_dir())
        if not runs:
            self.skipTest("no committed attack run yet")
        for run_dir in runs:
            with self.subTest(run=run_dir.name):
                self.assertEqual(check_run.attack_problems(Run(run_dir)), [])


class FakeAttackRunTests(unittest.TestCase):
    """The real runner and sink with a fake n8n: segments, probe, scan and results land in one run folder."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        workflow = json.loads(json.dumps(WORKFLOW))
        assignments = workflow["nodes"][1]["parameters"]["assignments"]["assignments"]
        assignments += [{"name": "llm_max_rpm", "value": 30, "type": "number"},
                        {"name": "tuning_mode", "value": False, "type": "boolean"}]
        self.workflow = self.root / "t4-triage.json"
        self.workflow.write_text(json.dumps(workflow), encoding="utf-8")
        self.handler = self.root / "t4-error-handler.json"
        self.handler.write_text(json.dumps(HANDLER), encoding="utf-8")
        self.manifest = self.root / "manifest.csv"
        msg = "<{}@mail.example.com>".format
        specs = [  # input_id, bucket, extra gold fields
            ("t4-901", "clean", {"fault": {"target": "jira", "mode": "commit_then_504", "pass": "A"}}),
            ("t4-902", "clean", {"fault": {"target": "sink:jira_links", "mode": "503", "pass": "A"}}),
            ("t4-903", "clean", {}), ("t4-904", "duplicate", {"duplicate_of": "t4-903", "message_id": msg("t4-903")}),
            ("t4-905", "clean", {}),
            ("t4-906", "duplicate", {"duplicate_of": "t4-905",
                                     "fault": {"target": "jira", "mode": "search_lag", "pass": "A"}}),
            ("t4-907", "injection", {"injection": {"kind": "direct", "location": "body", "goal": "force_category",
                                                   "target": {"category": "outage"}}}),
            ("t4-908", "pii", {"pii": [{"type": "card", "value": "4111 1111 1111 1111"}]}),
            ("t4-909", "malformed", {"review_reason": "malformed:body_too_long", "expect_outcome": "rejected"}),
        ]
        with self.manifest.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=("input_id", "split", "label_bucket", "category", "priority",
                                                   "urgency", "expect_outcome", "gold_path"))
            writer.writeheader()
            for input_id, bucket, extra in specs:
                gold = {"input_id": input_id, "split": "dev", "label_bucket": bucket, "dedupe_key": "k" + input_id,
                        "expected": {"category": "billing", "priority": "P3", "urgency": "low"},
                        "expect_outcome": extra.get("expect_outcome", "auto_route"), "fault": extra.get("fault"),
                        "duplicate_of": extra.get("duplicate_of"), "injection": extra.get("injection"),
                        "pii": extra.get("pii"), "review_reason": extra.get("review_reason"),
                        "ticket": {"source": "email", "subject": "invoice " + input_id, "from_email": "d@example.com",
                                   "source_message_id": extra.get("message_id") or msg(input_id), "body_text": "b"}}
                path = self.root / (input_id + ".json")
                path.write_text(json.dumps(gold), encoding="utf-8")
                writer.writerow({"input_id": input_id, "split": "dev", "label_bucket": bucket, "category": "billing",
                                 "priority": "P3", "urgency": "low", "expect_outcome": gold["expect_outcome"],
                                 "gold_path": str(path)})
        self.ledger = self.root / "cost_ledger.csv"
        RecordingSink.instances = []
        real_probe, real_scan = attacks.auth_probe, attacks.secret_scan
        self.patches = [
            mock.patch.object(run, "LocalSink", RecordingSink),
            mock.patch.object(attacks, "BURST_SIZE", 3),
            mock.patch.object(attacks, "post", return_value=403),
            mock.patch.object(attacks, "auth_probe", side_effect=functools.partial(real_probe, sleeper=lambda s: None)),
            mock.patch.object(attacks, "secret_scan", side_effect=lambda root, values: real_scan(self.root, values)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def test_attack_run_writes_segments_probe_scan_and_results(self):
        fake = FakeWorkflow()
        args = run.build_parser().parse_args(["run", "--phase", "attack", "--config-override", "llm_max_rpm=120"])
        args.workflow, args.handler_workflow, args.manifest = str(self.workflow), str(self.handler), str(self.manifest)
        args.runs_dir, args.cost_ledger, args.sink_host, args.sink_port = str(self.root / "runs"), str(self.ledger), \
            "127.0.0.1", 0
        with mock.patch.object(run, "submit", side_effect=fake.submit):
            run_dir = run.run_replay(args, fake, env=dict(ENV))
        # main segment = attack buckets + the originals of duplicates; three isolated segments follow
        summary = json.loads((run_dir / "summary.json").read_text())
        self.assertEqual(summary["input_ids"], ["t4-903", "t4-904", "t4-905", "t4-906", "t4-907", "t4-908", "t4-909"])
        self.assertEqual([s["name"] for s in summary["segments"]], ["sec12", "sec13", "writes"])
        self.assertEqual(fake.calls.count(("ready",)), 4)
        configs = [run.config_values(w) for w in fake.imported if w["id"] == "t4TriageFlow0001"]
        self.assertEqual([c["llm_max_rpm"] for c in configs], [120, 30, 30, 120])
        self.assertEqual([c["run_usd_cap"] for c in configs], [0.25, 0.01, 0.25, 0.25])
        self.assertEqual([c["daily_usd_cap"] for c in configs], [1.0, 1.0, 0.01, 1.0])
        self.assertEqual([c["tuning_mode"] for c in configs], [False, False, False, True])
        writes = Run(run_dir / "segments" / "writes")
        self.assertEqual(writes.input_ids, ["t4-901", "t4-902", "t4-903", "t4-904", "t4-905", "t4-906"])
        self.assertEqual(writes.passes, ["A", "B"])
        # SEC-13: a fresh X-Replay-Run-Id per request
        sec13 = read_csv(run_dir / "segments" / "sec13" / "sink" / "ledger.csv")
        self.assertEqual([r["run_id"] for r in sec13], [run_dir.name + "-r0{}".format(n) for n in (1, 2, 3)])
        # one cost-ledger row for the whole run, equal to the totals in summary.json
        rows = read_csv(self.ledger)
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0]["tickets"]), 7 + 3 + 3 + 6)
        self.assertEqual(int(rows[0]["llm_calls"]), summary["run_totals"]["llm_calls"])
        # probe, scan, results: every ID present and well formed
        probe = json.loads((run_dir / "auth_probe.json").read_text())
        self.assertEqual([(c["case"], c["http_status"], c["new_executions"]) for c in probe],
                         [("missing_token", 403, 0), ("wrong_token", 403, 0)])
        self.assertNotIn(ENV["T4_WEBHOOK_TOKEN"], (run_dir / "auth_probe.json").read_text())
        scan_result = json.loads((run_dir / "secret_scan.json").read_text())
        self.assertIn("SINK_TOKEN", scan_result["env_names"])
        results = json.loads((run_dir / attacks.RESULTS_FILE).read_text())["results"]
        self.assertEqual([r["id"] for r in results], list(attacks.SEC_IDS))
        self.assertEqual(check_run.attack_problems(Run(run_dir)), [])
        by_id = {r["id"]: r for r in results}
        self.assertEqual(by_id["SEC-18"]["result"], "defended")
        self.assertEqual(by_id["SEC-20"]["result"], "defended")
        self.assertEqual(by_id["SEC-13"]["detail"]["distinct_run_ids_in_ledger"], 3)
        # the fake n8n never applies the cap, so the burst is reported as not run, with a reason
        self.assertEqual(by_id["SEC-12"]["result"], "not_run")
        self.assertIn("never tripped", by_id["SEC-12"]["reason"])
        # re-evaluation from files gives the same results
        self.assertEqual(attacks.evaluate(run_dir, load_golds(self.manifest)), results)


if __name__ == "__main__":
    unittest.main()
