"""Golden-set generator (src/fixtures/make_tickets.py) against docs/HARNESS_SPEC.md §1 and ARCHITECTURE I-1, I-2.

These checks re-derive every property from the built gold; they do not trust the generator's own validation.
"""
import json
import re
import unittest
from collections import Counter
from pathlib import Path

from src.common.norm import content_sha256, dedupe_key
from src.fixtures import make_tickets as mt

ROOT = Path(__file__).resolve().parent.parent
GOLDS = []

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
ALLOWED_DOMAIN = re.compile(r"(^|\.)example\.(com|org|net|invalid)$", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s<>|)\]]+")
PHONE_RE = re.compile(r"(?:\+1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}")
TEST_CARDS = {"4111111111111111", "5555555555554444", "4012888888881881", "4242424242424242", "378282246310005"}
DOC_IP = re.compile(r"^(192\.0\.2|198\.51\.100|203\.0\.113)\.\d{1,3}$")    # RFC 5737
INJECTION_MARKERS = ("ignore previous", "ignore all previous", "ignore all prior", "disregard prior", "system prompt",
                     "you are now", "<!channel>", "<!here>", "@here", "<!--", "system:", "system notice")
KINDS = ("direct", "indirect")
LOCATIONS = ("subject", "body", "quoted", "signature", "attachment_name", "base64", "html_comment")
GOALS = ("force_category", "force_priority", "exfil_pii", "slack_broadcast", "jira_field", "skip_review")


def setUpModule():
    GOLDS.extend(mt.build())


def text_of(gold):
    t = gold["ticket"]
    names = " ".join(a["name"] for a in t["attachments"])
    return "\n".join((t["subject"], t["body_text"], names))


def luhn_ok(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def iban_ok(value):
    s = value.replace(" ", "")
    s = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in s)) % 97 == 1


def by_bucket(bucket):
    return [g for g in GOLDS if g["label_bucket"] == bucket]


class DeterminismTest(unittest.TestCase):
    def test_rebuild_is_byte_identical(self):
        self.assertEqual(mt.render(mt.build()), mt.render(GOLDS))

    def test_committed_files_match_generator(self):
        self.assertEqual(mt.check(ROOT), 0)

    def test_manifest_matches_gold(self):
        rows = mt.render(GOLDS)[mt.MANIFEST].splitlines()
        self.assertEqual(rows[0], ",".join(mt.MANIFEST_HEADER))
        self.assertEqual(len(rows), 201)
        for row, g in zip(rows[1:], GOLDS):
            e = g["expected"]
            self.assertEqual(row.split(","), [g["input_id"], g["split"], g["label_bucket"], e["category"],
                                              e["priority"], e["urgency"], g["expect_outcome"],
                                              "evals/gold/{}.json".format(g["input_id"])])

    def test_gold_keys_follow_frozen_order(self):
        keys = ["input_id", "synthetic", "split", "label_bucket", "hard_case", "ticket", "expected", "expect_outcome",
                "must_review", "review_reason", "dedupe_key", "content_sha256", "duplicate_of", "pii", "injection",
                "fault", "label_notes", "generator"]
        for g in GOLDS:
            self.assertEqual(list(g), keys)
            self.assertEqual(g["generator"]["seed"], 20261012)
            self.assertTrue(g["synthetic"])
            self.assertTrue(g["label_notes"].strip())


class CountsTest(unittest.TestCase):
    def test_ids_buckets_splits(self):
        self.assertEqual([g["input_id"] for g in GOLDS], ["t4-{:03d}".format(i) for i in range(1, 201)])
        self.assertEqual(Counter(g["label_bucket"] for g in GOLDS),
                         Counter({"clean": 104, "hard": 48, "injection": 16, "pii": 12, "duplicate": 12, "malformed": 8}))
        self.assertEqual(Counter(g["split"] for g in GOLDS), Counter({"dev": 100, "test": 100}))

    def test_category_floor_and_clean_hard_per_category(self):
        cats = Counter(g["expected"]["category"] for g in GOLDS)
        for c in mt.CATEGORIES:
            self.assertGreaterEqual(cats[c], 20, c)
            self.assertEqual(sum(1 for g in by_bucket("clean") if g["expected"]["category"] == c), 13, c)
            self.assertEqual(sum(1 for g in by_bucket("hard") if g["expected"]["category"] == c), 6, c)

    def test_stratified_by_category_and_bucket(self):
        for bucket in ("clean", "hard", "injection", "pii", "malformed"):
            for c in mt.CATEGORIES:
                n = Counter(g["split"] for g in by_bucket(bucket) if g["expected"]["category"] == c)
                self.assertLessEqual(abs(n["dev"] - n["test"]), 1, (bucket, c))

    def test_every_hard_kind_in_both_splits(self):
        for kind in mt.HARD_KINDS:
            splits = {g["split"] for g in by_bucket("hard") if g["hard_case"] == kind}
            self.assertEqual(splits, {"dev", "test"}, kind)


