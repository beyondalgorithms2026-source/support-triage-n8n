// Injection scan and model text cap on redacted text (ARCHITECTURE C-6, C-7). H4 Injection Scan + Cap.
// JS twin of src/common/inject.py: same patterns, same scan text, same model text. Plain ES2019, no require,
// so the file pastes into an n8n Code node. tests/test_inject.py runs it under node on the shared vectors.
// Entry point: scanAndCap(redacted, attachmentNames, maxModelChars) -> {model_text, injection_signals, truncated}.

var MAX_MODEL_CHARS = 6000;

var INJECT_PHRASES = [
  ['instruction_override',
    '\\b(?:ignore|disregard|forget|override|bypass)(?: (?:all|any|of|the|your|my|these|those|previous|prior|above' +
    '|earlier|preceding|existing|original|system|other))* (?:instructions?|rules|prompts?|directions|guidelines' +
    '|directives)\\b'],
  ['role_override',
    '\\byou are now (?:an? |the |in )?(?:[a-z]+ ){0,2}(?:assistant|ai|admin|administrator|system|bot|model|agent' +
    '|mode)\\b|\\b(?:act|behave) as (?:an? |the )?(?:admin|administrator|system|developer|root|unrestricted' +
    '|jailbroken)\\b|\\bdeveloper mode\\b|\\bjailbreak|\\bdo anything now\\b'],
  ['prompt_extraction',
    '\\b(?:reveal|show|print|repeat|output|display|tell me|give me|share|leak|dump)(?: me| us)? (?:(?:your|the|its) )?' +
    '(?:(?:full|hidden|initial|original|internal|secret) )?(?:system prompt|system message|developer message' +
    '|instructions you (?:use|follow|were given))\\b'],
  ['data_exfil',
    '\\b(?:repeat|include|copy|paste|print|output|reveal|leak|echo|expose)(?: (?:the|this|my|our|their|all|full' +
    '|every))?(?: (?:customer\'s|user\'s|client\'s|customer|user|client))? (?:full )?(?:card numbers?' +
    '|credit card(?: numbers?)?|card details|ssns?|social security numbers?|ibans?|passwords?|api keys?' +
    '|access tokens?|credentials|secrets?)\\b'],
  ['ai_address',
    '\\b(?:note|message|instructions?) (?:to|for) (?:the |any |all )?(?:ai|llm|language model|model|assistant|bot' +
    '|classifier)s?\\b|\\b(?:ai|llm)(?: (?:assistant|system|model|agent|classifier)s?)? ?:|\\bassistant ?:'],
  ['routing_override',
    '\\bpre-?approved\\b|\\bno review (?:is )?needed\\b|\\b(?:skip|bypass) (?:the )?(?:human )?review\\b' +
    '|\\broute(?: this| it)?(?: ticket| request| message)? automatically\\b' +
    '|\\bclassify (?:this|it)(?: ticket| request| message)? as\\b'],
  ['field_override', '\\bpriority ?: ?(?:highest|critical|p1)\\b|\\bjira assignee\\b'],
  ['slack_mention',
    '<!(?:channel|here|everyone)\\b|<!subteam\\^|<@[uw][a-z0-9]+>|(?<![a-z0-9._%+-])@(?:here|channel|everyone)\\b'],
  ['slack_link', '<https?://[^ |>]+\\|[^>]*>'],
  ['html_comment', '<!--'],
  ['delimiter_break', '</? ?ticket ?>']
];
var INJECT_FAKE_ROLE = /^(?:\[ ?)?(?:system|assistant|developer)(?: [a-z]+)? ?[:\]]/;
var INJECT_QUOTE_MARKS = /^[ \t]*(?:>[ \t]*)+/;
var INJECT_BASE64 = /[A-Za-z0-9+/]{24,}={0,2}/g;
var BASE64_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
var INJECT_QUOTE_LINE = /^[ \t]*>/;
var INJECT_ON_WROTE = /^[ \t]*On [^\n]{1,200} wrote:[ \t]*$/;
var INJECT_TICKET_TAG = /<(\/? ?ticket)/gi;
var INJECT_EDGE_SPACE = /^[ \t\r\n]+|[ \t\r\n]+$/g;
// Same class as src/common/norm.py WHITESPACE.
var INJECT_WHITESPACE = /[\t\n\x0b\x0c\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+/g;

function injectLines(text) {
  return text.split('\r\n').join('\n').split('\r').join('\n').split('\n');
}

function trimSpaces(text) {
  return text.replace(/^ +| +$/g, '');
}

function scanLines(text) {
  text = text.normalize('NFKC').toLowerCase().split('_').join(' ');
  return injectLines(text).map(function (line) {
    var m = INJECT_QUOTE_MARKS.exec(line);
    return m ? line.slice(m[0].length) : line;
  });
}

function flatText(lines) {
  return trimSpaces(lines.join(' ').replace(INJECT_WHITESPACE, ' '));
}

function injectHits(text) {
  var lines = scanLines(text);
  var flat = flatText(lines);
  var found = [];
  INJECT_PHRASES.forEach(function (p) { if (new RegExp(p[1]).test(flat)) found.push(p[0]); });
  if (lines.some(function (line) { return INJECT_FAKE_ROLE.test(trimSpaces(line.replace(INJECT_WHITESPACE, ' '))); })) {
    found.push('fake_role');
  }
  return found;
}

function b64Text(token) {
  var data = token.replace(/=+$/, '');
  if (data.length % 4 === 1) return null;
  var bits = 0;
  var nbits = 0;
  var out = [];
  for (var i = 0; i < data.length; i++) {
    bits = (bits << 6) | BASE64_ALPHABET.indexOf(data[i]);
    nbits += 6;
    if (nbits >= 8) {
      nbits -= 8;
      out.push((bits >> nbits) & 0xFF);
      bits &= (1 << nbits) - 1;
    }
  }
  if (!out.length) return null;
  for (var k = 0; k < out.length; k++) {
    var b = out[k];
    if (!((b >= 32 && b <= 126) || b === 9 || b === 10 || b === 13)) return null;
  }
  return out.map(function (c) { return String.fromCharCode(c); }).join('');
}

function injectScan(subject, body, attachmentNames) {
  var parts = [subject || '', body || ''];
  (attachmentNames || []).forEach(function (n) { if (n) parts.push(String(n)); });
  var text = parts.join('\n');
  var found = {};
  injectHits(text).forEach(function (s) { found[s] = true; });
  (text.match(INJECT_BASE64) || []).forEach(function (token) {
    var decoded = b64Text(token);
    if (decoded !== null && injectHits(decoded).length) found.encoded_instruction = true;
  });
  return Object.keys(found).sort();
}

function stripQuotes(body) {
  var keep = injectLines(body || '').filter(function (line) {
    return !INJECT_QUOTE_LINE.test(line) && !INJECT_ON_WROTE.test(line);
  });
  return keep.join('\n').replace(INJECT_EDGE_SPACE, '');
}

function buildModelText(subject, body, maxModelChars) {
  if (maxModelChars === undefined || maxModelChars === null) maxModelChars = MAX_MODEL_CHARS;
  // Cap by code points, as Python len() does.
  var chars = Array.from(stripQuotes(body).replace(INJECT_TICKET_TAG, '($1'));
  var truncated = chars.length > maxModelChars ? 1 : 0;
  var capped = chars.slice(0, maxModelChars).join('');
  var subj = (subject || '').replace(INJECT_TICKET_TAG, '($1');
  return { text: 'Subject: ' + subj + '\n\n' + capped, truncated: truncated };
}

function scanAndCap(redacted, attachmentNames, maxModelChars) {
  var subject = redacted.redacted_subject || '';
  var body = redacted.redacted_body || '';
  var built = buildModelText(subject, body, maxModelChars);
  return {
    model_text: built.text,
    injection_signals: injectScan(subject, body, attachmentNames),
    truncated: built.truncated
  };
}
