"""Vectors for src/common/norm.py. They are the contract for the JS twin in H1 (G7).

Hash vectors pin the exact preimage string; the digest is computed here with hashlib, so the JS twin test can
hash the same preimage with node crypto and compare.
"""
import hashlib
import re
import unittest

from src.common.norm import WHITESPACE, content_sha256, dedupe_key, email_norm, text_norm

TEXT_VECTORS = (
    ("  Hello\tWorld \n", "hello world"),
    ("Line1\r\n\r\nLine2", "line1 line2"),
    ("ＡＢＣ", "abc"),            # fullwidth letters
    ("ﬁle", "file"),                      # ligature
    ("Café", "café"),               # combining accent composes
    ("Café", "café"),
    ("a b", "a b"),                       # no-break space
    ("a  b", "a b"),                 # em spaces
    ("a﻿b", "a b"),                       # BOM counts as whitespace
    ("a\x85b", "a b"),                         # next line
    ("\x1ctab\x1d", "tab"),                    # separators
    ("x​y", "x​y"),                  # zero-width space is kept
    ("Ⅻ", "xii"),                         # roman numeral twelve
    ("Å", "å"),                      # angstrom sign
    ("", ""),
    (None, ""),
)

EMAIL_VECTORS = (
    (" Dana.Whitfield@Example.COM ", "dana.whitfield@example.com"),
    ("dana+t4@Example.com", "dana+t4@example.com"),
    ("ｄana@example.com", "dana@example.com"),
    ("dana @ example.com", "dana@example.com"),
    (None, ""),
)

DEDUPE_VECTORS = (
    (("email", "<t4-001@mail.example.com>"), "email|<t4-001@mail.example.com>"),
    (("webhook", "abc-123"), "webhook|abc-123"),
    (("Email", " X "), "Email| X "),           # raw values: no normalisation
)

CONTENT_VECTORS = (
    (("Dana@Example.com", "  Invoice  wrong ", "Hello\nthere"), "dana@example.com|invoice wrong|hello there"),
    ((None, None, "Body"), "||body"),
    (("a@example.org", "Ｈi", "x  y"), "a@example.org|hi|x y"),
)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TextNormTest(unittest.TestCase):
    def test_vectors(self):
        for raw, want in TEXT_VECTORS:
            with self.subTest(raw=raw):
                self.assertEqual(text_norm(raw), want)

    def test_idempotent(self):
        for raw, _ in TEXT_VECTORS:
            with self.subTest(raw=raw):
                self.assertEqual(text_norm(text_norm(raw)), text_norm(raw))

    def test_whitespace_pattern_is_js_compatible(self):
        # One pattern string for Python and JS: no \s, no (?...) groups, no Python-only escapes.
        self.assertNotIn(r"\s", WHITESPACE)
        self.assertNotIn("(?", WHITESPACE)
        self.assertTrue(re.fullmatch(WHITESPACE, " \t\n"))


class EmailNormTest(unittest.TestCase):
    def test_vectors(self):
        for raw, want in EMAIL_VECTORS:
            with self.subTest(raw=raw):
                self.assertEqual(email_norm(raw), want)


class DedupeKeyTest(unittest.TestCase):
    def test_vectors(self):
        for args, preimage in DEDUPE_VECTORS:
            with self.subTest(args=args):
                key = dedupe_key(*args)
                self.assertEqual(key, sha(preimage)[:20])
                self.assertRegex(key, r"^[0-9a-f]{20}$")

    def test_source_is_part_of_key(self):
        self.assertNotEqual(dedupe_key("email", "m-1"), dedupe_key("webhook", "m-1"))

    def test_empty_values_raise(self):
        for args in (("email", ""), ("", "m-1"), ("email", None), (None, "m-1")):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    dedupe_key(*args)


class ContentShaTest(unittest.TestCase):
    def test_vectors(self):
        for args, preimage in CONTENT_VECTORS:
            with self.subTest(args=args):
                digest = content_sha256(*args)
                self.assertEqual(digest, sha(preimage))
                self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_same_text_different_format_matches(self):
        self.assertEqual(content_sha256("A@Example.com", "Refund", "Please  refund\n invoice 7"),
                         content_sha256(" a@example.com", "REFUND", "please refund invoice 7"))

    def test_different_body_differs(self):
        self.assertNotEqual(content_sha256("a@example.com", "Refund", "invoice 7"),
                            content_sha256("a@example.com", "Refund", "invoice 8"))


if __name__ == "__main__":
    unittest.main()