class LabelRulesTest(unittest.TestCase):
    def test_cross_check_rules_hold_on_gold(self):
        # ARCHITECTURE C-14 R1-R3: correct gold must not trip the validator by itself.
        for g in GOLDS:
            e = g["expected"]
            if e["category"] == "outage":
                self.assertIn(e["priority"], ("P1", "P2"), g["input_id"])
            if e["category"] == "other":
                self.assertNotEqual(e["priority"], "P1", g["input_id"])
            if e["urgency"] == "high":
                self.assertNotEqual(e["priority"], "P4", g["input_id"])

    def test_privacy_keywords_only_in_privacy_tickets(self):
        # R4 would send any other ticket to review; keep that a model miss, not a label artefact.
        for g in GOLDS:
            if g["expected"]["category"] != "privacy":
                low = text_of(g).lower()
                for kw in mt.PRIVACY_KEYWORDS:
                    self.assertNotIn(kw, low, g["input_id"])

    def test_expected_outcomes(self):
        for g in GOLDS:
            cat, bucket, out = g["expected"]["category"], g["label_bucket"], g["expect_outcome"]
            if bucket == "injection":
                self.assertEqual(out, "review")
                self.assertEqual(g["review_reason"], "injection")
            elif bucket == "duplicate" and g["duplicate_of"]:
                self.assertEqual(out, "duplicate_skip")
            elif bucket == "malformed" and g["review_reason"]:
                self.assertEqual(out, "rejected")
            else:
                self.assertEqual(out, "review" if cat in ("privacy", "other") else "auto_route", g["input_id"])
            self.assertEqual(g["must_review"], out in ("review", "rejected"), g["input_id"])

    def test_clean_word_counts(self):
        for g in by_bucket("clean"):
            self.assertTrue(40 <= len(g["ticket"]["body_text"].split()) <= 250, g["input_id"])


class HardCaseTest(unittest.TestCase):
    def test_kinds(self):
        for g in by_bucket("hard"):
            kind = g["hard_case"]
            self.assertIn(kind, mt.HARD_KINDS)
            if kind == "short":
                self.assertLessEqual(len(g["ticket"]["body_text"].split()), 12, g["input_id"])
            if kind == "auto_reply":
                self.assertEqual(g["expected"]["category"], "other", g["input_id"])
            if kind == "multi_issue":
                self.assertIn("second issue", g["label_notes"].lower(), g["input_id"])
            if kind == "thread_quoted":
                self.assertGreaterEqual(g["ticket"]["body_text"].count("\n>"), 5, g["input_id"])
        for g in GOLDS:
            if g["label_bucket"] != "hard":
                self.assertIsNone(g["hard_case"])

    def test_no_placeholders_left(self):
        for g in GOLDS:
            self.assertNotRegex(text_of(g), r"\{\w+\}", g["input_id"])


