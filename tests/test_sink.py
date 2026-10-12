"""Sink + Jira/Slack sandbox (G5): every fault, every 403 path, stamps, request log. Localhost, ephemeral port."""
import base64
import contextlib
import csv
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.score import score
from src.sink import server as sink

SINK = "sink-test-value-1"
JIRA_EMAIL = "t4-bot@example.com"
JIRA_TOKEN = "jira-test-value-1"
SLACK = "slack-test-value-1"
TRIAGE, REVIEW = "C-TRIAGE", "C-REVIEW"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # never route localhost through a proxy


def basic(email, token):
    return "Basic " + base64.b64encode("{}:{}".format(email, token).encode()).decode()


AUTH = {"sink": {"X-Sink-Token": SINK}, "jira": {"Authorization": basic(JIRA_EMAIL, JIRA_TOKEN)},
        "slack": {"Authorization": "Bearer " + SLACK}, None: {}}


def adf(text):
    return {"type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def issue_body(dedupe_key="abc123", **fields):
    body = {"project": {"key": "SUP"}, "issuetype": {"name": "Task"}, "summary": "[billing] Charged twice",
            "description": adf("Card [CARD_1] was charged twice."), "priority": {"name": "Medium"},
            "labels": ["t4", "t4dk-" + dedupe_key, "t4-cat-billing"]}
    body.update(fields)
    return {"fields": body}


def search_path(dedupe_key):
    return "/rest/api/3/search/jql?jql=labels%20%3D%20%22t4dk-{}%22&fields=key&maxResults=2".format(dedupe_key)


class SinkCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "sink"
        self.start()

    def start(self):
        self.server = sink.make_server(self.dir, SINK, JIRA_EMAIL, JIRA_TOKEN, SLACK, channels=(TRIAGE, REVIEW))
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:{}".format(self.server.server_address[1])

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def tearDown(self):
        self.stop()
        self.tmp.cleanup()

    def call(self, method, path, body=None, auth="sink", raw=None, headers=None):
        hdrs = dict(AUTH[auth] if isinstance(auth, str) or auth is None else auth)
        hdrs.update(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if data is not None:
            hdrs["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=hdrs)
        try:
            with OPENER.open(request, timeout=5) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"null")

    def active(self, input_id="t4-001", run_pass="A"):
        self.assertEqual(self.call("POST", "/_replay/active", {"input_id": input_id, "pass": run_pass})[0], 200)

    def fault(self, **body):
        status, reply = self.call("POST", "/_replay/fault", body)
        self.assertEqual(status, 200, reply)

    def rows(self, table):
        return score.read_csv(self.dir / (table + ".csv"))

    def requests(self):
        return score.read_jsonl(self.dir / "requests.jsonl")

    def create(self, dedupe_key="abc123", **fields):
        return self.call("POST", "/rest/api/3/issue", issue_body(dedupe_key, **fields), auth="jira")

    def search(self, dedupe_key="abc123"):
        status, reply = self.call("GET", search_path(dedupe_key), auth="jira")
        self.assertEqual(status, 200, reply)
        return [issue["key"] for issue in reply["issues"]]

    def slack(self, channel=TRIAGE, text="SUP-1 [billing] P3 Charged twice"):
        return self.call("POST", "/api/chat.postMessage",
                         {"channel": channel, "text": text, "unfurl_links": False, "unfurl_media": False},
                         auth="slack")


class StartupTests(unittest.TestCase):
    def test_refuses_each_missing_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = [SINK, JIRA_EMAIL, JIRA_TOKEN, SLACK]
            for i in range(4):
                args = list(good)
                args[i] = ""
                with self.assertRaises(ValueError):
                    sink.make_server(tmp, *args)

    def test_main_names_missing_env_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"SINK_TOKEN": SINK}, clear=True):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(sink.main(["--state-dir", tmp, "--port", "0"]), 2)
            self.assertIn("JIRA_SANDBOX_API_TOKEN", err.getvalue())
            self.assertIn("SLACK_SANDBOX_BOT_TOKEN", err.getvalue())
            self.assertNotIn(SINK, err.getvalue())


