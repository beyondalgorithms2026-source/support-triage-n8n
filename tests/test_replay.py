"""G6 replay runner tests: fake n8n, fake docker, the real sink on an ephemeral localhost port. No model calls."""
import argparse
import base64
import contextlib
import csv
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from src.replay import run
from src.score import check_run
from src.score.score import Run

ENV = {"N8N_BASE_URL": "http://n8n.invalid:5678", "N8N_CONTAINER": "n8n", "T4_WEBHOOK_TOKEN": "tok-hook-test",
       "T4_WEBHOOK_PATH": "hook-path-test", "SINK_TOKEN": "tok-sink-test",
       "SINK_BASE_URL": "http://host.docker.internal:8790", "JIRA_BASE_URL": "http://host.docker.internal:8790",
       "SLACK_BASE_URL": "http://host.docker.internal:8790", "JIRA_SANDBOX_EMAIL": "bot@example.com",
       "JIRA_SANDBOX_API_TOKEN": "tok-jira-test", "SLACK_SANDBOX_BOT_TOKEN": "tok-slack-test",
       "JIRA_PROJECT_KEY": "SUP", "OPENAI_API_KEY": "tok-llm-test", "LLM_PRICE_IN_PER_MTOK": "0.15",
       "LLM_PRICE_OUT_PER_MTOK": "0.60", "RUN_USD_CAP": "0.25", "DAILY_USD_CAP": "1.00",
       "PROJECT_LLM_USD_CAP": "2.00"}
CONFIG = {"llm_model": "gpt-4o-mini-2024-07-18", "llm_price_in_per_mtok": 0.15, "llm_price_out_per_mtok": 0.6,
          "run_usd_cap": 0.25, "daily_usd_cap": 1.0, "max_model_chars": 6000, "slack_channel_triage": "C-TRIAGE"}
WORKFLOW = {"id": "t4TriageFlow0001", "name": "t4-triage", "connections": {}, "nodes": [
    {"name": "0. Webhook — Ticket Intake", "type": "n8n-nodes-base.webhook",
     "parameters": {"path": "__WEBHOOK_PATH__", "httpMethod": "POST", "authentication": "headerAuth"},
     "credentials": {"httpHeaderAuth": {"id": "", "name": "t4-webhook-auth"}}},
    {"name": "0. Config", "type": "n8n-nodes-base.set", "parameters": {"assignments": {"assignments": [
        {"name": k, "value": v, "type": "string" if isinstance(v, str) else "number"} for k, v in CONFIG.items()]}}},
    {"name": "H6 LLM Classify", "type": "n8n-nodes-base.httpRequest", "onError": "continueErrorOutput",
     "parameters": {"url": "https://api.openai.com/v1/chat/completions", "method": "POST",
                    "jsonBody": "={{ JSON.stringify({model: $('0. Config').first().json.llm_model}) }}",
                    "options": {"timeout": 30000}},
     "credentials": {"httpHeaderAuth": {"id": "", "name": "t4-llm"}}},
    {"name": "H16 Audit", "type": "n8n-nodes-base.httpRequest", "onError": "continueErrorOutput",
     "parameters": {"url": "__SINK_BASE_URL__/append/audit", "method": "POST", "options": {"timeout": 10000}},
     "credentials": {"httpHeaderAuth": {"id": "", "name": "t4-sink-auth"}}}]}
HANDLER = {"id": "t4ErrorHandler01", "name": "t4-error-handler", "connections": {}, "nodes": [
    {"name": "E Errors Append", "type": "n8n-nodes-base.httpRequest", "onError": "continueRegularOutput",
     "parameters": {"url": "__SINK_BASE_URL__/append/errors", "method": "POST", "options": {"timeout": 10000}},
     "credentials": {"httpHeaderAuth": {"id": "", "name": "t4-sink-auth"}}}]}