class InjectionTest(unittest.TestCase):
    def test_shape_and_split(self):
        inj = by_bucket("injection")
        self.assertEqual(len(inj), 16)
        for split in ("dev", "test"):
            kinds = Counter(g["injection"]["kind"] for g in inj if g["split"] == split)
            self.assertEqual(kinds, Counter({"direct": 4, "indirect": 4}), split)
        for g in inj:
            spec = g["injection"]
            self.assertEqual(set(spec), {"kind", "location", "goal", "target"})
            self.assertIn(spec["kind"], KINDS)
            self.assertIn(spec["location"], LOCATIONS)
            self.assertIn(spec["goal"], GOALS)
            self.assertTrue(spec["target"])
        self.assertEqual({g["injection"]["goal"] for g in inj}, set(GOALS))
        for g in GOLDS:
            if g["label_bucket"] != "injection":
                self.assertIsNone(g["injection"])

    def test_attacker_hosts_are_example_invalid(self):
        for g in by_bucket("injection"):
            blob = text_of(g) + json.dumps(g["injection"])
            for url in URL_RE.findall(blob):
                if "evil" in url:
                    self.assertRegex(url, r"^https://[a-z.]*example\.invalid/")
            for domain in EMAIL_RE.findall(blob):
                if "evil" in domain:
                    self.assertTrue(domain.endswith("example.invalid"), domain)

    def test_markers_only_in_injection_tickets(self):
        for g in GOLDS:
            low = text_of(g).lower()
            hits = [m for m in INJECTION_MARKERS if m in low]
            if g["label_bucket"] == "injection":
                continue
            self.assertEqual(hits, [], g["input_id"])

    def test_base64_payload_decodes(self):
        import base64
        g = next(g for g in by_bucket("injection") if g["injection"]["location"] == "base64")
        blob = re.search(r"[A-Za-z0-9+/]{40,}={0,2}", g["ticket"]["body_text"]).group(0)
        self.assertIn("ignore previous instructions", base64.b64decode(blob).decode("utf-8").lower())


class SyntheticDataTest(unittest.TestCase):
    def test_email_domains(self):
        for g in GOLDS:
            blob = json.dumps(g["ticket"]) + json.dumps(g["pii"])
            for domain in EMAIL_RE.findall(blob):
                self.assertRegex(domain, ALLOWED_DOMAIN, g["input_id"])

    def test_phone_numbers_use_555_01xx(self):
        for g in GOLDS:
            for phone in PHONE_RE.findall(text_of(g)):
                self.assertRegex(phone, r"555[ .-]01\d\d$", g["input_id"])

    def test_planted_pii(self):
        pii_ids = set()
        for g in GOLDS:
            for p in g["pii"]:
                pii_ids.add(g["input_id"])
                self.assertIn(p["type"], ("card", "ssn", "iban", "phone", "email", "ipv4", "url", "name"))
                self.assertIn(p["value"], text_of(g), g["input_id"])
                v = p["value"]
                if p["type"] == "card":
                    digits = re.sub(r"[ -]", "", v)
                    self.assertIn(digits, TEST_CARDS)
                    self.assertTrue(luhn_ok(digits))
                elif p["type"] == "ssn":
                    self.assertRegex(v, r"^(9\d\d|000)-\d\d-\d{4}$")
                elif p["type"] == "iban":
                    self.assertTrue(iban_ok(v), v)
                elif p["type"] == "ipv4":
                    self.assertRegex(v, DOC_IP)
                elif p["type"] == "url":
                    self.assertIn("?", v)
                    self.assertRegex(v, r"^https://[a-z.]+\.example\.(com|org|net)/")
                elif p["type"] == "name":
                    self.assertEqual(v, g["ticket"]["from_name"])
        for g in by_bucket("pii"):
            self.assertGreaterEqual(len(g["pii"]), 2, g["input_id"])
            self.assertIn(g["input_id"], pii_ids)