class AuthTests(SinkCase):
    def test_sink_group_403(self):
        for auth in (None, {"X-Sink-Token": "wrong"}, "jira", "slack"):
            self.assertEqual(self.call("GET", "/_health", auth=auth)[0], 403, auth)
            self.assertEqual(self.call("POST", "/append/errors", {"run_id": "r"}, auth=auth)[0], 403, auth)
        self.assertEqual(self.call("GET", "/_health")[0], 200)
        self.assertEqual(self.rows("errors"), [])

    def test_jira_group_403(self):
        bad = (None, "sink", "slack", {"Authorization": basic(JIRA_EMAIL, "wrong")},
               {"Authorization": basic("other@example.com", JIRA_TOKEN)}, {"Authorization": "Basic %%%"})
        for auth in bad:
            self.assertEqual(self.call("POST", "/rest/api/3/issue", issue_body(), auth=auth)[0], 403, auth)
            self.assertEqual(self.call("GET", search_path("abc123"), auth=auth)[0], 403, auth)
        self.assertEqual(self.rows("jira_issues"), [])

    def test_slack_group_403(self):
        for auth in (None, "sink", "jira", {"Authorization": "Bearer wrong"}, {"Authorization": SLACK}):
            status, reply = self.call("POST", "/api/chat.postMessage", {"channel": TRIAGE, "text": "x"}, auth=auth)
            self.assertEqual((status, reply["ok"]), (403, False), auth)
        self.assertEqual(self.rows("slack_messages"), [])


class PrivilegeTests(SinkCase):
    """C-17 / SEC-19: with a valid credential, every other project, type, method or path is 403 and logged."""

    def test_jira_other_project_type_method_path(self):
        self.assertEqual(self.create(project={"key": "HR"})[0], 403)
        self.assertEqual(self.create(issuetype={"name": "Bug"})[0], 403)
        self.assertEqual(self.create(issuetype={"id": "10001"})[0], 403)
        jql = "/rest/api/3/search/jql?jql=project%20%3D%20HR%20AND%20labels%20%3D%20%22t4%22"
        self.assertEqual(self.call("GET", jql, auth="jira")[0], 403)
        self.assertEqual(self.create()[0], 201)
        for method, path in (("DELETE", "/rest/api/3/issue/SUP-1"), ("PUT", "/rest/api/3/issue/SUP-1"),
                             ("GET", "/rest/api/3/issue/SUP-1"), ("POST", "/rest/api/3/issue/SUP-1/comment"),
                             ("GET", "/rest/api/3/project"), ("GET", "/rest/api/2/search?jql=x"),
                             ("POST", "/rest/api/3/search/jql"), ("PATCH", "/rest/api/3/issue")):
            self.assertEqual(self.call(method, path, {} if method != "GET" else None, auth="jira")[0], 403,
                             (method, path))
        self.assertEqual(len(self.rows("jira_issues")), 1)
        denied = [r for r in self.requests() if r["status"] == 403]
        self.assertEqual(len(denied), 12)
        self.assertTrue(all(r["target"] == "jira" for r in denied))

    def test_slack_other_method_path_channel(self):
        self.assertEqual(self.slack(channel="C-GENERAL")[0], 403)
        for method, path in (("POST", "/api/conversations.list"), ("POST", "/api/chat.delete"),
                             ("GET", "/api/chat.postMessage"), ("POST", "/api/chat.update")):
            self.assertEqual(self.call(method, path, {} if method == "POST" else None, auth="slack")[0], 403)
        self.assertEqual(self.rows("slack_messages"), [])

    def test_sink_cannot_write_sandbox_tables_or_unknown_paths(self):
        for table in ("jira_issues", "slack_messages", "nope"):
            self.assertEqual(self.call("POST", "/append/" + table, {"key": "SUP-9"})[0], 400)
        self.assertEqual(self.call("DELETE", "/append/audit")[0], 404)
        self.assertEqual(self.call("GET", "/")[0], 404)
        self.assertEqual(self.rows("jira_issues"), [])


