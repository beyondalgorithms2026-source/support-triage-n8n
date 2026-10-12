// Parse the classifier reply and compute per-class confidence (ARCHITECTURE C-10, C-13; ADR-005). H8 Parse +
// Confidence. Confidence of a field = probability of the chosen value's first token, renormalised over the
// first-token alternatives that start exactly one enum value of that field. No logprobs -> confidence 0 and
// conf_source "none" (fail closed: Decide sends the ticket to review). Plain ES2019, no require, so the file
// pastes into an n8n Code node. tests/test_workflow.py runs it under node on STUB completions.
// Entry point: classifyCompletion(completion) -> {category, priority, urgency, conf_*, conf_source, reasons,
// first_tokens}.

var CLASS_ENUMS = {
  category: ['billing', 'access', 'bug', 'outage', 'howto', 'feature', 'privacy', 'other'],
  priority: ['critical', 'high', 'normal', 'low'],
  urgency: ['high', 'medium', 'low']
};
var CLASS_FIELDS = ['category', 'priority', 'urgency'];
var PRIORITY_CODES = { critical: 'P1', high: 'P2', normal: 'P3', low: 'P4' };

// Offset of the first character of the string value of `field` in the JSON text, or -1.
function valueStart(content, field) {
  var m = new RegExp('"' + field + '"[ \\t\\r\\n]*:[ \\t\\r\\n]*"').exec(content);
  return m ? m.index + m[0].length : -1;
}

// The token that holds character `offset`, and the part of that token before it.
function tokenAt(tokens, offset) {
  var pos = 0;
  for (var i = 0; i < tokens.length; i++) {
    var text = String(tokens[i].token || '');
    if (offset < pos + text.length) return { index: i, prefix: text.slice(0, offset - pos) };
    pos += text.length;
  }
  return null;
}

// The one enum value that starts with `rest`, else null (empty or ambiguous token text).
function enumFor(rest, values) {
  if (!rest) return null;
  var hits = values.filter(function (v) { return v.indexOf(rest) === 0; });
  return hits.length === 1 ? hits[0] : null;
}

function fieldConfidence(tokens, content, field, chosen) {
  var start = valueStart(content, field);
  var at = start < 0 ? null : tokenAt(tokens, start);
  if (!at) return null;
  var tok = tokens[at.index];
  var alts = (tok.top_logprobs || []).slice();
  if (!alts.some(function (a) { return a.token === tok.token; })) alts.push({ token: tok.token, logprob: tok.logprob });
  var mass = {};
  var seen = [];
  alts.forEach(function (alt) {
    var text = String(alt.token || '');
    var value = text.indexOf(at.prefix) === 0 ? enumFor(text.slice(at.prefix.length), CLASS_ENUMS[field]) : null;
    var p = Math.exp(Number(alt.logprob));
    seen.push([text, value, Number(alt.logprob)]);
    if (value !== null && isFinite(p)) mass[value] = (mass[value] || 0) + p;
  });
  var total = 0;
  Object.keys(mass).forEach(function (v) { total += mass[v]; });
  if (!mass[chosen] || total <= 0) return null;
  return { confidence: Math.round(mass[chosen] / total * 1000000) / 1000000,
           map: { prefix: at.prefix, chosen: tok.token, alternatives: seen } };
}

function classifyCompletion(completion) {
  var choice = (completion && completion.choices && completion.choices[0]) || {};
  var content = String((choice.message && choice.message.content) || '');
  var out = { category: '', priority: '', urgency: '', conf_category: 0, conf_priority: 0, conf_urgency: 0,
              conf_source: 'none', reasons: [], first_tokens: {} };
  var parsed = null;
  try { parsed = JSON.parse(content); } catch (e) { parsed = null; }
  var ok = parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed) &&
    Object.keys(parsed).length === CLASS_FIELDS.length &&
    CLASS_FIELDS.every(function (f) { return CLASS_ENUMS[f].indexOf(parsed[f]) >= 0; });
  if (!ok) {
    out.reasons.push('schema_miss');
    return out;
  }
  out.category = parsed.category;
  out.priority = PRIORITY_CODES[parsed.priority];
  out.urgency = parsed.urgency;
  var tokens = choice.logprobs && choice.logprobs.content;
  var joined = Array.isArray(tokens) ? tokens.map(function (t) { return String(t.token || ''); }).join('') : '';
  if (!joined || joined !== content) {
    out.reasons.push('confidence:no_logprobs');
    return out;
  }
  var found = {};
  CLASS_FIELDS.forEach(function (field) {
    var r = fieldConfidence(tokens, content, field, parsed[field]);
    if (r !== null) found[field] = r;
  });
  if (Object.keys(found).length !== CLASS_FIELDS.length) {
    out.reasons.push('confidence:no_logprobs');
    return out;
  }
  CLASS_FIELDS.forEach(function (field) {
    out['conf_' + field] = found[field].confidence;
    out.first_tokens[field] = found[field].map;
  });
  out.conf_source = 'logprobs';
  return out;
}