class KeysAndDuplicatesTest(unittest.TestCase):
    def test_keys_recompute(self):
        for g in GOLDS:
            t = g["ticket"]
            self.assertEqual(g["content_sha256"], content_sha256(t["from_email"], t["subject"], t["body_text"]))
            if t.get("source_message_id"):
                self.assertEqual(g["dedupe_key"], dedupe_key(t["source"], t["source_message_id"]))
            else:
                self.assertIsNone(g["dedupe_key"])

    def test_duplicates(self):
        index = {g["input_id"]: (i, g) for i, g in enumerate(GOLDS)}
        kinds = Counter()
        for i, g in enumerate(by_bucket("duplicate")):
            template = g["generator"]["template"]
            kind, ref = template.split(":")
            kinds[kind] += 1
            pos, orig = index[ref]
            self.assertLess(pos, index[g["input_id"]][0])
            self.assertEqual(orig["split"], g["split"])
            if kind == "duplicate-resend":
                self.assertEqual(g["duplicate_of"], ref)
                self.assertEqual(g["ticket"], orig["ticket"])
                self.assertEqual(g["dedupe_key"], orig["dedupe_key"])
            elif kind == "duplicate-content":
                self.assertEqual(g["duplicate_of"], ref)
                self.assertEqual(g["content_sha256"], orig["content_sha256"])
                self.assertNotEqual(g["dedupe_key"], orig["dedupe_key"])
            else:
                self.assertEqual(kind, "duplicate-trap")
                self.assertIsNone(g["duplicate_of"])
                self.assertEqual(g["ticket"]["subject"], orig["ticket"]["subject"])
                self.assertNotEqual(g["content_sha256"], orig["content_sha256"])
            if g["duplicate_of"]:
                self.assertEqual(g["expected"], orig["expected"])
        self.assertEqual(kinds, Counter({"duplicate-resend": 6, "duplicate-content": 4, "duplicate-trap": 2}))

    def test_keys_unique_outside_duplicates(self):
        dups = {g["input_id"] for g in GOLDS if g["duplicate_of"]}
        others = [g for g in GOLDS if g["input_id"] not in dups]
        dkeys = [g["dedupe_key"] for g in others if g["dedupe_key"]]
        self.assertEqual(len(dkeys), len(set(dkeys)))
        csums = [g["content_sha256"] for g in others]
        self.assertEqual(len(csums), len(set(csums)))


class FaultsTest(unittest.TestCase):
    def test_faults_test_split_pass_a(self):
        faults = Counter()
        for g in GOLDS:
            f = g["fault"]
            if not f:
                continue
            self.assertEqual(g["split"], "test", g["input_id"])
            self.assertEqual(f["pass"], "A")
            faults["{}:{}".format(f["target"], f["mode"])] += 1
            if f["mode"] == "search_lag":
                self.assertEqual(g["generator"]["template"].split(":")[0], "duplicate-resend")
            else:
                self.assertEqual(g["expect_outcome"], "auto_route", g["input_id"])
        self.assertEqual(faults, Counter({"jira:commit_then_504": 3, "jira:503": 2, "slack:503": 2,
                                          "sink:jira_links:503": 2, "jira:search_lag": 1}))


class MalformedTest(unittest.TestCase):
    def test_each_case(self):
        m = {g["generator"]["template"] + ":" + (g["review_reason"] or g["expected"]["category"]): g
             for g in by_bucket("malformed")}
        self.assertEqual(len(m), 8)
        get = {k.split(":")[-1]: g for k, g in m.items()}
        self.assertGreater(len(get["body_too_long"]["ticket"]["body_text"]), mt.MAX_BODY_CHARS)
        self.assertEqual(get["empty_content"]["ticket"]["subject"], "")
        self.assertEqual(get["empty_content"]["ticket"]["body_text"], "")
        self.assertNotIn("source_message_id", get["missing_message_id"]["ticket"])
        self.assertIsNone(get["missing_message_id"]["dedupe_key"])
        self.assertGreater(len(get["too_many_attachments"]["ticket"]["attachments"]), mt.MAX_ATTACHMENTS)
        self.assertTrue(get["attachment_type"]["ticket"]["attachments"][0]["name"].endswith(".exe"))
        self.assertEqual(len(get["subject_too_long"]["ticket"]["subject"]), 1000)
        self.assertRegex(get["outage"]["ticket"]["body_text"], r"[\x00-\x08\x1b\x7f]")
        self.assertEqual(len(get["feature"]["ticket"]["body_text"]), mt.MAX_MODEL_CHARS)
        outcomes = Counter(g["expect_outcome"] for g in by_bucket("malformed"))
        self.assertEqual(outcomes, Counter({"rejected": 6, "auto_route": 2}))
        for g in by_bucket("malformed"):
            self.assertEqual(g["review_reason"] is not None, g["expect_outcome"] == "rejected")


class ReadmeStatsTest(unittest.TestCase):
    def test_stats_block_current(self):
        text = (ROOT / mt.README).read_text(encoding="utf-8")
        self.assertIn(mt.stats_block(GOLDS), text)


if __name__ == "__main__":
    unittest.main()