class SinkTableTests(SinkCase):
    def test_append_stamps_and_shared_sequence(self):
        self.active("t4-007", "B")
        status, reply = self.call("POST", "/append/audit", {"run_id": "r1", "status": "review",
                                                            "reasons": ["policy_class"], "ok": True})
        self.assertEqual(status, 200)
        self.assertEqual(reply["row"]["sink_seq"], "1")
        self.call("POST", "/append/errors", {"run_id": "r1", "code": "error:sink"})
        audit, errors = self.rows("audit"), self.rows("errors")
        self.assertEqual(list(audit[0])[:4], list(sink.STAMPS))
        self.assertEqual(list(audit[0])[4:], list(sink.SINK_COLUMNS["audit"]))
        self.assertEqual((audit[0]["replay_input_id"], audit[0]["replay_pass"]), ("t4-007", "B"))
        self.assertEqual((audit[0]["reasons"], audit[0]["ok"]), ('["policy_class"]', "true"))
        self.assertEqual(errors[0]["sink_seq"], "2")
        datetime.fromisoformat(audit[0]["sink_ts"])

    def test_append_rejects_bad_bodies(self):
        for body in ({}, {"sink_seq": "9", "run_id": "r"}, {"run_id": "r", "colour": "x"}):
            self.assertEqual(self.call("POST", "/append/ledger", body)[0], 400, body)
        self.assertEqual(self.call("POST", "/append/ledger", raw=b"[1]")[0], 400)
        self.assertEqual(self.call("POST", "/append/ledger", raw=b"{not json")[0], 400)
        self.assertEqual(self.rows("ledger"), [])

    def test_lookup_filters_and_alternatives(self):
        for status, sha in (("auto_routed", "c1"), ("review", "c1"), ("rejected", "c1"), ("review", "c2")):
            self.call("POST", "/append/audit", {"run_id": "r1", "status": status, "content_sha256": sha})
        status, reply = self.call("GET", "/lookup/audit?content_sha256=c1&status=auto_routed%7Creview")
        self.assertEqual((status, reply["count"]), (200, 2))
        self.assertEqual({r["status"] for r in reply["rows"]}, {"auto_routed", "review"})
        self.assertEqual(self.call("GET", "/lookup/jira_links?dedupe_key=zz")[1]["count"], 0)
        self.assertEqual(self.call("GET", "/lookup/audit")[0], 400)
        self.assertEqual(self.call("GET", "/lookup/audit?colour=x")[0], 400)
        self.assertEqual(self.call("GET", "/lookup/audit?status=a&status=b")[0], 400)
        self.assertEqual(self.call("GET", "/lookup/jira_issues?key=SUP-1")[0], 400)

    def test_ledger_sum_and_count(self):
        today = datetime.now(timezone.utc).date().isoformat()
        for run_id, day, usd in (("r1", today, "0.000150"), ("r1", today, "0.000250"), ("r2", "2000-01-01", "1")):
            self.call("POST", "/append/ledger", {"run_id": run_id, "day": day, "usd": usd})
        self.assertEqual(self.call("GET", "/ledger/sum?run_id=r1")[1], {"usd": 0.0004, "count": 2})
        self.assertEqual(self.call("GET", "/ledger/sum?day=" + today)[1], {"usd": 0.0004, "count": 2})
        self.assertEqual(self.call("GET", "/ledger/sum?run_id=nobody")[1], {"usd": 0.0, "count": 0})
        for query in ("", "?run_id=", "?run_id=r1&day=" + today, "?model=x"):
            self.assertEqual(self.call("GET", "/ledger/sum" + query)[0], 400, query)
        self.assertEqual(self.call("GET", "/ledger/count?since_s=60")[1], {"count": 3})
        # Age one row on disk: the count window must leave it out.
        path = self.dir / "ledger.csv"
        rows = self.rows("ledger")
        rows[0]["sink_ts"] = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        self.assertEqual(self.call("GET", "/ledger/count?since_s=60")[1], {"count": 2})
        for query in ("", "?since_s=-1", "?since_s=abc", "?since_s=nan", "?since_s=60&run_id=r1"):
            self.assertEqual(self.call("GET", "/ledger/count" + query)[0], 400, query)


