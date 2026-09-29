/**
 * Oakline Tax Group intake: Gmail -> Drive -> tracker sheet -> Chat.
 * Entry points: setup, processInbox, onTrackerEdit, fridaySummary.
 * Every trigger entry point runs through guarded_ so a failure alerts within
 * the minute instead of waiting for Apps Script's daily failure digest.
 */

var TAB_CLIENTS = 'Clients';
var TAB_INTAKE = 'Intake';
var TAB_LOG = 'Log';
var LABEL_INTAKE = 'Client Intake';
var LABEL_DONE = 'Client Intake/Processed';
var SEARCH_QUERY = 'label:client-intake newer_than:14d';

var CLIENT_HEADERS = ['Client', 'Emails', 'Domains', 'Folder ID', 'Contact name'];
var INTAKE_HEADERS = ['Intake ID', 'Received', 'Client', 'Sender', 'Subject', 'File', 'Document type',
  'Status', 'Assigned to', 'Assigned at', 'Days to assign', 'Notes', 'Message ID', 'File ID'];
var LOG_HEADERS = ['Time', 'Level', 'Message'];
var COL = {}; INTAKE_HEADERS.forEach(function (h, i) { COL[h] = i + 1; });

var STAFF = ['Dana Whitfield', 'Luis Ortega', 'Priya Natarajan'];

// Fictional clients. The first one is an address Daniel controls, used in the Loom.
var SEED_CLIENTS = [
  ['Marcus Rivera', 'parsodg@gmail.com', '', '', 'Marcus'],
  ['Brightline Dental', '', 'brightlinedental.com', '', 'Dr. Kim'],
  ['Hollis Family Farm', 'accounts@hollisfarm.com', '', '', 'June'],
  ['Carver & Webb Architects', '', 'carverwebb.com', '', 'Nora']
];

// ---------- configuration ----------

function cfg_() {
  var p = PropertiesService.getScriptProperties().getProperties();
  return {
    spreadsheetId: p.SPREADSHEET_ID,
    clientFilesId: p.CLIENT_FILES_FOLDER_ID,
    unassignedId: p.UNASSIGNED_FOLDER_ID,
    chatWebhook: p.CHAT_WEBHOOK_URL || '',
    alertEmail: p.ALERT_EMAIL || Session.getEffectiveUser().getEmail(),
    reportUrl: p.REPORT_URL || '',
    firmName: p.FIRM_NAME || 'Oakline Tax Group'
  };
}

function tracker_() {
  var id = cfg_().spreadsheetId;
  if (!id) throw new Error('SPREADSHEET_ID is not set. Run setup() from the tracker first.');
  return SpreadsheetApp.openById(id);
}

function requireSheet_(ss, name) {
  var sh = ss.getSheetByName(name);
  if (!sh) {
    throw new Error('Tab "' + name + '" not found in the tracker. Was it renamed? Rename it back to "' +
      name + '"; emails waiting in the inbox are filed on the next run.');
  }
  return sh;
}

// ---------- error handling ----------

function guarded_(name, fn, arg) {
  try {
    return fn(arg);
  } catch (e) {
    reportFailure_(name, e);
    throw e; // keep the run marked Failed in the Executions page
  }
}

function reportFailure_(name, e) {
  var message = (e && e.message) ? e.message : String(e);
  var key = alertKey(name, message);
  var cache = CacheService.getScriptCache();
  if (cache.get(key)) return;
  cache.put(key, '1', 3600);
  var c = cfg_();
  var execUrl = 'https://script.google.com/home/projects/' + ScriptApp.getScriptId() + '/executions';
  var body = [
    name + ' failed at ' + new Date().toString(),
    '',
    message,
    '',
    'Run history: ' + execUrl,
    '',
    'Nothing is lost: intake emails stay labeled and are picked up on the next run after the fix.',
    'Repeats of this same error are muted for an hour.',
    '',
    (e && e.stack) ? e.stack : ''
  ].join('\n');
  try { MailApp.sendEmail(c.alertEmail, '[' + c.firmName + ' intake] ' + name + ' failed', body); } catch (x) { console.error(x); }
  postChat_('*Intake automation failed* in `' + name + '`: ' + message + '\n<' + execUrl + '|Run history>');
  try { log_('ERROR', name + ': ' + message); } catch (x) { console.error(x); }
}

function log_(level, message) {
  console.log(level + ' ' + message);
  try {
    var sh = tracker_().getSheetByName(TAB_LOG);
    if (sh) sh.appendRow([new Date(), level, message]);
  } catch (e) { console.error('log_ failed: ' + e); }
}

function postChat_(text) {
  var url = cfg_().chatWebhook;
  if (!url) { console.log('Chat (no webhook set): ' + text); return false; }
  try {
    var res = UrlFetchApp.fetch(url, {
      method: 'post',
      contentType: 'application/json; charset=UTF-8',
      payload: JSON.stringify({ text: text }),
      muteHttpExceptions: true
    });
    if (res.getResponseCode() >= 300) {
      console.warn('Chat post returned ' + res.getResponseCode() + ': ' + res.getContentText());
      return false;
    }
    return true;
  } catch (e) {
    console.warn('Chat post failed: ' + e); // a Chat outage must not stop intake
    return false;
  }
}

