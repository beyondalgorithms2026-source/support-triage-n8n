"""PII redaction before the model and before any write (ARCHITECTURE C-5, ADR-004).

Reference implementation. The JS twin `src/js/redact.js` (H3 Redact) must give the same output for every vector in
tests/vectors/redact_vectors.json and for every gold ticket (tests/test_redact.py runs it under node).

Order matters: URLs with a query string go first (they can hold emails and IPs), then emails, IBANs, cards, SSNs,
IPv4, phones, and the sender display name last. Each distinct value gets one typed numbered placeholder
(`[EMAIL_1]`, `[EMAIL_2]` …), shared between subject and body. Counts are occurrences per type; values go nowhere.

Every pattern is written so the same string works in Python `re` (with re.ASCII) and in a JS RegExp: ASCII classes
only, no \\s, no `.`, no ^/$ anchors, fixed-width lookbehind only.

    python3 -m src.common.redact --audit evals/gold     # 0 surviving planted PII values, else exit 1
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PII_TYPES = ("email", "phone", "card", "iban", "ssn", "ipv4", "url", "name")

URL_Q = r"[Hh][Tt][Tt][Pp][Ss]?://[^ \t\r\n<>\"'|()\[\]{}]+\?[^ \t\r\n<>\"'|()\[\]{}]+"
EMAIL = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
IBAN = r"(?<![A-Za-z0-9])[A-Z]{2}[0-9]{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?(?![A-Za-z0-9])"
CARD = r"(?<![0-9])[0-9](?:[ -]?[0-9]){12,18}(?![0-9])"
SSN = r"(?<![0-9])[0-9]{3}-[0-9]{2}-[0-9]{4}(?![0-9])"
_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])"
IPV4 = r"(?<![0-9.])(?:" + _OCTET + r"\.){3}" + _OCTET + r"(?![0-9]|\.[0-9])"
# NANP with optional +1 / (area code), or any + country code followed by 2-5 digit groups.
PHONE = (r"(?<![A-Za-z0-9+])(?:(?:\+1[ .-]?)?(?:\([0-9]{3}\)[ .-]?|[0-9]{3}[ .-])[0-9]{3}[ .-][0-9]{4}"
         r"|\+[0-9]{1,3}(?:[ .-]?(?:\([0-9]{1,4}\)|[0-9]{1,4})){2,5})(?![A-Za-z0-9])")

# Apply order. Each rule is (pattern, check); `check` gets the matched text, and False leaves it in place.
_ORDER = ("url", "email", "iban", "card", "ssn", "ipv4", "phone")


def luhn_ok(text):
    digits = [int(c) for c in text if "0" <= c <= "9"]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def iban_ok(text):
    code = text.replace(" ", "")
    if not 15 <= len(code) <= 34:
        return False
    rem = 0
    for c in code[4:] + code[:4]:
        value = str(int(c)) if "0" <= c <= "9" else str(ord(c) - 55)
        for d in value:
            rem = (rem * 10 + int(d)) % 97
    return rem == 1


def phone_ok(text):
    return 7 <= sum(1 for c in text if "0" <= c <= "9") <= 15


_RULES = {
    "url": (re.compile(URL_Q, re.ASCII), None),
    "email": (re.compile(EMAIL, re.ASCII), None),
    "iban": (re.compile(IBAN, re.ASCII), iban_ok),
    "card": (re.compile(CARD, re.ASCII), luhn_ok),
    "ssn": (re.compile(SSN, re.ASCII), None),
    "ipv4": (re.compile(IPV4, re.ASCII), None),
    "phone": (re.compile(PHONE, re.ASCII), phone_ok),
}


def new_state():
    """Placeholder numbering shared by every field of one ticket."""
    return {"counts": {t: 0 for t in PII_TYPES}, "seen": {t: {} for t in PII_TYPES}}


def _placeholder(state, kind, value):
    seen = state["seen"][kind]
    if value not in seen:
        seen[value] = len(seen) + 1
    state["counts"][kind] += 1
    return "[{}_{}]".format(kind.upper(), seen[value])


def _is_word(ch):
    return ("A" <= ch <= "Z") or ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch == "_" or ord(ch) >= 128


def name_parts(display_name):
    """Full display name first, then each part of 2+ characters, longest first. Quotes and spaces trimmed."""
    if not display_name:
        return []
    full = " ".join(p for p in str(display_name).replace('"', " ").split(" ") if p)
    if not full:
        return []
    parts = [full]
    for part in sorted(set(full.split(" ")), key=lambda p: (-len(p), p)):
        if len(part) >= 2 and part not in parts:
            parts.append(part)
    return parts


def _redact_name(text, display_name, state):
    for part in name_parts(display_name):
        out, i = [], 0
        while True:
            j = text.find(part, i)
            if j < 0:
                break
            end = j + len(part)
            if (j > 0 and _is_word(text[j - 1])) or (end < len(text) and _is_word(text[end])):
                out.append(text[i:j + 1])
                i = j + 1
                continue
            out.append(text[i:j])
            # Every form of the sender's name is one person: one placeholder.
            out.append(_placeholder(state, "name", "sender"))
            i = end
        out.append(text[i:])
        text = "".join(out)
    return text


def redact_text(text, display_name=None, state=None):
    """Redact one string. Pass the same `state` for every field of one ticket."""
    if state is None:
        state = new_state()
    if text is None:
        return ""
    text = str(text)
    for kind in _ORDER:
        pattern, check = _RULES[kind]

        def repl(m, kind=kind, check=check):
            if check is not None and not check(m.group(0)):
                return m.group(0)
            return _placeholder(state, kind, m.group(0))
        text = pattern.sub(repl, text)
    return _redact_name(text, display_name, state)


def redact_ticket(ticket):
    """ticket (gold `ticket` shape) -> {redacted_subject, redacted_body, pii_counts}. Subject first, then body."""
    state = new_state()
    name = ticket.get("from_name")
    subject = redact_text(ticket.get("subject"), name, state)
    body = redact_text(ticket.get("body_text"), name, state)
    return {"redacted_subject": subject, "redacted_body": body, "pii_counts": dict(state["counts"])}


# ---------------------------------------------------------------- audit
def audit(gold_dir):
    """(problems, totals) over every gold file: planted values that survive redaction, and counts by type."""
    from src.score.score import leak_targets     # the same leak rule the scorer uses (Q-26 (3))
    problems, totals, planted = [], {t: 0 for t in PII_TYPES}, 0
    for path in sorted(Path(gold_dir).glob("t4-*.json")):
        gold = json.loads(path.read_text(encoding="utf-8"))
        out = redact_ticket(gold.get("ticket") or {})
        for kind, n in out["pii_counts"].items():
            totals[kind] += n
        pii = gold.get("pii") or []
        planted += len(pii)
        pairs = [("subject", out["redacted_subject"]), ("body", out["redacted_body"])]
        for item in pii:
            for target in leak_targets([item], pairs):
                problems.append("{}: planted {} survives in {}".format(gold.get("input_id"), item.get("type"), target))
    return problems, totals, planted


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--audit", metavar="GOLD_DIR", required=True, help="gold directory, e.g. evals/gold")
    args = parser.parse_args(argv)
    problems, totals, planted = audit(args.audit)
    print("planted PII values: {}".format(planted))
    print("redactions by type: " + ", ".join("{}={}".format(k, v) for k, v in totals.items()))
    for line in problems:
        print("LEAK " + line)
    print("surviving planted PII values: {}".format(len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