class JiraSlackTests(SinkCase):
    def test_create_then_search(self):
        self.active("t4-010")
        status, reply = self.create("k10")
        self.assertEqual(status, 201)
        self.assertEqual(reply["key"], "SUP-1")
        self.assertEqual(set(reply), {"id", "key", "self"})
        self.assertEqual(self.search("k10"), ["SUP-1"])
        self.assertEqual(self.search("other"), [])
        issue = self.rows("jira_issues")[0]
        self.assertEqual((issue["project"], issue["issuetype"], issue["priority"], issue["created_seq"]),
                         ("SUP", "Task", "Medium", "1"))
        self.assertEqual(issue["labels"], "t4|t4dk-k10|t4-cat-billing")
        self.assertEqual(issue["description_text"], "Card [CARD_1] was charged twice.")
        self.assertEqual(issue["replay_input_id"], "t4-010")
        self.assertEqual(self.create("k11")[1]["key"], "SUP-2")

    def test_create_field_contract(self):
        self.assertEqual(self.create(assignee={"accountId": "x"})[0], 400)
        self.assertEqual(self.create(priority={"name": "Blocker"})[0], 400)
        self.assertEqual(self.create(description="plain text")[0], 400)
        self.assertEqual(self.create(summary="two\nlines")[0], 400)
        self.assertEqual(self.create(labels=["has space"])[0], 400)
        self.assertEqual(self.call("POST", "/rest/api/3/issue", {"fields": {}, "update": {}}, auth="jira")[0], 400)
        self.assertEqual(self.call("GET", "/rest/api/3/search/jql?jql=summary%20~%20x", auth="jira")[0], 400)
        self.assertEqual(self.call("GET", search_path("k").replace("maxResults=2", "maxResults=0"), auth="jira")[0],
                         400)
        self.assertEqual(self.rows("jira_issues"), [])

    def test_slack_post(self):
        self.active("t4-011")
        status, reply = self.slack(REVIEW, "Review: [privacy] P3")
        self.assertEqual((status, reply["ok"], reply["channel"]), (200, True, REVIEW))
        message = self.rows("slack_messages")[0]
        self.assertEqual((message["channel"], message["text"], message["unfurl_links"]),
                         (REVIEW, "Review: [privacy] P3", "false"))
        self.assertEqual(self.call("POST", "/api/chat.postMessage", {"channel": TRIAGE}, auth="slack")[0], 400)


class FaultTests(SinkCase):
    def test_jira_503_holds_for_the_ticket_and_creates_nothing(self):
        self.active("t4-101")
        self.fault(target="jira", mode="503")
        self.assertEqual(self.create("k1")[0], 503)
        self.assertEqual(self.create("k1")[0], 503)
        self.assertEqual(self.search("k1"), [])
        self.assertEqual(self.rows("jira_issues"), [])
        self.active("t4-102")                       # a new ticket clears the fault
        self.assertEqual(self.create("k2")[0], 201)

    def test_times_limits_firings(self):
        self.active("t4-103")
        self.fault(target="jira", mode="503", times=1)
        self.assertEqual(self.create("k3")[0], 503)
        self.assertEqual(self.create("k3")[0], 201)

    def test_pass_gate(self):
        self.active("t4-104", "B")
        self.fault(target="jira", mode="503", **{"pass": "A"})
        self.assertEqual(self.create("k4")[0], 201)

    def test_commit_then_504(self):
        self.active("t4-105")
        self.fault(target="jira", mode="commit_then_504")
        status, _ = self.create("k5")
        self.assertEqual(status, 504)
        self.assertEqual(self.search("k5"), ["SUP-1"])     # SEC-15: reconcile finds the committed issue
        self.assertEqual(len(self.rows("jira_issues")), 1)

    def test_search_lag(self):
        self.active("t4-106")
        self.assertEqual(self.create("k6")[0], 201)
        self.fault(target="jira", mode="search_lag", lag_requests=4)
        self.assertEqual(self.search("k6"), [])            # issue is 2 requests old
        self.call("GET", "/_health")
        self.assertEqual(self.search("k6"), ["SUP-1"])     # 4 requests old
        self.fault(target="jira", mode="search_lag")       # default lag
        self.assertEqual(self.search("k6"), [])
        lagged = [r for r in self.requests() if r.get("fault") == "jira:search_lag"]
        self.assertEqual([r["lag_requests"] for r in lagged], [4, 4, sink.DEFAULT_LAG_REQUESTS])

    def test_slack_503(self):
        self.active("t4-107")
        self.fault(target="slack", mode="503")
        self.assertEqual(self.slack()[0], 503)
        self.assertEqual(self.rows("slack_messages"), [])

    def test_sink_jira_links_503_only_hits_that_table(self):
        self.active("t4-108")
        self.fault(target="sink:jira_links", mode="503")
        link = {"run_id": "r1", "dedupe_key": "k8", "issue_key": "SUP-1", "created_via": "create"}
        self.assertEqual(self.call("POST", "/append/jira_links", link)[0], 503)
        self.assertEqual(self.call("POST", "/append/audit", {"run_id": "r1", "status": "error"})[0], 200)
        self.assertEqual(self.rows("jira_links"), [])
        self.assertEqual(self.call("GET", "/lookup/jira_links?dedupe_key=k8")[1]["count"], 0)

    def test_fault_validation_and_clear(self):
        bad = ({"target": "jira", "mode": "500"}, {"target": "sink:audit", "mode": "503"},
               {"target": ["jira"], "mode": "503"}, {"target": "jira", "mode": "503", "times": 0},
               {"target": "jira", "mode": "503", "times": True}, {"target": "jira", "mode": "503", "pass": "C"},
               {"target": "jira", "mode": "503", "lag_requests": 3}, {"target": "jira", "mode": "503", "x": 1},
               {"clear": False})
        for body in bad:
            self.assertEqual(self.call("POST", "/_replay/fault", body)[0], 400, body)
        self.active("t4-109")
        self.fault(target="jira", mode="503")
        self.fault(clear=True)
        self.assertEqual(self.create("k9")[0], 201)
        for body in ({"input_id": "", "pass": "A"}, {"input_id": "t4-1", "pass": "C"}, {"pass": "A"}):
            self.assertEqual(self.call("POST", "/_replay/active", body)[0], 400, body)


