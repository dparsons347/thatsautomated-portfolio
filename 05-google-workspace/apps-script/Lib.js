/**
 * Pure logic for the Oakline intake. No Google services in this file, so it
 * runs under Node for the tests in ../tests. Everything here is a plain
 * global function because that is how Apps Script shares code between files.
 */

var FREE_MAIL_DOMAINS = [
  'gmail.com', 'googlemail.com', 'yahoo.com', 'ymail.com', 'hotmail.com',
  'outlook.com', 'live.com', 'msn.com', 'aol.com', 'icloud.com', 'me.com',
  'mac.com', 'proton.me', 'protonmail.com', 'gmx.com', 'comcast.net',
  'att.net', 'bellsouth.net', 'charter.net', 'verizon.net'
];

var STATUSES = ['New', 'Needs assignment', 'Needs attention', 'Assigned', 'Waiting on client', 'Done'];
var OPEN_STATUSES = ['New', 'Needs assignment', 'Needs attention', 'Assigned', 'Waiting on client'];

// Order matters: the first rule that matches wins.
var DOCUMENT_RULES = [
  { type: '1099', re: /\b1099(?:[-\s]?(?:nec|misc|int|div|b|r|k|g|sa))?\b/i },
  { type: 'W-2', re: /\bw[-\s_]?2\b/i },
  { type: '1098', re: /\b1098(?:[-\s]?(?:t|e))?\b|mortgage interest/i },
  { type: 'K-1', re: /\bk[-\s_]?1\b/i },
  { type: 'Prior-year return', re: /\b1040\b|prior[-\s_]?year|(?:last|previous)[-\s_]?year'?s?[-\s_]?return|\b(?:19|20)\d\d[-\s_]?(?:tax[-\s_]?)?return\b/i },
  { type: 'Bank statement', re: /bank[-\s_]?statement|\bstatement\b|\bstmt\b/i },
  { type: 'Receipt', re: /receipt|invoice|\brcpt\b/i },
  { type: 'ID', re: /driver'?s?[-\s_]?licen[cs]e|\bpassport\b|photo[-\s_]?id|\bid[-\s_]?card\b/i },
  { type: 'Engagement letter', re: /engagement[-\s_]?letter|signed[-\s_]?engagement/i }
];

/** "Marcus Rivera <Marcus@Example.com>" -> { name: 'Marcus Rivera', email: 'marcus@example.com' } */
function parseAddress(from) {
  var s = String(from || '').trim();
  var m = s.match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/);
  if (m) return { name: m[1].trim(), email: m[2].trim().toLowerCase() };
  return { name: '', email: s.toLowerCase() };
}

/** "a@x.com, B@y.com ;c" -> ['a@x.com', 'b@y.com', 'c'] */
function splitList(value) {
  return String(value || '')
    .split(/[,;\n]/)
    .map(function (x) { return x.trim().toLowerCase(); })
    .filter(function (x) { return x.length > 0; });
}

function emailDomain(email) {
  var at = String(email || '').lastIndexOf('@');
  return at < 0 ? '' : String(email).slice(at + 1).toLowerCase();
}

/**
 * Find the client for a sender. Exact address first, then business domain.
 * A free-mail domain never matches by domain, so one Gmail client does not
 * claim every Gmail sender. Returns the client object or null.
 */
function matchClient(email, clients) {
  var addr = String(email || '').trim().toLowerCase();
  if (!addr) return null;
  for (var i = 0; i < clients.length; i++) {
    if (clients[i].emails.indexOf(addr) >= 0) return clients[i];
  }
  var domain = emailDomain(addr);
  if (!domain || FREE_MAIL_DOMAINS.indexOf(domain) >= 0) return null;
  for (var j = 0; j < clients.length; j++) {
    if (clients[j].domains.indexOf(domain) >= 0) return clients[j];
  }
  return null;
}

function classifyOne_(text) {
  var t = String(text || '').replace(/[_.]/g, ' ');
  for (var i = 0; i < DOCUMENT_RULES.length; i++) {
    if (DOCUMENT_RULES[i].re.test(t)) return DOCUMENT_RULES[i].type;
  }
  return null;
}

/**
 * Document type from the file name; if the name says nothing, from the subject,
 * but only when the subject names exactly one type ("W-2 and 1099" is ambiguous).
 */
function classifyDocument(fileName, subject) {
  var base = String(fileName || '').replace(/\.[a-z0-9]{2,5}$/i, '');
  var fromName = classifyOne_(base);
  if (fromName) return fromName;
  var s = String(subject || '').replace(/[_.]/g, ' ');
  var hits = DOCUMENT_RULES.filter(function (r) { return r.re.test(s); });
  return hits.length === 1 ? hits[0].type : 'Other';
}

/** True for a PDF whose bytes (as a latin-1 string) carry an /Encrypt dictionary. */
function isEncryptedPdf(fileName, contentType, latin1) {
  var isPdf = /pdf/i.test(String(contentType || '')) || /\.pdf$/i.test(String(fileName || ''));
  if (!isPdf) return false;
  return /\/Encrypt[\s\/<\d]/.test(String(latin1 || ''));
}

/** Signature logos and tracking pixels: images under 20 KB are not client documents. */
function shouldSkipAttachment(name, contentType, size) {
  return /^image\//i.test(String(contentType || '')) && Number(size) < 20 * 1024;
}

/** Days between two dates, one decimal. */
function daysBetween(from, to) {
  var ms = new Date(to).getTime() - new Date(from).getTime();
  return Math.round((ms / 86400000) * 10) / 10;
}

function intakeId(date, n) {
  var d = new Date(date);
  var y = d.getFullYear();
  var m = ('0' + (d.getMonth() + 1)).slice(-2);
  var day = ('0' + d.getDate()).slice(-2);
  return 'INT-' + y + m + day + '-' + ('000' + n).slice(-4);
}

/** Status and note for one saved attachment. */
function rowStatus(clientMatched, encrypted) {
  var note = encrypted ? 'Password-protected PDF, ask the client for an unlocked copy.' : '';
  if (!clientMatched) {
    return { status: 'Needs assignment', note: note ? 'Unknown sender. ' + note : 'Unknown sender.' };
  }
  return { status: encrypted ? 'Needs attention' : 'New', note: note };
}

function ackBody(contactName, files, firmName) {
  var hello = contactName ? 'Hi ' + contactName + ',' : 'Hello,';
  var lines = [hello, '', 'Thanks, we received ' + (files.length === 1 ? 'this document' : 'these ' + files.length + ' documents') + ':', ''];
  files.forEach(function (f) {
    lines.push('- ' + f.name + ' (' + f.type + ')' + (f.encrypted ? ' - this one is password protected, could you send an unlocked copy?' : ''));
  });
  lines.push('', 'Someone on our team will pick them up and let you know if anything else is needed.', '', firmName);
  return lines.join('\n');
}

function chatIntakeText(clientName, senderEmail, files, trackerUrl) {
  var who = clientName ? '*' + clientName + '*' : '*Unknown sender* ' + senderEmail;
  var head = clientName
    ? 'New documents from ' + who + ':'
    : 'Documents from ' + who + ' are in _Unassigned. Can someone pick the client in the tracker?';
  var list = files.map(function (f) {
    return '- ' + f.name + ' (' + f.type + ')' + (f.encrypted ? ' - password protected' : '');
  });
  return [head].concat(list).concat(trackerUrl ? ['<' + trackerUrl + '|Open the tracker>'] : []).join('\n');
}

/**
 * Friday numbers from Intake rows. Each row: { received, status, assignedAt, daysToAssign, client }.
 */
function weeklySummary(rows, now) {
  var weekAgo = new Date(new Date(now).getTime() - 7 * 86400000);
  var received = 0, assigned = 0, dayTotal = 0, dayCount = 0;
  var open = {};
  OPEN_STATUSES.forEach(function (s) { open[s] = 0; });
  rows.forEach(function (r) {
    if (r.received && new Date(r.received) >= weekAgo) received++;
    if (r.assignedAt && new Date(r.assignedAt) >= weekAgo) {
      assigned++;
      if (typeof r.daysToAssign === 'number' && !isNaN(r.daysToAssign)) { dayTotal += r.daysToAssign; dayCount++; }
    }
    if (open.hasOwnProperty(r.status)) open[r.status]++;
  });
  return {
    received: received,
    assigned: assigned,
    avgDaysToAssign: dayCount ? Math.round((dayTotal / dayCount) * 10) / 10 : null,
    open: open
  };
}

/** Collapses repeated alerts: same function and same message is one alert per hour. */
function alertKey(fnName, message) {
  return ('alert:' + fnName + ':' + String(message || '')).slice(0, 240);
}

if (typeof module !== 'undefined') {
  module.exports = {
    parseAddress: parseAddress, splitList: splitList, emailDomain: emailDomain,
    matchClient: matchClient, classifyDocument: classifyDocument,
    isEncryptedPdf: isEncryptedPdf, shouldSkipAttachment: shouldSkipAttachment,
    daysBetween: daysBetween, intakeId: intakeId, rowStatus: rowStatus,
    ackBody: ackBody, chatIntakeText: chatIntakeText, weeklySummary: weeklySummary,
    alertKey: alertKey, STATUSES: STATUSES
  };
}
