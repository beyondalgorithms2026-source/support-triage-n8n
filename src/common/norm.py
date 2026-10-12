"""Text normalisation and ticket keys (ARCHITECTURE C-4, §8; ADR-006).

The JS twin (H1 Intake Guard, G7) must give the same output for every vector in tests/test_norm.py.
WHITESPACE is written so the same pattern string works in Python `re` and in a JS RegExp.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

# Explicit class instead of \s: Python and JS disagree on \x1c-\x1f, \x85 and ﻿.
WHITESPACE = (r"[\t\n\x0b\x0c\r\x1c-\x20\x85\xa0  -     　﻿]+")
_WHITESPACE_RE = re.compile(WHITESPACE)
DEDUPE_KEY_HEX = 20


def text_norm(value):
    """NFKC, casefold, collapse every whitespace run to one space, strip. None -> ""."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return _WHITESPACE_RE.sub(" ", text).strip(" ")


def email_norm(value):
    """text_norm with every space removed. No provider-specific rules (dots, plus tags are kept)."""
    return text_norm(value).replace(" ", "")


def _sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dedupe_key(source, message_id):
    """First 20 hex of sha256(source + "|" + message_id) over the raw values.

    Empty or missing values raise ValueError: intake rejects them (C-3), and one shared key would merge
    unrelated tickets.
    """
    if not source or not message_id:
        raise ValueError("dedupe_key needs a non-empty source and message_id")
    return _sha256_hex("{}|{}".format(source, message_id))[:DEDUPE_KEY_HEX]


def content_sha256(from_email, subject, body):
    """sha256 hex of email_norm(from_email) | text_norm(subject) | text_norm(body)."""
    return _sha256_hex("{}|{}|{}".format(email_norm(from_email), text_norm(subject), text_norm(body)))