class RequestLogTests(SinkCase):
    def test_rows_bodies_and_no_headers(self):
        self.active("t4-201")
        self.create("k20")
        self.slack()
        self.call("POST", "/append/audit", {"run_id": "r1", "status": "auto_routed"})
        self.call("POST", "/_replay/llm_input", {"llm_input": "Subject: Charged twice\n\nCard [CARD_1]"})
        self.call("GET", "/_health", auth={"X-Sink-Token": "wrong"})
        text = (self.dir / "requests.jsonl").read_text(encoding="utf-8")
        for secret in (SINK, JIRA_TOKEN, SLACK, JIRA_EMAIL, "wrong", "Authorization", "X-Sink-Token",
                       base64.b64encode("{}:{}".format(JIRA_EMAIL, JIRA_TOKEN).encode()).decode()):
            self.assertNotIn(secret, text)
        rows = self.requests()
        self.assertEqual([r["seq"] for r in rows], list(range(1, len(rows) + 1)))
        for row in rows:
            self.assertTrue({"seq", "ts", "method", "path", "status", "target", "active_input", "pass"} <= set(row))
        by_target = {r["target"]: r for r in rows[1:]}
        self.assertEqual(by_target["jira"]["body"]["fields"]["labels"][1], "t4dk-k20")
        self.assertEqual(by_target["slack"]["body"]["channel"], TRIAGE)
        self.assertIn("[CARD_1]", by_target["llm"]["body"]["llm_input"])
        self.assertNotIn("body", by_target["sink"])
        self.assertEqual((by_target["jira"]["active_input"], by_target["jira"]["pass"]), ("t4-201", "A"))
        self.assertEqual(rows[-1]["status"], 403)

    def test_scorer_reads_sink_files(self):
        """Q-25 contract: src.score.score loads this folder as a run's sink/."""
        self.active("t4-202")
        self.create("k21")
        self.slack()
        self.call("POST", "/_replay/llm_input", {"llm_input": "Call [PHONE_1]"})
        run = score.Run(self.dir.parent)
        self.assertEqual([r["key"] for r in run.issues_with_key("k21")], ["SUP-1"])
        self.assertEqual(len(run.rows("slack_messages", "t4-202", "A")), 1)
        targets = {score.request_target(r) for r in score.select(run.requests, "t4-202", "A")}
        self.assertEqual(targets, {"sink", "jira", "slack", "llm"})
        self.assertIn("llm_input", {t for t, _ in score.outbound(run, "t4-202")})


class RestartTests(SinkCase):
    def test_sequences_continue_after_restart(self):
        self.active("t4-301")
        self.create("k30")
        self.call("POST", "/append/audit", {"run_id": "r1", "status": "auto_routed"})
        before = len(self.requests())
        self.stop()
        self.start()
        self.active("t4-301", "B")
        self.assertEqual(self.search("k30"), ["SUP-1"])
        self.assertEqual(self.create("k31")[1]["key"], "SUP-2")
        row = self.call("POST", "/append/audit", {"run_id": "r1", "status": "duplicate_skip"})[1]["row"]
        self.assertEqual(row["sink_seq"], "4")
        self.assertEqual(self.requests()[before]["seq"], before + 1)


if __name__ == "__main__":
    unittest.main()