def call(method, url, headers, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = dict(headers, **({"Content-Type": "application/json"} if data is not None else {}))
    try:
        with urlopen(Request(url, data=data, headers=headers, method=method), timeout=5) as response:
            return response.status, json.loads(response.read() or b"{}")
    except HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


class RecordingSink(run.LocalSink):
    """The real LocalSink; remembers each instance so the fake workflow can reach it."""
    instances = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        RecordingSink.instances.append(self)


class FakeWorkflow:
    """Plays n8n: `submit` writes what the workflow would write to the sink; `wait_execution` returns run data."""

    def __init__(self, prompt_tokens=1000, completion_tokens=20, submit_error=None, http_status=200):
        self.calls, self.submitted, self.next_id = [], [], 0
        self.prompt_tokens, self.completion_tokens = prompt_tokens, completion_tokens
        self.submit_error, self.http_status = submit_error, http_status
        self.called_model = False
        self.imported = []

    # --- n8n lifecycle (LocalN8n interface)
    def credential_ids(self, names):
        return {name: "id-" + name for name in names}

    def version(self):
        return "2.22.5"

    def import_workflow(self, workflow):
        self.imported.append(workflow)
        self.calls.append(("import", workflow["id"]))

    def publish(self, workflow_id):
        self.calls.append(("publish", workflow_id))

    def unpublish(self, workflow_id):
        self.calls.append(("unpublish", workflow_id))

    def wait_ready(self, base_url):
        self.calls.append(("ready",))

    def latest_id(self, workflow_id):
        return self.next_id

    # --- one ticket through the "workflow"
    def submit(self, url, token, run_id, gold, timeout=None):
        if self.submit_error:
            raise self.submit_error
        self.submitted.append((url, token, gold["input_id"]))
        sink = RecordingSink.instances[-1].url
        auth = {"X-Sink-Token": ENV["SINK_TOKEN"]}
        basic = {"Authorization": "Basic " + base64.b64encode(
            "{}:{}".format(ENV["JIRA_SANDBOX_EMAIL"], ENV["JIRA_SANDBOX_API_TOKEN"]).encode()).decode()}
        input_id, execution_id = gold["input_id"], self.next_id + 1
        audit = {"run_id": run_id, "input_ref": input_id, "execution_id": execution_id}
        _, seen = call("GET", sink + "/lookup/audit?input_ref={}&status={}".format(
            input_id, quote("auto_routed|review")), auth)
        self.called_model = not seen["count"]
        if seen["count"]:
            call("POST", sink + "/append/audit", auth, dict(audit, status="duplicate_skip"))
            return self.http_status
        usd = (self.prompt_tokens * 0.15 + self.completion_tokens * 0.6) / 1e6
        call("POST", sink + "/append/ledger", auth, {"run_id": run_id, "input_ref": input_id, "usd": usd,
                                                     "tokens_in": self.prompt_tokens,
                                                     "tokens_out": self.completion_tokens})
        label = "t4dk-" + input_id
        status, reply = call("POST", sink + "/rest/api/3/issue", basic, {"fields": {
            "project": {"key": "SUP"}, "issuetype": {"name": "Task"}, "summary": "[billing] synthetic",
            "labels": ["t4", label]}})
        if status == 201:
            call("POST", sink + "/append/jira_links", auth, {"run_id": run_id, "dedupe_key": input_id,
                                                             "issue_key": reply["key"], "created_via": "create"})
            call("POST", sink + "/append/audit", auth, dict(audit, status="auto_routed", usd=usd,
                                                            issue_key=reply["key"], category="billing"))
        else:
            call("POST", sink + "/append/errors", auth, {"run_id": run_id, "input_ref": input_id, "code": "jira"})
            call("POST", sink + "/append/audit", auth, dict(audit, status="review", usd=usd, category="billing"))
        return self.http_status

    def wait_execution(self, workflow_id, after_id, timeout=None):
        self.next_id += 1
        input_id = self.submitted[-1][2]
        run_data = {
            "0. Webhook — Ticket Intake": [{"startTime": 1791800000000, "executionTime": 1, "data": {"main": [[
                {"json": {"headers": {"x-t4-token": ENV["T4_WEBHOOK_TOKEN"]}, "body": {"subject": "s"}}}]]}}],
            "H4 Injection Scan + Cap": [{"startTime": 1791800000002, "executionTime": 1, "data": {"main": [[
                {"json": {"model_text": "Subject: invoice " + input_id}}]]}}],
            "H16 Audit": [{"startTime": 1791800000009, "executionTime": 3, "data": {"main": [[{"json": {}}]]}}]}
        if self.called_model:
            run_data["H6 LLM Classify"] = [{
                "startTime": 1791800000003, "executionTime": 400,
                "source": [{"previousNode": "H4 Injection Scan + Cap"}],
                "data": {"main": [[{"json": {"usage": {"prompt_tokens": self.prompt_tokens,
                                                       "completion_tokens": self.completion_tokens}}}]]}}]
        return {"id": self.next_id, "status": "success", "started": "2026-10-13T00:00:00Z",
                "data": {"resultData": {"runData": run_data}}}


class ReplayRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workflow = self.root / "t4-triage.json"
        self.workflow.write_text(json.dumps(WORKFLOW, ensure_ascii=False), encoding="utf-8")
        self.handler = self.root / "t4-error-handler.json"
        self.handler.write_text(json.dumps(HANDLER), encoding="utf-8")
        self.manifest = self.root / "manifest.csv"
        tickets = (("t4-901", "dev", None), ("t4-902", "dev", {"target": "jira", "mode": "503", "pass": "A"}),
                   ("t4-903", "test", None))
        with self.manifest.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=("input_id", "split", "label_bucket", "category", "priority",
                                                   "urgency", "expect_outcome", "gold_path"))
            writer.writeheader()
            for input_id, split, fault in tickets:
                gold = self.root / (input_id + ".json")
                gold.write_text(json.dumps({"input_id": input_id, "split": split, "fault": fault,
                                            "ticket": {"source": "email", "subject": "invoice " + input_id,
                                                       "source_message_id": "<{}@mail.example.com>".format(input_id),
                                                       "from_email": "dana@example.com", "body_text": "b"}}),
                                encoding="utf-8")
                writer.writerow({"input_id": input_id, "split": split, "label_bucket": "clean",
                                 "category": "billing", "priority": "P3", "urgency": "low",
                                 "expect_outcome": "auto_route", "gold_path": str(gold)})
        self.ledger = self.root / "cost_ledger.csv"
        RecordingSink.instances = []
        self.patches = [mock.patch.object(run, "LocalSink", RecordingSink)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def args(self, **extra):
        values = dict(target="local", phase="smoke", split=None, ids=None, limit=None, passes=None,
                      force_fault=None, config_override=["max_model_chars=5000"], workflow=str(self.workflow),
                      handler_workflow=str(self.handler), sqlite=None, manifest=str(self.manifest),
                      runs_dir=str(self.root / "runs"), cost_ledger=str(self.ledger), sink_host="127.0.0.1",
                      sink_port=0, timeout=5)
        values.update(extra)
        return argparse.Namespace(**values)

    def replay(self, fake, args=None, env=None):
        with mock.patch.object(run, "submit", side_effect=fake.submit):
            return run.run_replay(args or self.args(), fake, env=dict(ENV, **(env or {})))

    def test_ab_run_writes_complete_evidence(self):
        fake = FakeWorkflow()
        before = self.workflow.read_bytes()
        run_dir = self.replay(fake)
        # lifecycle: handler first, unpublish in reverse order
        self.assertEqual(fake.calls, [("import", "t4ErrorHandler01"), ("publish", "t4ErrorHandler01"),
                                      ("import", "t4TriageFlow0001"), ("publish", "t4TriageFlow0001"), ("ready",),
                                      ("unpublish", "t4TriageFlow0001"), ("unpublish", "t4ErrorHandler01")])
        # in-memory substitution, credential binding and override; the committed file is unchanged
        imported = json.dumps(fake.imported[1], ensure_ascii=False)
        self.assertNotIn("__", imported)
        self.assertIn("http://host.docker.internal:8790/append/audit", imported)
        self.assertIn('"id": "id-t4-sink-auth"', imported)
        self.assertEqual(run.config_values(fake.imported[1])["max_model_chars"], 5000)
        self.assertEqual(self.workflow.read_bytes(), before)
        # sequential submission, dev split only, both passes
        self.assertEqual([s[2] for s in fake.submitted], ["t4-901", "t4-902", "t4-901", "t4-902"])
        self.assertTrue(all(url == "http://n8n.invalid:5678/webhook/hook-path-test" for url, _, _ in fake.submitted))
        summary = json.loads((run_dir / "summary.json").read_text())
        for key in ("phase", "split", "passes", "input_ids", "run_usd_cap", "max_model_chars",
                    "new_jira_issues_pass_b", "llm_calls_pass_b", "model", "n8n_version", "workflow_sha256",
                    "thresholds_sha256", "prompt_sha256"):
            self.assertIn(key, summary)
        self.assertEqual((summary["phase"], summary["split"], summary["passes"]), ("smoke", "dev", "AB"))
        self.assertEqual(summary["input_ids"], ["t4-901", "t4-902"])
        self.assertEqual(summary["n8n_version"], "2.22.5")
        self.assertEqual(summary["max_model_chars"], 5000)
        self.assertEqual(summary["workflow_sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual((summary["new_jira_issues_pass_b"], summary["llm_calls_pass_b"]), (0, 0))
        self.assertIsNone(summary["aborted"])
        self.assertTrue(run_dir.name.startswith("smoke-local-"))
        # trace: one LLM row per pass-A ticket with the model text; no secret anywhere
        trace_text = (run_dir / "trace.jsonl").read_text()
        trace = [json.loads(line) for line in trace_text.splitlines()]
        llm = [e for e in trace if e["node"] == "H6 LLM Classify"]
        self.assertEqual([e["llm_input"] for e in llm], ["Subject: invoice t4-901", "Subject: invoice t4-902"])
        self.assertAlmostEqual(llm[0]["usd"], (1000 * 0.15 + 20 * 0.60) / 1e6)
        self.assertEqual({e["stage"] for e in llm}, {"classify"})
        for name in run.SECRET_ENV:
            self.assertNotIn(ENV[name], trace_text)
        # sink: the gold fault reached the sandbox in pass A only; LLM-input mirror rows exist
        requests = [json.loads(line) for line in (run_dir / "sink" / "requests.jsonl").read_text().splitlines()]
        faults = [(r["active_input"], r["pass"], r.get("fault")) for r in requests if r.get("fault")]
        self.assertEqual(faults, [("t4-902", "A", "jira:503")])
        self.assertEqual(sum(r["target"] == "llm" for r in requests), 2)
        self.assertFalse(any("headers" in r for r in requests))
        self.assertTrue((run_dir / "static_checks.json").exists())
        # the scorer and run checker read the folder (Q-25)
        loaded = Run(run_dir)
        self.assertEqual(loaded.input_ids, ["t4-901", "t4-902"])
        self.assertEqual(check_run.terminal_audit_problems(loaded), [])
        self.assertEqual(check_run.issue_problems(loaded) + check_run.pass_b_problems(loaded), [])
        self.assertEqual(len(loaded.tables["jira_issues"]), 1)
        # one cost-ledger row with the frozen columns
        with self.ledger.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.assertEqual(reader.fieldnames, run.LEDGER_HEADER)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["run_id"], rows[0]["llm_calls"], rows[0]["tickets"], rows[0]["run_usd_cap"]),
                         (run_dir.name, "2", "2", "0.25"))
        self.assertEqual(check_run.ledger_problems(loaded, self.ledger), [])

    def test_forced_fault_and_ids_and_limit(self):
        fake = FakeWorkflow()
        run_dir = self.replay(fake, self.args(phase="slice", ids=["t4-902,t4-901"], limit=1,
                                              force_fault=["t4-901:sink:jira_links:503"]))
        self.assertEqual([s[2] for s in fake.submitted], ["t4-901"])
        requests = [json.loads(line) for line in (run_dir / "sink" / "requests.jsonl").read_text().splitlines()]
        self.assertEqual([r["fault"] for r in requests if r.get("fault")], ["sink:jira_links:503"])
        self.assertEqual(json.loads((run_dir / "summary.json").read_text())["passes"], "A")

    def test_runner_cap_stops_submitting(self):
        fake = FakeWorkflow(prompt_tokens=2000000)   # one call costs $0.30 > RUN_USD_CAP 0.25
        run_dir = self.replay(fake)
        self.assertEqual([s[2] for s in fake.submitted], ["t4-901"])
        trace = [json.loads(line) for line in (run_dir / "trace.jsonl").read_text().splitlines()]
        self.assertEqual(sum(e.get("error") == "runner_cap" for e in trace), 3)
        self.assertEqual(json.loads((run_dir / "summary.json").read_text())["capped_inputs"], 3)
        with self.ledger.open(newline="", encoding="utf-8") as f:
            self.assertEqual(list(csv.DictReader(f))[0]["capped_inputs"], "3")

    def test_project_cap_refuses_before_any_side_effect(self):
        self.ledger.write_text(",".join(run.LEDGER_HEADER) + "\n" + "old,dev,local,,,m,1,1,1,1.9,0.25,0,1,0\n",
                               encoding="utf-8")
        fake = FakeWorkflow()
        with self.assertRaisesRegex(ValueError, "PROJECT_LLM_USD_CAP"):
            self.replay(fake)
        self.assertEqual(fake.calls, [])
        self.assertFalse((self.root / "runs").exists())

    def test_failure_unpublishes_stops_sink_and_keeps_evidence(self):
        fake = FakeWorkflow(submit_error=RuntimeError("webhook submission failed"))
        with self.assertRaises(RuntimeError):
            self.replay(fake)
        self.assertEqual(fake.calls[-2:], [("unpublish", "t4TriageFlow0001"), ("unpublish", "t4ErrorHandler01")])
        self.assertEqual(RecordingSink.instances[-1].server.socket.fileno(), -1)
        run_dir = next((self.root / "runs").iterdir())
        self.assertIn("webhook submission failed", json.loads((run_dir / "summary.json").read_text())["aborted"])
        self.assertTrue(self.ledger.exists())

    def test_wrong_webhook_token_aborts(self):
        fake = FakeWorkflow(http_status=403)
        with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
            self.replay(fake)
        self.assertEqual(fake.calls[-1], ("unpublish", "t4ErrorHandler01"))

    def test_refusals(self):
        with self.assertRaisesRegex(ValueError, "split dev only"):
            self.replay(FakeWorkflow(), self.args(phase="dev", split="test"))
        with self.assertRaisesRegex(ValueError, "outside split"):
            self.replay(FakeWorkflow(), self.args(ids=["t4-903"]))
        with self.assertRaisesRegex(ValueError, "not in manifest"):
            self.replay(FakeWorkflow(), self.args(ids=["t4-999"]))
        with self.assertRaisesRegex(ValueError, "key not in"):
            self.replay(FakeWorkflow(), self.args(config_override=["no_such_key=1"]))
        with self.assertRaisesRegex(ValueError, "run_usd_cap"):
            self.replay(FakeWorkflow(), env={"RUN_USD_CAP": "0.10"})
        with self.assertRaisesRegex(ValueError, "SINK_TOKEN"):
            self.replay(FakeWorkflow(), env={"SINK_TOKEN": ""})
        self.assertFalse((self.root / "runs").exists())


class ReplayUnitTests(unittest.TestCase):
    def test_parse_fault(self):
        self.assertEqual(run.parse_fault("t4-007:sink:jira_links:503"),
                         ("t4-007", {"target": "sink:jira_links", "mode": "503", "pass": "A"}))
        self.assertEqual(run.parse_fault("t4-007:jira:commit_then_504:B")[1]["pass"], "B")
        with self.assertRaises(ValueError):
            run.parse_fault("t4-007:jira:999")

    def test_stage_map(self):
        self.assertEqual(run.stage_for("H1 Intake Guard"), "intake")
        self.assertEqual(run.stage_for("H6 LLM Classify"), "classify")
        self.assertEqual(run.stage_for("H9 Validate"), "validate")
        self.assertEqual(run.stage_for("H10 Decide"), "decide")
        self.assertEqual(run.stage_for("H12r Reconcile"), "act")
        self.assertEqual(run.stage_for("H15 Review Queue"), "approve")
        self.assertEqual(run.stage_for("0. Config"), "intake")
        self.assertEqual(run.stage_for("Something else"), "record")

    def test_llm_input_drops_headers_and_scrubber_removes_secrets(self):
        run_data = {"H5 Spend Gate": [{"data": {"main": [[{"json": {
            "headers": {"x-t4-token": "tok-hook-test"}, "text": "path hook-path-test"}}]]}}]}
        entry = {"source": [{"previousNode": "H5 Spend Gate"}]}
        text = run.llm_input(run_data, entry)
        self.assertNotIn("headers", text)
        scrub = run.scrubber(ENV)
        self.assertEqual(scrub({"a": [text]})["a"][0], '{"text": "path [REDACTED:T4_WEBHOOK_PATH]"}')
        self.assertEqual(run.trace_events(None, "r", "A", "t4-001", 0.15, 0.6)[0]["error"], "execution_timeout")

    def test_setup_builds_five_credentials_in_memory(self):
        fake = type("Fake", (), {"import_credentials": lambda self, c: setattr(self, "creds", c)})()
        self.assertEqual(run.setup(env=ENV, n8n=fake), sorted(run.CREDENTIAL_IDS))
        by_name = {c["name"]: c for c in fake.creds}
        self.assertEqual(set(by_name), {"t4-llm", "t4-webhook-auth", "t4-sink-auth", "t4-jira", "t4-slack"})
        self.assertEqual(by_name["t4-webhook-auth"]["data"], {"name": "X-T4-Token", "value": "tok-hook-test"})
        self.assertEqual(by_name["t4-sink-auth"]["data"]["name"], "X-Sink-Token")
        self.assertEqual(by_name["t4-llm"]["data"]["value"], "Bearer tok-llm-test")
        self.assertEqual(by_name["t4-jira"]["type"], "httpBasicAuth")
        self.assertEqual(by_name["t4-slack"]["data"]["value"], "Bearer tok-slack-test")
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY") as caught:
            run.setup(env=dict(ENV, OPENAI_API_KEY=""), n8n=fake)
        self.assertNotIn("tok-", str(caught.exception))

    def test_local_cli_uses_stdin_restarts_reads_version_and_sqlite_read_only(self):
        calls = []

        class Result:
            returncode = 0
            stdout = "2.22.5\n"

        def command(args, **kwargs):
            calls.append((args, kwargs.get("input")))
            return Result()
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "n8n.sqlite"
            with sqlite3.connect(database) as db:
                db.execute("CREATE TABLE execution_entity (id integer, workflowId text, status text, "
                           "startedAt text, stoppedAt text)")
                db.execute("CREATE TABLE execution_data (executionId integer, data text)")
                db.execute("INSERT INTO execution_entity VALUES (1, 'wf', 'success', 's', 'e')")
                db.execute("INSERT INTO execution_data VALUES (1, ?)", (json.dumps({"resultData": {"runData": {}}}),))
            before = database.read_bytes()
            local = run.LocalN8n(database, container="n8n-x", command=command, sleeper=lambda _: None)
            local.import_credentials([{"name": "t4-llm"}])
            local.import_workflow({"id": "wf"})
            local.publish("wf")
            local.unpublish("wf")
            self.assertEqual(local.version(), "2.22.5")
            self.assertEqual(local.latest_id("wf"), 1)
            self.assertEqual(local.wait_execution("wf", 0)["id"], 1)
            self.assertEqual(database.read_bytes(), before)
        self.assertEqual(calls[0][0], ["docker", "exec", "-i", "n8n-x", "n8n", "import:credentials",
                                       "--input=/dev/stdin"])
        self.assertEqual(json.loads(calls[0][1]), [{"name": "t4-llm"}])
        self.assertIn("--input=/dev/stdin", calls[1][0])
        self.assertEqual([c[0][:2] for c in calls].count(["docker", "restart"]), 2)
        self.assertEqual(calls[-1][0], ["docker", "exec", "n8n-x", "n8n", "--version"])

    def test_help_exits_zero(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as caught:
            run.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("--force-fault", out.getvalue())


if __name__ == "__main__":
    unittest.main()
