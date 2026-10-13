"""Workflow JSON contract (GOALS G7, G8): static checks, embedded JS equals src/js, H6 body references only `model_text`
and Config, every external node is bounded and has its error output wired, every path ends in the audit node, and the
Code-node JS behaves as ARCHITECTURE §3 says under node (upstream nodes stubbed).

STUB completions and STUB upstream items below are hand-built test inputs, not run evidence.
"""
import hashlib
import json
import math
import re
import shutil
import subprocess
import unittest
from collections import deque
from pathlib import Path

from src.checks.static_checks import check_file
from src.common.norm import content_sha256, dedupe_key, email_norm, text_norm
from src.score.score import CATEGORIES, PRIORITY_WORDS, URGENCIES, is_llm_node
from src.sink.server import SINK_COLUMNS
from tests.test_norm import CONTENT_VECTORS, DEDUPE_VECTORS, EMAIL_VECTORS, TEXT_VECTORS
from tests.test_redact import NODE, assert_plain_es2019, run_js

ROOT = Path(__file__).resolve().parents[1]
TRIAGE = ROOT / "workflows" / "t4-triage.json"
HANDLER = ROOT / "workflows" / "t4-error-handler.json"
JS_DIR = ROOT / "src" / "js"
THRESHOLDS = ROOT / "evals" / "thresholds.json"
GOLD = ROOT / "evals" / "gold"
CREDENTIALS = {"t4-llm", "t4-webhook-auth", "t4-sink-auth", "t4-jira", "t4-slack"}
# ARCHITECTURE §4 node ids (G8 adds H2, H5, H9, H11, H12r, H12b, H14, H15, H15s to the G7 slice).
NODE_PREFIXES = ("H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8", "H9", "H10", "H11", "H12", "H12r", "H12b", "H13",
                 "H14", "H15", "H15s", "H16", "H16r", "E")
CONFIG_KEYS = {"llm_model", "llm_price_in_per_mtok", "llm_price_out_per_mtok", "llm_prompt_chars", "run_usd_cap",
               "daily_usd_cap", "llm_max_rpm", "max_body_chars", "max_subject_chars", "max_attachments",
               "max_model_chars", "max_output_tokens", "allowed_attachment_types", "jira_project_key",
               "jira_issue_type", "jira_max_creates_per_run", "slack_channel_triage", "slack_channel_review",
               "always_review", "privacy_keywords", "tau_category", "tau_priority", "tuning_mode"}
