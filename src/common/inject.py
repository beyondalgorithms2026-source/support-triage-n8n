"""Injection scan and model text cap on redacted text (ARCHITECTURE C-6, C-7). H4 Injection Scan + Cap.

Reference implementation. The JS twin `src/js/inject.js` must give the same output for every vector in
tests/vectors/inject_vectors.json and for every gold ticket (tests/test_inject.py runs it under node).

A hit does not block: it adds a name to `injection_signals`, and Decide sends the ticket to review (C-14 R5).
The scan reads the whole redacted subject, body and attachment names, including quoted history. The model text is
built after the scan: quoted lines (`>`) and `On … wrote:` lines are dropped, `<ticket>` tags are defused (C-9),
and the body is capped at `max_model_chars` code points (`truncated` = 1 when the cap cut it).

Scan text = NFKC, lower case, `_` → space, leading quote marks removed per line, whitespace collapsed.
Patterns are ASCII-only and compiled with re.ASCII, so the same string works as a JS RegExp.
Patterns were written from the C-6 families and the dev injection tickets only (I-9; OPEN_QUESTIONS Q-28).

    python3 -m src.common.inject --audit evals/gold --split dev
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

from src.common.norm import WHITESPACE

MAX_MODEL_CHARS = 6000      # `0. Config` default (ARCHITECTURE §5.2)

# (signal, pattern) over the flat scan text.
PHRASES = (
    ("instruction_override",
     r"\b(?:ignore|disregard|forget|override|bypass)(?: (?:all|any|of|the|your|my|these|those|previous|prior|above"
     r"|earlier|preceding|existing|original|system|other))* (?:instructions?|rules|prompts?|directions|guidelines"
     r"|directives)\b"),
    ("role_override",
     r"\byou are now (?:an? |the |in )?(?:[a-z]+ ){0,2}(?:assistant|ai|admin|administrator|system|bot|model|agent"
     r"|mode)\b|\b(?:act|behave) as (?:an? |the )?(?:admin|administrator|system|developer|root|unrestricted"
     r"|jailbroken)\b|\bdeveloper mode\b|\bjailbreak|\bdo anything now\b"),
    ("prompt_extraction",
     r"\b(?:reveal|show|print|repeat|output|display|tell me|give me|share|leak|dump)(?: me| us)? (?:(?:your|the|its) )?"
     r"(?:(?:full|hidden|initial|original|internal|secret) )?(?:system prompt|system message|developer message"
     r"|instructions you (?:use|follow|were given))\b"),
    ("data_exfil",
     r"\b(?:repeat|include|copy|paste|print|output|reveal|leak|echo|expose)(?: (?:the|this|my|our|their|all|full"
     r"|every))?(?: (?:customer's|user's|client's|customer|user|client))? (?:full )?(?:card numbers?"
     r"|credit card(?: numbers?)?|card details|ssns?|social security numbers?|ibans?|passwords?|api keys?"
     r"|access tokens?|credentials|secrets?)\b"),
    ("ai_address",
     r"\b(?:note|message|instructions?) (?:to|for) (?:the |any |all )?(?:ai|llm|language model|model|assistant|bot"
     r"|classifier)s?\b|\b(?:ai|llm)(?: (?:assistant|system|model|agent|classifier)s?)? ?:|\bassistant ?:"),
    ("routing_override",
     r"\bpre-?approved\b|\bno review (?:is )?needed\b|\b(?:skip|bypass) (?:the )?(?:human )?review\b"
     r"|\broute(?: this| it)?(?: ticket| request| message)? automatically\b"
     r"|\bclassify (?:this|it)(?: ticket| request| message)? as\b"),
    ("field_override", r"\bpriority ?: ?(?:highest|critical|p1)\b|\bjira assignee\b"),
    ("slack_mention",
     r"<!(?:channel|here|everyone)\b|<!subteam\^|<@[uw][a-z0-9]+>|(?<![a-z0-9._%+-])@(?:here|channel|everyone)\b"),
    ("slack_link", r"<https?://[^ |>]+\|[^>]*>"),
    ("html_comment", r"<!--"),
    ("delimiter_break", r"</? ?ticket ?>"),
)
# A line that pretends to be a system or assistant turn (checked per line, after quote marks are removed).
FAKE_ROLE = r"(?:\[ ?)?(?:system|assistant|developer)(?: [a-z]+)? ?[:\]]"
QUOTE_MARKS = r"[ \t]*(?:>[ \t]*)+"
BASE64_TOKEN = r"[A-Za-z0-9+/]{24,}={0,2}"
BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
QUOTE_LINE = r"[ \t]*>"
ON_WROTE = r"[ \t]*On [^\n]{1,200} wrote:[ \t]*"
TICKET_TAG = r"<(/? ?ticket)"
EDGE_SPACE = r"^[ \t\r\n]+|[ \t\r\n]+$"

_PHRASES = tuple((name, re.compile(p, re.ASCII)) for name, p in PHRASES)
_FAKE_ROLE = re.compile(FAKE_ROLE, re.ASCII)
_QUOTE_MARKS = re.compile(QUOTE_MARKS, re.ASCII)
_BASE64 = re.compile(BASE64_TOKEN, re.ASCII)
_QUOTE_LINE = re.compile(QUOTE_LINE, re.ASCII)
_ON_WROTE = re.compile(ON_WROTE, re.ASCII)
_TICKET_TAG = re.compile(TICKET_TAG, re.ASCII | re.IGNORECASE)
_EDGE_SPACE = re.compile(EDGE_SPACE, re.ASCII)
_WHITESPACE = re.compile(WHITESPACE)


def _lines(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def scan_lines(text):
    """Scan form, one entry per line: NFKC, lower case, `_` → space, leading quote marks removed."""
    text = unicodedata.normalize("NFKC", text).lower().replace("_", " ")
    out = []
    for line in _lines(text):
        m = _QUOTE_MARKS.match(line)
        out.append(line[m.end():] if m else line)
    return out


def flat_text(lines):
    return _WHITESPACE.sub(" ", " ".join(lines)).strip(" ")


def _hits(text):
    lines = scan_lines(text)
    flat = flat_text(lines)
    found = [name for name, pattern in _PHRASES if pattern.search(flat)]
    if any(_FAKE_ROLE.match(_WHITESPACE.sub(" ", line).strip(" ")) for line in lines):
        found.append("fake_role")
    return found


def b64_text(token):
    """Decoded text of a base64 token, or None when it is not printable ASCII."""
    data = token.rstrip("=")
    if len(data) % 4 == 1:
        return None
    bits, nbits, out = 0, 0, []
    for ch in data:
        bits = (bits << 6) | BASE64_ALPHABET.index(ch)
        nbits += 6
        if nbits >= 8:
            nbits -= 8
            out.append((bits >> nbits) & 0xFF)
            bits &= (1 << nbits) - 1
    if not out or any(not (32 <= b <= 126 or b in (9, 10, 13)) for b in out):
        return None
    return "".join(chr(b) for b in out)


def scan(subject, body, attachment_names=()):
    """Sorted unique injection signal names for one redacted ticket. [] = no hit."""
    text = "\n".join([subject or "", body or ""] + [str(n) for n in attachment_names or () if n])
    found = set(_hits(text))
    for token in _BASE64.findall(text):
        decoded = b64_text(token)
        if decoded is not None and _hits(decoded):
            found.add("encoded_instruction")
    return sorted(found)


def strip_quotes(body):
    """Drop `>` lines and `On … wrote:` lines (C-7), then trim blank space at both ends."""
    keep = [line for line in _lines(body or "") if not _QUOTE_LINE.match(line) and not _ON_WROTE.fullmatch(line)]
    return _EDGE_SPACE.sub("", "\n".join(keep))


def model_text(subject, body, max_model_chars=MAX_MODEL_CHARS):
    """(model_text, truncated). The body is capped at max_model_chars code points; the subject (≤ 300, C-2) is not."""
    body = _TICKET_TAG.sub(r"(\1", strip_quotes(body))
    truncated = 1 if len(body) > max_model_chars else 0
    body = body[:max_model_chars]
    subject = _TICKET_TAG.sub(r"(\1", subject or "")
    return "Subject: {}\n\n{}".format(subject, body), truncated


def scan_and_cap(redacted, attachment_names=(), max_model_chars=MAX_MODEL_CHARS):
    """H4: {redacted_subject, redacted_body} -> {model_text, injection_signals, truncated}."""
    subject, body = redacted.get("redacted_subject") or "", redacted.get("redacted_body") or ""
    text, truncated = model_text(subject, body, max_model_chars)
    return {"model_text": text, "injection_signals": scan(subject, body, attachment_names), "truncated": truncated}


def attachment_names(ticket):
    return [a.get("name") for a in ticket.get("attachments") or [] if isinstance(a, dict) and a.get("name")]


# ---------------------------------------------------------------- audit
def audit(gold_dir, split):
    """{bucket: [(input_id, signals), …]} after redaction, for the gold files in `split` ("all" = both)."""
    from src.common.redact import redact_ticket
    by_bucket = {}
    for path in sorted(Path(gold_dir).glob("t4-*.json")):
        gold = json.loads(path.read_text(encoding="utf-8"))
        if split != "all" and gold.get("split") != split:
            continue
        ticket = gold.get("ticket") or {}
        out = scan_and_cap(redact_ticket(ticket), attachment_names(ticket))
        by_bucket.setdefault(gold.get("label_bucket"), []).append((gold.get("input_id"), out["injection_signals"]))
    return by_bucket


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--audit", metavar="GOLD_DIR", required=True, help="gold directory, e.g. evals/gold")
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--min-injection", type=int, default=6, help="injection tickets that must be flagged (GOALS G4)")
    parser.add_argument("--max-clean", type=int, default=2, help="clean + hard tickets allowed to be flagged (GOALS G4)")
    args = parser.parse_args(argv)
    by_bucket = audit(args.audit, args.split)
    for bucket in sorted(by_bucket):
        rows = by_bucket[bucket]
        flagged = [(i, s) for i, s in rows if s]
        print("{:<10} flagged {:>3} of {:>3}".format(bucket, len(flagged), len(rows)))
        for input_id, signals in flagged:
            print("    {} {}".format(input_id, ",".join(signals)))
        for input_id, signals in rows:
            if bucket == "injection" and not signals:
                print("    {} MISSED".format(input_id))
    inj = sum(1 for _, s in by_bucket.get("injection", []) if s)
    clean = sum(1 for b in ("clean", "hard") for _, s in by_bucket.get(b, []) if s)
    ok = inj >= args.min_injection and clean <= args.max_clean
    print("injection flagged {} (need >= {}); clean/hard flagged {} (allow <= {}): {}".format(
        inj, args.min_injection, clean, args.max_clean, "PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