// ---------- intake ----------

function processInbox() { return guarded_('processInbox', processInbox_); }

function processInbox_() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) { console.log('Another run is active, skipping.'); return; }
  try {
    var c = cfg_();
    var ss = tracker_();
    var intake = requireSheet_(ss, TAB_INTAKE);
    var clientsSheet = requireSheet_(ss, TAB_CLIENTS);
    var clients = readClients_(clientsSheet);
    var seen = seenMessageIds_(intake);
    var me = Session.getEffectiveUser().getEmail().toLowerCase();
    var doneLabel = GmailApp.getUserLabelByName(LABEL_DONE) || GmailApp.createLabel(LABEL_DONE);

    var threads = GmailApp.search(SEARCH_QUERY, 0, 50);
    var filed = 0;
    threads.forEach(function (thread) {
      thread.getMessages().forEach(function (msg) {
        var id = msg.getId();
        if (seen[id]) return;
        var sender = parseAddress(msg.getFrom());
        if (sender.email === me) { seen[id] = true; return; } // our own acknowledgements
        filed += fileMessage_(msg, sender, clients, intake, clientsSheet, c);
        seen[id] = true;
      });
      thread.addLabel(doneLabel);
    });
    if (filed) log_('INFO', 'Filed ' + filed + ' row(s).');
  } finally {
    lock.releaseLock();
  }
}

function fileMessage_(msg, sender, clients, intake, clientsSheet, c) {
  var client = matchClient(sender.email, clients);
  var folder = client ? clientFolder_(client, clientsSheet, c) : DriveApp.getFolderById(c.unassignedId);
  var subject = msg.getSubject();
  var received = msg.getDate();
  var attachments = msg.getAttachments({ includeInlineImages: false });
  var files = [];
  var rows = [];
  var next = Math.max(intake.getLastRow(), 1);

  attachments.forEach(function (att) {
    if (shouldSkipAttachment(att.getName(), att.getContentType(), att.getSize())) return;
    var blob = att.copyBlob();
    var encrypted = isEncryptedPdf(att.getName(), att.getContentType(), blob.getDataAsString('ISO-8859-1'));
    var file = folder.createFile(blob.setName(att.getName()));
    var type = classifyDocument(att.getName(), subject);
    var st = rowStatus(!!client, encrypted);
    files.push({ name: att.getName(), type: type, encrypted: encrypted });
    rows.push([intakeId(received, next++), received, client ? client.name : '', sender.email, subject,
      linkFormula_(file.getUrl(), att.getName()), type, st.status, '', '', '', st.note, msg.getId(), file.getId()]);
  });

  if (!rows.length) {
    rows.push([intakeId(received, next++), received, client ? client.name : '', sender.email, subject, '',
      'No attachment', client ? 'Needs attention' : 'Needs assignment', '', '', '',
      'Email had no attachments.', msg.getId(), '']);
  }

  intake.getRange(intake.getLastRow() + 1, 1, rows.length, INTAKE_HEADERS.length).setValues(rows);

  if (client && files.length) {
    msg.reply(ackBody(client.contact, files, c.firmName));
  }
  if (files.length || !client) {
    postChat_(chatIntakeText(client ? client.name : '', sender.email,
      files.length ? files : [{ name: '(no attachment)', type: 'email only', encrypted: false }],
      tracker_().getUrl() + '#gid=' + intake.getSheetId()));
  }
  return rows.length;
}

function linkFormula_(url, name) {
  return '=HYPERLINK("' + url + '","' + String(name).replace(/"/g, '""') + '")';
}

function readClients_(sheet) {
  var values = sheet.getDataRange().getValues().slice(1);
  var out = [];
  values.forEach(function (r, i) {
    if (!String(r[0]).trim()) return;
    out.push({ row: i + 2, name: String(r[0]).trim(), emails: splitList(r[1]), domains: splitList(r[2]),
      folderId: String(r[3] || '').trim(), contact: String(r[4] || '').trim() });
  });
  return out;
}

function seenMessageIds_(intake) {
  var seen = {};
  var n = intake.getLastRow() - 1;
  if (n < 1) return seen;
  intake.getRange(2, COL['Message ID'], n, 1).getValues().forEach(function (r) { if (r[0]) seen[r[0]] = true; });
  return seen;
}

function clientFolder_(client, clientsSheet, c) {
  if (client.folderId) {
    try { return DriveApp.getFolderById(client.folderId); } catch (e) { /* deleted, recreate below */ }
  }
  var parent = DriveApp.getFolderById(c.clientFilesId);
  var it = parent.getFoldersByName(client.name);
  var folder = it.hasNext() ? it.next() : parent.createFolder(client.name);
  clientsSheet.getRange(client.row, 4).setValue(folder.getId());
  client.folderId = folder.getId();
  return folder;
}