AUDIT = "H16 Audit Record"
AFTER_AUDIT = {"H16 Audit Append", "H16r Respond", "H16e Audit Failed"}
JIRA_CREATES = ("H12 Jira Create", "H12b Jira Create (retry once)")
SLACK_NODES = {"H14 Slack Notify": "H13 Build Link", "H15s Slack Review Post": "H15 Build Review"}
BLOCK = re.compile(r"// BEGIN (src/js/[a-z_]+\.js)\n(.*?)// END \1\n", re.S)
# Runs one Code node body the way n8n does (async function body), with $input / $ / $execution / $prevNode stubs.
# `nodes` maps an upstream node name to its first output json; null = the node ran but gave no success item.
CODE_HARNESS = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const fn = new AsyncFunction('$input', '$json', '$', '$execution', '$prevNode', input.code);
const nodes = input.nodes || {};
const $ = (name) => {
  if (!Object.prototype.hasOwnProperty.call(nodes, name)) {
    return { isExecuted: false, first: () => { throw new Error('node did not run: ' + name); } };
  }
  return { isExecuted: true, first: () => ({ json: nodes[name] }) };
};
(async function () {
  const out = [];
  for (const json of input.items) {
    const item = { json };
    const $input = { first: () => item, all: () => [item] };
    out.push((await fn($input, json, $, { id: 'stub' }, { name: input.prev || '' }))[0].json);
  }
  process.stdout.write(JSON.stringify(out));
})().catch((error) => { process.stderr.write(String(error && error.stack || error)); process.exit(1); });
"""


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def nodes_by_name(workflow):
    return {n["name"]: n for n in workflow["nodes"]}


def config_items(workflow):
    """`0. Config` values as n8n hands them on: array/object strings parsed."""
    node = nodes_by_name(workflow)["0. Config"]
    out = {}
    for a in node["parameters"]["assignments"]["assignments"]:
        value = a["value"]
        out[a["name"]] = json.loads(value) if a["type"] in ("array", "object") and isinstance(value, str) else value
    return out


def run_code(code, items, nodes=None, prev=""):
    payload = {"code": code, "items": items, "nodes": nodes or {}, "prev": prev}
    out = subprocess.run([NODE, "-e", CODE_HARNESS], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise AssertionError("node failed:\n" + out.stderr)
    return json.loads(out.stdout)


class WorkflowShapeTest(unittest.TestCase):
    def setUp(self):
        self.triage, self.handler = load(TRIAGE), load(HANDLER)

    def test_static_checks_clean(self):
        for path in (TRIAGE, HANDLER):
            with self.subTest(path.name):
                result = check_file(str(path))
                self.assertEqual(result["secrets"], [])
                self.assertEqual(result["violations"], [])

    def test_ids_and_error_workflow(self):
        self.assertTrue(self.triage["id"])
        self.assertTrue(self.handler["id"])
        self.assertEqual(self.triage["settings"]["errorWorkflow"], self.handler["id"])
        types = [n["type"] for n in self.handler["nodes"]]
        self.assertIn("n8n-nodes-base.errorTrigger", types)
        urls = [n["parameters"].get("url") for n in self.handler["nodes"]]
        self.assertIn("__SINK_BASE_URL__/append/errors", urls)

    def test_architecture_nodes_present(self):
        names = list(nodes_by_name(self.triage))
        prefixes = {name.split(" ", 1)[0] for name in names}
        for prefix in NODE_PREFIXES:
            self.assertIn(prefix, prefixes)
        self.assertIn("0. Config", names)
        self.assertIn("H10 Decide", names)
        self.assertFalse([n for n in names if "slice" in n.lower()])
        webhook = [n for n in self.triage["nodes"] if n["type"] == "n8n-nodes-base.webhook"]
        self.assertEqual(len(webhook), 1)
        params = webhook[0]["parameters"]
        self.assertEqual((params["httpMethod"], params["path"], params["authentication"]),
                         ("POST", "__WEBHOOK_PATH__", "headerAuth"))
        self.assertEqual(webhook[0]["credentials"]["httpHeaderAuth"]["name"], "t4-webhook-auth")

    def test_only_h6_is_a_model_node(self):
        # score.py and the runner count every node whose name looks like a model call (trace usd, llm_input).
        self.assertEqual([n for n in nodes_by_name(self.triage) if is_llm_node(n)], ["H6 LLM Classify"])

    def test_connections_name_real_nodes(self):
        for workflow in (self.triage, self.handler):
            names = set(nodes_by_name(workflow))
            for source, outputs in workflow["connections"].items():
                self.assertIn(source, names)
                for branch in outputs["main"]:
                    for target in branch:
                        self.assertIn(target["node"], names)

    def test_credentials_by_name_only(self):
        for workflow in (self.triage, self.handler):
            for node in workflow["nodes"]:
                for ref in (node.get("credentials") or {}).values():
                    self.assertEqual(set(ref), {"name"}, node["name"])
                    self.assertIn(ref["name"], CREDENTIALS)

    def test_jira_create_never_retries(self):
        nodes = nodes_by_name(self.triage)
        creates = [n["name"] for n in self.triage["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"
                   and n["parameters"].get("method") == "POST"
                   and n["parameters"]["url"].endswith("/rest/api/3/issue")]
        self.assertEqual(sorted(creates), sorted(JIRA_CREATES))
        for name in JIRA_CREATES:
            with self.subTest(name):
                self.assertIs(nodes[name]["retryOnFail"], False)
                self.assertNotIn("maxTries", nodes[name])
        # C-18 (5): the create's error output reconciles by label before the single re-create.
        self.assertEqual(self.triage["connections"]["H12 Jira Create"]["main"][1][0]["node"], "H12r Reconcile")

    def test_external_nodes_bounded(self):
        """Every HTTP node: error output, a timeout, and at most 3 tries (ARCHITECTURE §4 header)."""
        external = [n for n in self.triage["nodes"] + self.handler["nodes"]
                    if n["type"] == "n8n-nodes-base.httpRequest"]
        self.assertGreaterEqual(len(external), 20)
        for node in external:
            with self.subTest(node["name"]):
                self.assertEqual(node.get("onError"), "continueErrorOutput")
                self.assertGreater(node["parameters"]["options"]["timeout"], 0)
                if node.get("retryOnFail"):
                    self.assertLessEqual(node["maxTries"], 3)

    def test_credentials_match_host(self):
        expect = {"__SINK_BASE_URL__": ("httpHeaderAuth", "t4-sink-auth"),
                  "__JIRA_BASE_URL__": ("httpBasicAuth", "t4-jira"),
                  "__SLACK_BASE_URL__": ("httpHeaderAuth", "t4-slack"),
                  "https://api.openai.com": ("httpHeaderAuth", "t4-llm")}
        for node in self.triage["nodes"]:
            if node["type"] != "n8n-nodes-base.httpRequest":
                continue
            url = node["parameters"]["url"].lstrip("=")
            host = next(h for h in expect if url.startswith(h))
            with self.subTest(node["name"]):
                kind, name = expect[host]
                self.assertEqual(node["credentials"], {kind: {"name": name}})
                self.assertEqual(node["parameters"]["genericAuthType"], kind)

    def test_every_error_output_is_wired(self):
        connections = self.triage["connections"]
        allowed = {"E Build Error Record", "H12r Reconcile", "E Queue?", AUDIT, "H16e Audit Failed"}
        for node in self.triage["nodes"]:
            if node.get("onError") == "continueErrorOutput":
                with self.subTest(node["name"]):
                    branches = connections[node["name"]]["main"]
                    self.assertEqual(len(branches), 2)
                    self.assertTrue(branches[1], "error output is not connected")
                    self.assertLessEqual({t["node"] for t in branches[1]}, allowed)

    def test_every_node_reaches_the_audit_row(self):
        """C-24 / no silent drop: from every node before H16 some path reaches H16 Audit Record."""
        connections = self.triage["connections"]
        for start in nodes_by_name(self.triage):
            if start == AUDIT or start in AFTER_AUDIT:
                continue
            seen, todo = {start}, deque([start])
            while todo:
                for branch in connections.get(todo.popleft(), {}).get("main", []):
                    for target in branch:
                        if target["node"] not in seen:
                            seen.add(target["node"])
                            todo.append(target["node"])
            with self.subTest(start):
                self.assertIn(AUDIT, seen)

    def test_if_branches_complete(self):
        for node in self.triage["nodes"]:
            if node["type"] == "n8n-nodes-base.if":
                with self.subTest(node["name"]):
                    branches = self.triage["connections"][node["name"]]["main"]
                    self.assertEqual(len(branches), 2)
                    self.assertTrue(branches[0] and branches[1])

    def test_first_on_error_output_nodes_names_branch_zero(self):
        """Smoke run 20261013T032636Z: `$('H3 Redact').first()` read H3's empty error branch from H16 (pii_counts {}).
        A node with an error output is read with first(0), here through `pick`."""
        nodes = nodes_by_name(self.triage)
        with_error = {name for name, n in nodes.items() if n.get("onError") == "continueErrorOutput"}
        for node in self.triage["nodes"]:
            text = node["parameters"].get("jsCode") or json.dumps(node["parameters"])
            for target in re.findall(r"\$\('([^']+)'\)\.first\(\)", text):
                with self.subTest(node=node["name"], target=target):
                    self.assertNotIn(target, with_error)
            if "const pick" in text:
                self.assertIn("$(name).first(0).json", text, node["name"])

    def test_slack_text_from_build_nodes_only(self):
        nodes = nodes_by_name(self.triage)
        for slack, build in SLACK_NODES.items():
            with self.subTest(slack):
                body = nodes[slack]["parameters"]["jsonBody"]
                self.assertEqual(body, "={{ $('" + build + "').first(0).json.slack_body }}")
                js = nodes[build]["parameters"]["jsCode"]
                self.assertIn("unfurl_links: false", js)
                self.assertIn("slack_channel_", js)
                self.assertIn(".replace(/</g, '&lt;')", js)

    def test_config(self):
        cfg = config_items(self.triage)
        self.assertLessEqual(CONFIG_KEYS, set(cfg))
        self.assertNotIn("slice_mode", cfg)
        self.assertEqual(cfg["always_review"], ["privacy", "other"])
        self.assertEqual(set(cfg["tau_category"]), set(CATEGORIES))
        self.assertEqual(set(cfg["tau_priority"]), {"P1", "P2", "P3", "P4"})
        # G9: Config tau = evals/thresholds.json (HARNESS_SPEC §3.6); policy classes never auto-route.
        thresholds = load(THRESHOLDS)
        self.assertEqual(cfg["tau_category"], thresholds["tau_category"])
        self.assertEqual(cfg["tau_priority"], thresholds["tau_priority"])
        self.assertEqual({cfg["tau_category"][c] for c in cfg["always_review"]}, {1.01})
        self.assertIs(cfg["tuning_mode"], False)     # only a dev run sets it, in memory
        self.assertEqual(cfg["llm_model"], "gpt-4o-mini-2024-07-18")
        self.assertNotEqual(cfg["slack_channel_triage"], cfg["slack_channel_review"])
        self.assertTrue(cfg["slack_channel_triage"] and cfg["slack_channel_review"])
        # llm_prompt_chars bounds the non-ticket part of the H6 request (C-8 estimate).
        body = nodes_by_name(self.triage)["H6 LLM Classify"]["parameters"]["jsonBody"]
        system = json.loads(re.search(r"role: 'system', content: (\".*?(?<!\\)\") \}", body).group(1))
        self.assertGreater(cfg["llm_prompt_chars"], len(system))


class EmbeddedJsTest(unittest.TestCase):
    def test_blocks_equal_src_js(self):
        seen = set()
        for workflow in (load(TRIAGE), load(HANDLER)):
            for node in workflow["nodes"]:
                code = node["parameters"].get("jsCode") or ""
                for path, text in BLOCK.findall(code):
                    with self.subTest(node=node["name"], path=path):
                        self.assertEqual(text, (ROOT / path).read_text(encoding="utf-8"))
                        seen.add(path)
        self.assertEqual(seen, {"src/js/" + p.name for p in JS_DIR.glob("*.js")})

    def test_each_control_node_holds_its_file(self):
        nodes = nodes_by_name(load(TRIAGE))
        for name, path in (("H1 Intake Guard", "src/js/norm.js"), ("H3 Redact", "src/js/redact.js"),
                           ("H4 Injection Scan + Cap", "src/js/inject.js"),
                           ("H8 Parse + Confidence", "src/js/confidence.js")):
            with self.subTest(name):
                self.assertIn(path, [p for p, _ in BLOCK.findall(nodes[name]["parameters"]["jsCode"])])

    @unittest.skipUnless(NODE, "node not installed")
    def test_every_code_node_compiles(self):
        for workflow in (load(TRIAGE), load(HANDLER)):
            for node in workflow["nodes"]:
                if node["type"] != "n8n-nodes-base.code":
                    continue
                with self.subTest(node["name"]):
                    out = subprocess.run([NODE, "-e", "const A = Object.getPrototypeOf(async function () {})"
                                          ".constructor; new A('$input', '$json', '$', '$execution', '$prevNode', "
                                          "require('fs').readFileSync(0, 'utf8'));"],
                                         input=node["parameters"]["jsCode"], capture_output=True, text=True,
                                         timeout=60)
                    self.assertEqual(out.returncode, 0, out.stderr)


class LlmBodyTest(unittest.TestCase):
    def setUp(self):
        self.workflow = load(TRIAGE)
        self.node = nodes_by_name(self.workflow)["H6 LLM Classify"]
        self.body = self.node["parameters"]["jsonBody"]

    def test_references_only_model_text_and_config(self):
        refs = set(re.findall(r"\$json\.([A-Za-z_][A-Za-z0-9_]*)", self.body))
        self.assertIn("model_text", refs)
        self.assertLessEqual(refs, {"model_text"} | set(config_items(self.workflow)))
        params = json.dumps(self.node["parameters"])
        for other in ("$(", "$input", "$node", "$items", "$env", "$prevNode"):
            self.assertNotIn(other, params)

    def test_one_expression(self):
        self.assertTrue(self.body.startswith("={{"))
        self.assertEqual((self.body.count("{{"), self.body.count("}}")), (1, 1))

    def test_request_shape(self):
        p = self.node["parameters"]
        self.assertEqual((p["method"], p["url"]), ("POST", "https://api.openai.com/v1/chat/completions"))
        self.assertEqual(self.node["credentials"], {"httpHeaderAuth": {"name": "t4-llm"}})
        self.assertEqual((self.node["retryOnFail"], self.node["maxTries"]), (True, 2))
        self.assertEqual(p["options"]["timeout"], 30000)
        for part in ("temperature: 0", "logprobs: true", "top_logprobs: 5", "type: 'json_schema'", "strict: true",
                     "'<ticket>\\n' + $json.model_text + '\\n</ticket>'"):
            self.assertIn(part, self.body)
        self.assertNotIn("tools", self.body)
        self.assertNotIn("function_call", self.body)

    def test_schema_enums_match_scorer(self):
        enums = re.findall(r'"enum": \[([^\]]*)\]', self.body)
        values = [json.loads("[" + e + "]") for e in enums]
        self.assertEqual(values, [list(CATEGORIES), list(PRIORITY_WORDS), list(URGENCIES)])
        self.assertIn('"additionalProperties": false', self.body)


@unittest.skipUnless(NODE, "node not installed")
class NormJsTest(unittest.TestCase):
    JS = JS_DIR / "norm.js"

    def test_plain_es2019(self):
        assert_plain_es2019(self, self.JS)

    def test_text_and_email_vectors(self):
        self.assertEqual(run_js(self.JS, "textNorm", [[raw] for raw, _ in TEXT_VECTORS]),
                         [text_norm(raw) for raw, _ in TEXT_VECTORS])
        self.assertEqual(run_js(self.JS, "emailNorm", [[raw] for raw, _ in EMAIL_VECTORS]),
                         [email_norm(raw) for raw, _ in EMAIL_VECTORS])

    def test_keys_equal_python(self):
        self.assertEqual(run_js(self.JS, "dedupeKey", [list(a) for a, _ in DEDUPE_VECTORS]),
                         [dedupe_key(*a) for a, _ in DEDUPE_VECTORS])
        self.assertEqual(run_js(self.JS, "contentSha256", [list(a) for a, _ in CONTENT_VECTORS]),
                         [content_sha256(*a) for a, _ in CONTENT_VECTORS])
        self.assertEqual(run_js(self.JS, "dedupeKey", [["email", ""], ["", "m-1"], [None, "m-1"]]), [None] * 3)

    def test_sha256_unicode_and_block_edges(self):
        texts = ["", "abc", "x" * 55, "x" * 56, "y" * 64, "z" * 119, "Caf\u00e9 \u20ac \U0001F600 \ufeff"]
        self.assertEqual(run_js(self.JS, "sha256Hex", [[t] for t in texts]),
                         [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts])


def completion(content, alternatives=None, logprob=-0.01, tokens=None):
    """A STUB chat completion. `tokens` splits `content`; `alternatives` maps a token to extra top_logprobs."""
    tokens = tokens or re.findall(r'[{}:,"]|[a-z_]+', content)
    assert "".join(tokens) == content
    alternatives = alternatives or {}
    rows = []
    for tok in tokens:
        top = [{"token": tok, "logprob": logprob}] + [{"token": t, "logprob": lp} for t, lp in alternatives.get(tok, [])]
        rows.append({"token": tok, "logprob": logprob, "top_logprobs": top})
    return {"choices": [{"message": {"content": content}, "logprobs": {"content": rows}}]}


@unittest.skipUnless(NODE, "node not installed")
class ConfidenceJsTest(unittest.TestCase):
    JS = JS_DIR / "confidence.js"
    CONTENT = '{"category":"billing","priority":"high","urgency":"medium"}'

    def classify(self, *completions):
        return run_js(self.JS, "classifyCompletion", [[c] for c in completions])

    def test_plain_es2019(self):
        assert_plain_es2019(self, self.JS)

    def test_renormalised_first_token(self):
        alt = {"billing": [("bug", math.log(0.2)), ("access", math.log(0.1)), ("xyz", math.log(0.3))],
               "high": [("critical", math.log(0.5))]}
        out, = self.classify(completion(self.CONTENT, alt, logprob=math.log(0.6)))
        self.assertEqual((out["category"], out["priority"], out["urgency"]), ("billing", "P2", "medium"))
        self.assertEqual(out["conf_source"], "logprobs")
        self.assertAlmostEqual(out["conf_category"], 0.6 / 0.9, places=5)   # "xyz" starts no enum value
        self.assertAlmostEqual(out["conf_priority"], 0.6 / 1.1, places=5)
        self.assertEqual(out["conf_urgency"], 1)
        self.assertEqual(out["reasons"], [])

    def test_token_with_quote_prefix(self):
        tokens = ['{"', 'category', '":', '"how', 'to', '","', 'priority', '":"', 'normal', '","', 'urgency', '":"',
                  'low', '"}']
        content = "".join(tokens)
        alt = {'"how': [('"feature', math.log(0.25)), ('"out', math.log(0.25))]}
        out, = self.classify(completion(content, alt, logprob=math.log(0.5), tokens=tokens))
        self.assertEqual(out["category"], "howto")
        self.assertAlmostEqual(out["conf_category"], 0.5, places=5)
        self.assertEqual(out["first_tokens"]["category"]["prefix"], '"')

    def test_no_logprobs_fails_closed(self):
        out, = self.classify({"choices": [{"message": {"content": self.CONTENT}}]})
        self.assertEqual((out["category"], out["conf_source"], out["conf_category"]), ("billing", "none", 0))
        self.assertEqual(out["reasons"], ["confidence:no_logprobs"])

    def test_schema_miss(self):
        bad = ['not json', '{"category":"sales","priority":"high","urgency":"low"}',
               '{"category":"bug","priority":"high"}', '[]']
        for out in self.classify(*({"choices": [{"message": {"content": c}}]} for c in bad)):
            self.assertEqual((out["category"], out["reasons"]), ("", ["schema_miss"]))
        out, = self.classify({})
        self.assertEqual(out["reasons"], ["schema_miss"])

    def test_ambiguous_chosen_token_fails_closed(self):
        tokens = ['{"', 'category', '":"', 'b', 'ug', '","', 'priority', '":"', 'low', '","', 'urgency', '":"',
                  'low', '"}']
        out, = self.classify(completion("".join(tokens), tokens=tokens))
        self.assertEqual(out["conf_source"], "none")
        self.assertEqual(out["reasons"], ["confidence:no_logprobs"])


@unittest.skipUnless(NODE, "node not installed")
class IntakeGuardTest(unittest.TestCase):
    """H1 on all 200 gold tickets: keys equal gold (C-4) and rejects equal gold `malformed:<code>` (C-2, C-3)."""

    def test_gold_keys_and_rejects(self):
        workflow = load(TRIAGE)
        cfg = config_items(workflow)
        golds = [load(p) for p in sorted(GOLD.glob("t4-*.json"))]
        items = [dict(cfg, headers={"x-replay-run-id": "stub-run", "x-replay-input-id": g["input_id"]},
                      body=g["ticket"], params={}, query={}) for g in golds]
        outs = run_code(nodes_by_name(workflow)["H1 Intake Guard"]["parameters"]["jsCode"], items)
        for gold, out in zip(golds, outs):
            with self.subTest(gold["input_id"]):
                self.assertNotIn("headers", out)
                self.assertNotIn("body", out)
                self.assertEqual(out["content_sha256"], gold["content_sha256"])
                self.assertEqual(out["dedupe_key"], gold["dedupe_key"] or "")
                reason = gold.get("review_reason") or ""
                want = "reject:" + reason.split(":", 1)[1] if reason.startswith("malformed:") else None
                self.assertEqual(out.get("error_code"), want)
                self.assertEqual((out["run_id"], out["input_ref"]), ("stub-run", gold["input_id"]))


@unittest.skipUnless(NODE, "node not installed")
class ControlNodesTest(unittest.TestCase):
    """G8 Code nodes under node, upstream nodes stubbed by name (STUB items), against ARCHITECTURE §3."""

    @classmethod
    def setUpClass(cls):
        cls.workflow = load(TRIAGE)
        cls.nodes = nodes_by_name(cls.workflow)
        cls.cfg = config_items(cls.workflow)

    def node(self, name, item=None, upstream=None, prev=""):
        return run_code(self.nodes[name]["parameters"]["jsCode"], [item or {}], upstream, prev)[0]

    def labels(self, **extra):
        item = dict(self.cfg, run_id="stub-run", input_ref="STUB-1", dedupe_key="stubkey0000000000001",
                    category="bug", conf_category=0.97, priority="P3", conf_priority=0.91, urgency="medium",
                    conf_source="logprobs", reasons=[], redacted_subject="Export fails", redacted_body="CSV is empty.",
                    truncated=0, injection_signals=[])
        item.update(extra)
        return item

    # ------------------------------------------------------------ H2 dedupe (C-18 steps 1-2)
    def dedupe(self, links, same):
        return self.node("H2 Dedupe Check", {"rows": same}, {
            "H1 Intake Guard": {"dedupe_key": "stubkey0000000000001"}, "H2 Link Lookup": {"rows": links}})

    def test_h2_content_lookup_matches_error_rows(self):
        url = self.nodes["H2 Content Lookup"]["parameters"]["url"]
        self.assertTrue(url.endswith("&status=auto_routed%7Creview%7Cerror"), url)

    def test_dedupe_error_row_counts_only_with_issue_key(self):
        out = self.dedupe([], [])
        self.assertEqual((out["dedupe_route"], out["duplicate_via"]), ("new", ""))
        out = self.dedupe([{"issue_key": "T4-1"}], [])
        self.assertEqual((out["dedupe_route"], out["duplicate_via"], out["duplicate_issue_key"]),
                         ("duplicate", "jira_links", "T4-1"))
        out = self.dedupe([], [{"status": "review", "issue_key": ""}])
        self.assertEqual((out["dedupe_route"], out["duplicate_via"]), ("duplicate", "content"))
        # H13 failed after the issue existed (Q-34): the replay skips the model call.
        out = self.dedupe([], [{"status": "error", "issue_key": "T4-2"}])
        self.assertEqual((out["dedupe_route"], out["duplicate_via"], out["duplicate_issue_key"]),
                         ("duplicate", "content", "T4-2"))
        # An error row without an issue (queue append failed) is processed again.
        out = self.dedupe([], [{"status": "error", "issue_key": ""}])
        self.assertEqual(out["dedupe_route"], "new")

    # ------------------------------------------------------------ H5 spend gate (C-8)
    def spend(self, day=0.0, run=0.0, count=0, model_text="Subject: x\n\nbody"):
        h4 = dict(self.cfg, run_id="stub-run", model_text=model_text)
        return self.node("H5 Spend Check", {"count": count}, {
            "H4 Injection Scan + Cap": h4, "H5 Day Spend": {"usd": day, "count": 0},
            "H5 Run Spend": {"usd": run, "count": 0}})

    def test_spend_gate_passes_under_caps(self):
        out = self.spend()
        cfg = self.cfg
        chars = cfg["llm_prompt_chars"] + len("Subject: x\n\nbody")
        want = (chars * cfg["llm_price_in_per_mtok"] + cfg["max_output_tokens"] * cfg["llm_price_out_per_mtok"]) / 1e6
        self.assertAlmostEqual(out["est_usd"], want, places=12)
        self.assertEqual((out["spend_route"], out["capped"], out["reasons"]), ("call", 0, []))
        self.assertEqual(out["model_text"], "Subject: x\n\nbody")   # H6 reads model_text from this item

    def test_spend_gate_caps(self):
        for kwargs, reason in ((dict(day=self.cfg["daily_usd_cap"]), "capped:daily_usd"),
                               (dict(run=self.cfg["run_usd_cap"]), "capped:run_usd"),
                               (dict(count=self.cfg["llm_max_rpm"]), "capped:llm_rpm")):
            with self.subTest(reason):
                out = self.spend(**kwargs)
                self.assertEqual((out["spend_route"], out["capped"], out["reasons"]), ("capped", 1, [reason]))

    # ------------------------------------------------------------ H9 validate (C-14)
    def validate(self, **extra):
        return self.node("H9 Validate", self.labels(**extra))["reasons"]

    def test_validate_rules(self):
        self.assertEqual(self.validate(), [])
        self.assertEqual(self.validate(category="outage", priority="P3"), ["rule:outage_priority"])
        self.assertEqual(self.validate(category="outage", priority="P2"), [])
        self.assertEqual(self.validate(category="other", priority="P1"), ["rule:other_p1"])
        self.assertEqual(self.validate(urgency="high", priority="P4"), ["rule:urgent_low"])
        self.assertEqual(self.validate(redacted_body="Please delete my data under the GDPR."),
                         ["rule:privacy_keywords"])
        self.assertEqual(self.validate(category="privacy", redacted_body="A GDPR data subject request."), [])
        self.assertEqual(self.validate(category="outage", priority="P1", truncated=1), ["rule:truncated_sensitive"])
        self.assertEqual(self.validate(truncated=1), [])
        self.assertEqual(self.validate(injection_signals=["role_override"]), ["injection"])

    def test_validate_keeps_parse_reasons(self):
        self.assertEqual(self.validate(category="", priority="", urgency="", reasons=["schema_miss"],
                                       injection_signals=["slack_mention"]), ["schema_miss", "injection"])

    # ------------------------------------------------------------ H10 decide (C-15, C-16)
    def decide(self, **extra):
        out = self.node("H10 Decide", self.labels(**extra))
        return out["route"], out["reasons"]

    def test_tau_never_sends_everything_to_review(self):
        never_cat, never_pri = {c: 1.01 for c in CATEGORIES}, {p: 1.01 for p in ("P1", "P2", "P3", "P4")}
        self.assertEqual(self.decide(conf_category=1, conf_priority=1, tau_category=never_cat, tau_priority=never_pri),
                         ("review", ["threshold:category", "threshold:priority"]))

    def test_tuning_mode_counts_every_tau_as_zero(self):
        never_cat, never_pri = {c: 1.01 for c in CATEGORIES}, {p: 1.01 for p in ("P1", "P2", "P3", "P4")}
        for flag in (True, "true"):      # --config-override keeps the type; a string form also counts
            with self.subTest(flag):
                self.assertEqual(self.decide(tau_category=never_cat, tau_priority=never_pri, tuning_mode=flag,
                                             conf_category=0.31, conf_priority=0.2), ("auto", []))
        self.assertEqual(self.decide(tau_category=never_cat, tau_priority=never_pri, tuning_mode=True,
                                     category="other", reasons=["rule:urgent_low"]),
                         ("review", ["rule:urgent_low", "policy:other"]))      # rules and policy still apply
        self.assertEqual(self.decide(tau_category=never_cat, tau_priority=never_pri, tuning_mode=False,
                                     conf_category=1, conf_priority=1),
                         ("review", ["threshold:category", "threshold:priority"]))

    def test_tau_zero_auto_routes_clean_labels(self):
        zero_cat, zero_pri = {c: 0 for c in CATEGORIES}, {p: 0 for p in ("P1", "P2", "P3", "P4")}
        self.assertEqual(self.decide(tau_category=zero_cat, tau_priority=zero_pri), ("auto", []))
        # tune.py --apply writes JSON strings; both forms decide the same.
        self.assertEqual(self.decide(tau_category=json.dumps(zero_cat), tau_priority=json.dumps(zero_pri)),
                         ("auto", []))
        self.assertEqual(self.decide(tau_category=zero_cat, tau_priority=zero_pri, category="privacy"),
                         ("review", ["policy:privacy"]))
        self.assertEqual(self.decide(tau_category=zero_cat, tau_priority=zero_pri, reasons=["injection"]),
                         ("review", ["injection"]))
        self.assertEqual(self.decide(tau_category={"billing": 0}, tau_priority=zero_pri),
                         ("review", ["threshold:category"]))        # a missing tau fails closed
        self.assertEqual(self.decide(tau_category=zero_cat, tau_priority=zero_pri, category="", priority=""),
                         ("review", ["schema_miss"]))

    # ------------------------------------------------------------ H11 route (C-18 step 3, C-21)
    def route(self, issues, creates=0):
        return self.node("H11 Route", {"issues": issues}, {
            "H10 Decide": self.labels(route="auto"), "H11 Create Count": {"count": creates, "rows": []}})

    def test_route(self):
        out = self.route([])
        self.assertEqual((out["next"], out["capped"], out["reasons"]), ("create", 0, []))
        out = self.route([{"id": "10003", "key": "SUP-3"}])
        self.assertEqual((out["next"], out["found_key"]), ("link", "SUP-3"))
        out = self.route([], creates=self.cfg["jira_max_creates_per_run"])
        self.assertEqual((out["next"], out["capped"], out["reasons"]), ("capped", 1, ["capped:jira_creates"]))

    # ------------------------------------------------------------ H13 build link + Slack text (C-18 step 6, C-20)
    def test_link_created_via(self):
        out = self.node("H13 Build Link", {"id": "10001", "key": "SUP-1"},
                        {"H10 Decide": self.labels(), "H12 Jira Create": {"key": "SUP-1"}})
        self.assertEqual((out["source"], out["link_row"]["created_via"], out["notify"]), ("H12", "create", "yes"))
        self.assertEqual(set(out["link_row"]), set(SINK_COLUMNS["jira_links"]))
        out = self.node("H13 Build Link", {"issues": [{"key": "SUP-2"}]},
                        {"H10 Decide": self.labels(), "H12 Jira Create": None, "H12r Reconcile": {}})
        self.assertEqual((out["source"], out["issue_key"], out["link_row"]["created_via"]), ("H12r", "SUP-2", "search"))
        out = self.node("H13 Build Link", {"key": "SUP-5"}, {"H10 Decide": self.labels(), "H12 Jira Create": None,
                                                            "H12r Reconcile": {}, "H12b Jira Create (retry once)": {}})
        self.assertEqual((out["source"], out["link_row"]["created_via"]), ("H12b", "retry"))
        out = self.node("H13 Build Link", self.labels(found_key="SUP-4"), {"H10 Decide": self.labels()})
        self.assertEqual((out["source"], out["issue_key"], out["notify"]), ("H11", "SUP-4", "no"))

    def test_slack_triage_text_is_escaped(self):
        decide = self.labels(category="<!channel>", dedupe_key="<https://x.example.invalid|y>&")
        out = self.node("H13 Build Link", {"key": "SUP-1"}, {"H10 Decide": decide, "H12 Jira Create": {}})
        body = out["slack_body"]
        self.assertEqual((body["channel"], body["unfurl_links"], body["unfurl_media"]),
                         (self.cfg["slack_channel_triage"], False, False))
        self.assertNotIn("<", body["text"])
        self.assertIn("&lt;!channel&gt;", body["text"])
        self.assertIn("&amp;", body["text"])

    # ------------------------------------------------------------ H15 review (C-22)
    def test_review_row_and_post(self):
        out = self.node("H15 Build Review", self.labels(category="privacy", reasons=["policy:privacy"]))
        row = out["review_row"]
        self.assertEqual(set(row), set(SINK_COLUMNS["review_queue"]))
        self.assertEqual((row["reasons"], row["category"], row["redacted_body"]), (["policy:privacy"], "privacy",
                                                                                   "CSV is empty."))
        self.assertEqual(out["slack_body"]["channel"], self.cfg["slack_channel_review"])
        self.assertIn("policy:privacy", out["slack_body"]["text"])
        self.assertNotIn("CSV is empty", out["slack_body"]["text"])        # no ticket text in Slack
        capped = self.node("H15 Build Review", dict(self.cfg, run_id="r", dedupe_key="k", reasons=["capped:run_usd"],
                                                    redacted_subject="s", redacted_body="b"))
        self.assertEqual((capped["review_row"]["category"], capped["review_row"]["conf_category"]), ("", ""))
        self.assertIn("unclassified", capped["slack_body"]["text"])

    # ------------------------------------------------------------ E (C-25)
    def error(self, prev, item=None, **upstream):
        ran = {"H1 Intake Guard": {"run_id": "stub-run", "input_ref": "STUB-1", "dedupe_key": "k1"}}
        ran.update(upstream)
        return self.node("E Build Error Record", item or {"error": {"message": "503 - injected"}}, ran, prev)

    def test_error_record_codes_and_queue(self):
        out = self.error("H1 Continue?", {"error_node": "H1 Intake Guard", "error_code": "reject:body_too_long",
                                          "error_stage": "intake", "error_message": "intake limit"})
        self.assertEqual((out["code"], out["stage"], out["queue"], out["nonfatal"]),
                         ("reject:body_too_long", "intake", "yes", False))
        self.assertEqual(set(out["error_row"]), set(SINK_COLUMNS["errors"]))
        self.assertEqual(set(out["review_row"]), set(SINK_COLUMNS["review_queue"]))
        self.assertEqual((out["review_row"]["redacted_body"], out["review_row"]["reasons"]),
                         ("", ["reject:body_too_long"]))
        out = self.error("H6 LLM Classify", **{"H3 Redact": {"redacted_subject": "s", "redacted_body": "b"}})
        self.assertEqual((out["code"], out["stage"], out["queue"]), ("error:llm", "classify", "yes"))
        self.assertEqual((out["review_row"]["redacted_subject"], out["error_row"]["message"]), ("s", "503 - injected"))
        for prev, code, stage in (("H12b Jira Create (retry once)", "error:jira", "act"),
                                  ("H12r Reconcile", "error:jira", "act"), ("H2 Link Lookup", "error:sink", "intake"),
                                  ("H5 Rate Count", "error:sink", "classify")):
            with self.subTest(prev):
                out = self.error(prev)
                self.assertEqual((out["code"], out["stage"], out["queue"]), (code, stage, "yes"))
        self.assertEqual(self.error("H14 Slack Notify")["nonfatal"], True)
        self.assertEqual(self.error("H14 Slack Notify")["queue"], "no")
        self.assertEqual(self.error("H15s Slack Review Post")["code"], "error:slack")
        self.assertEqual(self.error("H13 Link Record", **{"H13 Build Link": {"issue_key": "SUP-9"}})["queue"], "no")
        self.assertEqual(self.error("H15 Review Queue")["queue"], "no")

    # ------------------------------------------------------------ H16 terminal audit row (C-24)
    def audit(self, **ran):
        upstream = {"H1 Intake Guard": {"run_id": "stub-run", "input_ref": "STUB-1", "dedupe_key": "k1",
                                        "content_sha256": "c1", "started_ms": 1}}
        upstream.update({k.replace("_", " "): v for k, v in ran.items()})
        return self.node(AUDIT, {}, upstream)

    def classified(self, **more):
        ran = {"H2_Dedupe_Check": {"dedupe_route": "new"}, "H3_Redact": {"pii_counts": {"email": 1}},
               "H4_Injection_Scan_+_Cap": {"injection_signals": [], "truncated": 0},
               "H5_Spend_Check": {"capped": 0, "reasons": []},
               "H7_Cost_Record": {"tokens_in": 900, "tokens_out": 20, "usd": 0.000147},
               "H8_Parse_+_Confidence": self.labels(), "H10_Decide": self.labels(route="auto")}
        ran.update(more)
        return ran

    def test_audit_columns_frozen(self):
        self.assertEqual(set(self.audit()), set(SINK_COLUMNS["audit"]))

    def test_audit_status_matrix(self):
        auto = dict(H11_Route=dict(self.labels(), capped=0), H13_Build_Link={"source": "H12", "issue_key": "SUP-1"},
                    H13_Link_Record={"row": {}})
        cases = [
            ("rejected", dict(E_Build_Error_Record={"code": "reject:attachment_type", "stage": "intake",
                                                    "nonfatal": False}, E_Review_Queue_Append={"row": {}})),
            ("duplicate_skip", dict(H2_Dedupe_Check={"dedupe_route": "duplicate", "duplicate_via": "content",
                                                     "duplicate_issue_key": ""})),
            ("auto_routed", self.classified(**auto, H14_Slack_Notify={"ok": True})),
            ("auto_routed", self.classified(**auto, H14_Slack_Notify=None,
                                            E_Build_Error_Record={"code": "error:slack", "nonfatal": True})),
            ("duplicate_skip", self.classified(H11_Route=self.labels(), H13_Build_Link={"source": "H11",
                                                                                        "issue_key": "SUP-4"},
                                               H13_Link_Record={"row": {}})),
            ("review", self.classified(H10_Decide=self.labels(reasons=["threshold:category"]),
                                       H15_Build_Review={}, H15_Review_Queue={"row": {}},
                                       H15s_Slack_Review_Post={"ok": True})),
            ("review", dict(H2_Dedupe_Check={"dedupe_route": "new"}, H5_Spend_Check={"capped": 1,
                                                                                    "reasons": ["capped:run_usd"]},
                            H15_Review_Queue={"row": {}})),
            ("review", self.classified(H12_Jira_Create=None, H12r_Reconcile={}, **{
                "H12b_Jira_Create_(retry_once)": None},
                E_Build_Error_Record={"code": "error:jira", "stage": "act", "nonfatal": False},
                E_Review_Queue_Append={"row": {}})),
            ("error", self.classified(**dict(auto, H13_Link_Record=None),
                                      E_Build_Error_Record={"code": "error:sink", "stage": "act", "nonfatal": False})),
            ("error", self.classified(H6_LLM_Classify=None, E_Build_Error_Record={"code": "error:llm",
                                                                                  "nonfatal": False},
                                      E_Review_Queue_Append=None)),
        ]
        rows = [self.audit(**ran) for _, ran in cases]
        self.assertEqual([r["status"] for r in rows], [status for status, _ in cases])
        rejected, dup, auto_row, slack_failed, h11, review, capped, jira_err, link_err, queue_err = rows
        self.assertEqual((rejected["reasons"], rejected["stage"], rejected["tokens_in"]),
                         (["reject:attachment_type"], "intake", 0))
        self.assertEqual(dup["reasons"], ["duplicate:content"])
        self.assertEqual((auto_row["issue_key"], auto_row["notify_ok"], auto_row["usd"], auto_row["ok"]),
                         ("SUP-1", 1, 0.000147, 1))
        self.assertEqual((slack_failed["notify_ok"], slack_failed["reasons"]), (0, []))
        self.assertEqual((h11["issue_key"], h11["reasons"]), ("SUP-4", ["duplicate:jira_search"]))
        self.assertEqual((review["notify_ok"], review["reasons"]), (1, ["threshold:category"]))
        self.assertEqual((capped["capped"], capped["reasons"], capped["usd"]), (1, ["capped:run_usd"], 0))
        self.assertEqual(jira_err["reasons"], ["error:jira"])
        self.assertEqual((link_err["issue_key"], link_err["ok"]), ("SUP-1", 0))
        self.assertEqual(queue_err["reasons"], ["error:llm"])


if __name__ == "__main__":
    unittest.main()
