// PII redaction before the model and before any write (ARCHITECTURE C-5, ADR-004). H3 Redact.
// JS twin of src/common/redact.py: same patterns, same order, same placeholders. Plain ES2019, no require,
// so the file pastes into an n8n Code node. tests/test_redact.py runs it under node on the shared vectors.
// Entry point: redactTicket(ticket) -> {redacted_subject, redacted_body, pii_counts}.

var PII_TYPES = ['email', 'phone', 'card', 'iban', 'ssn', 'ipv4', 'url', 'name'];

var REDACT_OCTET = '(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])';
var REDACT_PATTERNS = {
  url: '[Hh][Tt][Tt][Pp][Ss]?://[^ \\t\\r\\n<>"\'|()\\[\\]{}]+\\?[^ \\t\\r\\n<>"\'|()\\[\\]{}]+',
  email: '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}',
  iban: '(?<![A-Za-z0-9])[A-Z]{2}[0-9]{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?(?![A-Za-z0-9])',
  card: '(?<![0-9])[0-9](?:[ -]?[0-9]){12,18}(?![0-9])',
  ssn: '(?<![0-9])[0-9]{3}-[0-9]{2}-[0-9]{4}(?![0-9])',
  ipv4: '(?<![0-9.])(?:' + REDACT_OCTET + '\\.){3}' + REDACT_OCTET + '(?![0-9]|\\.[0-9])',
  phone: '(?<![A-Za-z0-9+])(?:(?:\\+1[ .-]?)?(?:\\([0-9]{3}\\)[ .-]?|[0-9]{3}[ .-])[0-9]{3}[ .-][0-9]{4}' +
         '|\\+[0-9]{1,3}(?:[ .-]?(?:\\([0-9]{1,4}\\)|[0-9]{1,4})){2,5})(?![A-Za-z0-9])'
};
var REDACT_ORDER = ['url', 'email', 'iban', 'card', 'ssn', 'ipv4', 'phone'];

function isDigit(c) { return c >= '0' && c <= '9'; }

function luhnOk(text) {
  var digits = [];
  for (var k = 0; k < text.length; k++) { if (isDigit(text[k])) digits.push(+text[k]); }
  if (digits.length < 13 || digits.length > 19) return false;
  var total = 0;
  for (var i = 0; i < digits.length; i++) {
    var d = digits[digits.length - 1 - i];
    if (i % 2) { d *= 2; if (d > 9) d -= 9; }
    total += d;
  }
  return total % 10 === 0;
}

function ibanOk(text) {
  var code = text.split(' ').join('');
  if (code.length < 15 || code.length > 34) return false;
  var moved = code.slice(4) + code.slice(0, 4);
  var rem = 0;
  for (var i = 0; i < moved.length; i++) {
    var c = moved[i];
    var value = isDigit(c) ? c : String(c.charCodeAt(0) - 55);
    for (var j = 0; j < value.length; j++) rem = (rem * 10 + (+value[j])) % 97;
  }
  return rem === 1;
}

function phoneOk(text) {
  var n = 0;
  for (var i = 0; i < text.length; i++) { if (isDigit(text[i])) n++; }
  return n >= 7 && n <= 15;
}

var REDACT_CHECKS = { iban: ibanOk, card: luhnOk, phone: phoneOk };

function newRedactState() {
  var state = { counts: {}, seen: {} };
  for (var i = 0; i < PII_TYPES.length; i++) { state.counts[PII_TYPES[i]] = 0; state.seen[PII_TYPES[i]] = {}; }
  return state;
}

function redactPlaceholder(state, kind, value) {
  var seen = state.seen[kind];
  if (!Object.prototype.hasOwnProperty.call(seen, value)) seen[value] = Object.keys(seen).length + 1;
  state.counts[kind] += 1;
  return '[' + kind.toUpperCase() + '_' + seen[value] + ']';
}

function isWordChar(ch) {
  return /[A-Za-z0-9_]/.test(ch) || ch.charCodeAt(0) >= 128;
}

function namePartsOf(displayName) {
  if (!displayName) return [];
  var full = String(displayName).split('"').join(' ').split(' ').filter(function (p) { return p; }).join(' ');
  if (!full) return [];
  var uniq = [];
  full.split(' ').forEach(function (p) { if (uniq.indexOf(p) < 0) uniq.push(p); });
  uniq.sort(function (a, b) {
    if (a.length !== b.length) return b.length - a.length;
    return a < b ? -1 : (a > b ? 1 : 0);
  });
  var parts = [full];
  uniq.forEach(function (p) { if (p.length >= 2 && parts.indexOf(p) < 0) parts.push(p); });
  return parts;
}

function redactName(text, displayName, state) {
  namePartsOf(displayName).forEach(function (part) {
    var out = [];
    var i = 0;
    for (;;) {
      var j = text.indexOf(part, i);
      if (j < 0) break;
      var end = j + part.length;
      if ((j > 0 && isWordChar(text[j - 1])) || (end < text.length && isWordChar(text[end]))) {
        out.push(text.slice(i, j + 1));
        i = j + 1;
        continue;
      }
      out.push(text.slice(i, j));
      // Every form of the sender's name is one person: one placeholder.
      out.push(redactPlaceholder(state, 'name', 'sender'));
      i = end;
    }
    out.push(text.slice(i));
    text = out.join('');
  });
  return text;
}

function redactText(text, displayName, state) {
  if (!state) state = newRedactState();
  if (text === null || text === undefined) return '';
  text = String(text);
  REDACT_ORDER.forEach(function (kind) {
    var flags = 'g';
    var check = REDACT_CHECKS[kind];
    text = text.replace(new RegExp(REDACT_PATTERNS[kind], flags), function (m) {
      if (check && !check(m)) return m;
      return redactPlaceholder(state, kind, m);
    });
  });
  return redactName(text, displayName, state);
}

function redactTicket(ticket) {
  var state = newRedactState();
  var name = ticket.from_name;
  var subject = redactText(ticket.subject, name, state);
  var body = redactText(ticket.body_text, name, state);
  var counts = {};
  PII_TYPES.forEach(function (t) { counts[t] = state.counts[t]; });
  return { redacted_subject: subject, redacted_body: body, pii_counts: counts };
}
