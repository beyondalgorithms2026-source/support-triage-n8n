"""Workflow JSON contract for the G7 slice (GOALS G7): static checks, embedded JS equals src/js, H6 body references
only `model_text` and Config, and the Code-node JS behaves as the Python references do under node.

STUB completions below are hand-built test inputs for src/js/confidence.js, not run evidence.
"""
import hashlib
import json
import math
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from src.checks.static_checks import check_file
from src.common.norm import content_sha256, dedupe_key, email_norm, text_norm
from src.score.score import CATEGORIES, PRIORITY_WORDS, URGENCIES, is_llm_node
from tests.test_norm import CONTENT_VECTORS, DEDUPE_VECTORS, EMAIL_VECTORS, TEXT_VECTORS
from tests.test_redact import NODE, assert_plain_es2019, run_js

ROOT = Path(__file__).resolve().parents[1]
TRIAGE = ROOT / "workflows" / "t4-triage.json"
HANDLER = ROOT / "workflows" / "t4-error-handler.json"
JS_DIR = ROOT / "src" / "js"
GOLD = ROOT / "evals" / "gold"
CREDENTIALS = {"t4-llm", "t4-webhook-auth", "t4-sink-auth", "t4-jira", "t4-slack"}
SLICE_PREFIXES = ("H1", "H3", "H4", "H6", "H7", "H8", "H10", "H12", "H13", "H16")
CONFIG_KEYS = {"llm_model", "llm_price_in_per_mtok", "llm_price_out_per_mtok", "run_usd_cap", "daily_usd_cap",
               "llm_max_rpm", "max_body_chars", "max_model_chars", "max_output_tokens", "allowed_attachment_types",
               "jira_project_key", "jira_issue_type", "jira_max_creates_per_run", "always_review", "tau_category",
               "tau_priority", "slice_mode"}
BLOCK = re.compile(r"// BEGIN (src/js/[a-z_]+\.js)\n(.*?)// END \1\n", re.S)
# Runs one Code node body the way n8n does (async function body), with $input / $ / $execution stubs.
CODE_HARNESS = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const fn = new AsyncFunction('$input', '$json', '$', '$execution', input.code);
(async function () {
  const out = [];
  for (const json of input.items) {
    const item = { json };
    const $input = { first: () => item, all: () => [item] };
    const $ = () => { throw new Error('no other nodes in this harness'); };
    out.push((await fn($input, json, $, { id: 'stub' }))[0].json);
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


def run_code(code, items):
    out = subprocess.run([NODE, "-e", CODE_HARNESS], input=json.dumps({"code": code, "items": items}),
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

    def test_slice_nodes_present(self):
        names = list(nodes_by_name(self.triage))
        prefixes = {name.split(" ", 1)[0] for name in names}
        for prefix in SLICE_PREFIXES:
            self.assertIn(prefix, prefixes)
        self.assertIn("0. Config", names)
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
        node = nodes_by_name(self.triage)["H12 Jira Create"]
        self.assertIs(node["retryOnFail"], False)
        self.assertEqual(node["credentials"], {"httpBasicAuth": {"name": "t4-jira"}})
        self.assertEqual(node["parameters"]["genericAuthType"], "httpBasicAuth")

    def test_every_error_output_is_wired(self):
        connections = self.triage["connections"]
        for node in self.triage["nodes"]:
            if node.get("onError") == "continueErrorOutput":
                with self.subTest(node["name"]):
                    branches = connections[node["name"]]["main"]
                    self.assertEqual(len(branches), 2)
                    self.assertTrue(branches[1], "error output is not connected")

    def test_config(self):
        cfg = config_items(self.triage)
        self.assertLessEqual(CONFIG_KEYS, set(cfg))
        self.assertIs(cfg["slice_mode"], True)
        self.assertEqual(cfg["always_review"], ["privacy", "other"])
        self.assertEqual(set(cfg["tau_category"]), set(CATEGORIES))
        self.assertEqual(set(cfg["tau_priority"]), {"P1", "P2", "P3", "P4"})
        self.assertEqual(cfg["llm_model"], "gpt-4o-mini-2024-07-18")


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
                                          ".constructor; new A('$input', '$json', '$', '$execution', "
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


if __name__ == "__main__":
    unittest.main()