// ---------- tracker edits ----------

function onTrackerEdit(e) { return guarded_('onTrackerEdit', onTrackerEdit_, e); }

function onTrackerEdit_(e) {
  if (!e || !e.range) return;
  var sh = e.range.getSheet();
  if (sh.getName() !== TAB_INTAKE) return;
  var c = cfg_();
  var r0 = e.range.getRow(), c0 = e.range.getColumn();
  var r1 = r0 + e.range.getNumRows() - 1, c1 = c0 + e.range.getNumColumns() - 1;
  for (var r = Math.max(r0, 2); r <= r1; r++) {
    if (c0 <= COL['Client'] && COL['Client'] <= c1) clientChosen_(sh, r, c);
    if (c0 <= COL['Status'] && COL['Status'] <= c1) statusChanged_(sh, r);
  }
}

function rowObject_(sh, r) {
  var v = sh.getRange(r, 1, 1, INTAKE_HEADERS.length).getValues()[0];
  var o = {};
  INTAKE_HEADERS.forEach(function (h, i) { o[h] = v[i]; });
  return o;
}

function statusChanged_(sh, r) {
  var row = rowObject_(sh, r);
  if (row['Status'] !== 'Assigned' || row['Assigned at']) return;
  var now = new Date();
  sh.getRange(r, COL['Assigned at']).setValue(now);
  sh.getRange(r, COL['Days to assign']).setValue(daysBetween(row['Received'], now));
  var who = row['Assigned to'] || 'someone (Assigned to is blank)';
  postChat_('*' + row['Intake ID'] + '* ' + row['Document type'] + ' from ' + (row['Client'] || row['Sender']) +
    ' is assigned to *' + who + '*. Waited ' + daysBetween(row['Received'], now) + ' days.');
}

function clientChosen_(sh, r, c) {
  var row = rowObject_(sh, r);
  if (row['Status'] !== 'Needs assignment' || !row['Client']) return;
  var clientsSheet = requireSheet_(tracker_(), TAB_CLIENTS);
  var clients = readClients_(clientsSheet);
  var client = clients.filter(function (x) { return x.name === String(row['Client']).trim(); })[0];
  if (!client) {
    sh.getRange(r, COL['Notes']).setValue('No client named "' + row['Client'] + '" in the Clients tab.');
    return;
  }
  if (row['File ID']) {
    DriveApp.getFileById(row['File ID']).moveTo(clientFolder_(client, clientsSheet, c));
  }
  var locked = /password-protected/i.test(String(row['Notes']));
  sh.getRange(r, COL['Status']).setValue(locked ? 'Needs attention' : 'New');
  sh.getRange(r, COL['Notes']).setValue(String(row['Notes']).replace(/^Unknown sender\.\s*/, ''));
  postChat_('Filed ' + (row['File'] ? '"' + fileNameFromCell_(sh, r) + '"' : 'the email') + ' from ' +
    row['Sender'] + ' under *' + client.name + '*.');
}

function fileNameFromCell_(sh, r) {
  return sh.getRange(r, COL['File']).getDisplayValue();
}

// ---------- Friday summary ----------

function fridaySummary() { return guarded_('fridaySummary', fridaySummary_); }

function fridaySummary_() {
  var c = cfg_();
  var intake = requireSheet_(tracker_(), TAB_INTAKE);
  var n = intake.getLastRow() - 1;
  var values = n > 0 ? intake.getRange(2, 1, n, INTAKE_HEADERS.length).getValues() : [];
  var rows = values.map(function (v) {
    return { received: v[COL['Received'] - 1], status: v[COL['Status'] - 1], assignedAt: v[COL['Assigned at'] - 1],
      daysToAssign: v[COL['Days to assign'] - 1] === '' ? NaN : Number(v[COL['Days to assign'] - 1]) };
  });
  var s = weeklySummary(rows, new Date());
  var lines = [
    'Intake for the week ending ' + Utilities.formatDate(new Date(), 'America/Chicago', 'EEE MMM d') + ':',
    '',
    'Documents received: ' + s.received,
    'Documents assigned: ' + s.assigned,
    'Average days to assign: ' + (s.avgDaysToAssign === null ? 'n/a' : s.avgDaysToAssign),
    '',
    'Open right now:'
  ];
  Object.keys(s.open).forEach(function (k) { lines.push('  ' + k + ': ' + s.open[k]); });
  if (c.reportUrl) lines.push('', 'Report: ' + c.reportUrl);
  lines.push('Tracker: ' + tracker_().getUrl());
  MailApp.sendEmail(c.alertEmail, c.firmName + ' intake, week ending ' +
    Utilities.formatDate(new Date(), 'America/Chicago', 'MMM d'), lines.join('\n'));
  log_('INFO', 'Friday summary sent.');
}
