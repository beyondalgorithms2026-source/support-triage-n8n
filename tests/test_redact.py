"""PII redaction (C-5, ADR-004): Python reference on the shared vectors, the gold leak audit, and JS parity.

tests/vectors/redact_vectors.json is the contract for both src/common/redact.py and src/js/redact.js (H3).
The parity tests run the JS under node, the same way n8n runs a Code node: the file is pasted, not required.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from src.common.redact import PII_TYPES, audit, iban_ok, luhn_ok, redact_text, redact_ticket

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests" / "vectors" / "redact_vectors.json"
GOLD = ROOT / "evals" / "gold"
NODE = shutil.which("node")
# Reads the JS file as a Code node would hold it, calls `entry` once per argument list, prints JSON.
NODE_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const fn = new Function(src + '\nreturn ' + process.argv[2] + ';')();
const calls = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(calls.map(function (args) { return fn.apply(null, args); })));
"""
ES2019_BANNED = ("require(", "import ", "export ", "module.exports", "matchAll", "replaceAll", "??")


def run_js(js_file, entry, calls):
    """Results of `entry(*args)` for each args list, from the JS file under node."""
    out = subprocess.run([NODE, "-e", NODE_HARNESS, str(js_file), entry], input=json.dumps(calls),
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise AssertionError("node failed on {}:\n{}".format(js_file, out.stderr))
    return json.loads(out.stdout)


def gold_tickets():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(GOLD.glob("t4-*.json"))]


def assert_plain_es2019(case, js_file):
    src = Path(js_file).read_text(encoding="utf-8")
    # ASCII only: a literal U+2028 inside a regex literal is a line break to the JS parser.
    case.assertTrue(src.isascii(), "{} holds non-ASCII characters; write them as \\u escapes".format(js_file))
    for token in ES2019_BANNED:
        case.assertNotIn(token, src, "{} holds {!r}; it must paste into an n8n Code node".format(js_file, token))


class RedactVectorTest(unittest.TestCase):
    def test_vectors(self):
        for vec in json.loads(VECTORS.read_text(encoding="utf-8")):
            with self.subTest(vec["name"]):
                self.assertEqual(redact_ticket(vec["ticket"]), vec["expected"])

    def test_counts_have_every_type_in_order(self):
        self.assertEqual(list(redact_ticket({})["pii_counts"]), list(PII_TYPES))

    def test_luhn(self):
        self.assertTrue(luhn_ok("4111 1111 1111 1111"))
        self.assertTrue(luhn_ok("5555-5555-5555-4444"))
        self.assertFalse(luhn_ok("4111 1111 1111 1112"))
        self.assertFalse(luhn_ok("1234"))

    def test_iban(self):
        self.assertTrue(iban_ok("DE89 3704 0044 0532 0130 00"))
        self.assertTrue(iban_ok("GB82WEST12345698765432"))
        self.assertFalse(iban_ok("GB00WEST12345698765432"))

    def test_idempotent(self):
        once = redact_ticket({"from_name": "Dana Whitfield", "subject": "Call +1 415-555-0142",
                              "body_text": "Card 4111 1111 1111 1111, dana@example.com\nDana"})
        again = redact_ticket({"from_name": "Dana Whitfield", "subject": once["redacted_subject"],
                               "body_text": once["redacted_body"]})
        self.assertEqual(again["redacted_subject"], once["redacted_subject"])
        self.assertEqual(again["redacted_body"], once["redacted_body"])
        self.assertEqual(sum(again["pii_counts"].values()), 0)

    def test_none_text(self):
        self.assertEqual(redact_text(None), "")


class RedactGoldAuditTest(unittest.TestCase):
    def test_no_planted_value_survives(self):
        problems, totals, planted = audit(GOLD)
        self.assertEqual(problems, [])
        self.assertGreater(planted, 0)
        for kind in ("email", "phone", "card", "iban", "ssn", "ipv4", "url", "name"):
            self.assertGreater(totals[kind], 0, kind)


@unittest.skipUnless(NODE, "node not found: JS parity not checked (scripts/accept.sh G4 fails without node)")
class RedactJsParityTest(unittest.TestCase):
    JS = ROOT / "src" / "js" / "redact.js"

    def test_plain_es2019(self):
        assert_plain_es2019(self, self.JS)

    def test_vectors(self):
        vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
        got = run_js(self.JS, "redactTicket", [[v["ticket"]] for v in vectors])
        for vec, out in zip(vectors, got):
            with self.subTest(vec["name"]):
                self.assertEqual(out, vec["expected"])

    def test_gold_tickets_match_python(self):
        golds = gold_tickets()
        got = run_js(self.JS, "redactTicket", [[g["ticket"]] for g in golds])
        for gold, out in zip(golds, got):
            with self.subTest(gold["input_id"]):
                self.assertEqual(out, redact_ticket(gold["ticket"]))


if __name__ == "__main__":
    unittest.main()
