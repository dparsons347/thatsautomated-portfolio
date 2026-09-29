/**
 * One-time setup, safe to run again. Run it from the Apps Script editor of the
 * tracker spreadsheet (the script is bound to it). It creates or reuses:
 * the three tabs, the Drive folders, the Gmail labels and filter, and the triggers.
 */

var INTAKE_ADDRESS_DEFAULT = 'daniel+intake@thatsautomated.com';

function setup() {
  var props = PropertiesService.getScriptProperties();
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) throw new Error('Run setup() from the script bound to the tracker spreadsheet.');
  props.setProperty('SPREADSHEET_ID', ss.getId());
  if (!props.getProperty('FIRM_NAME')) props.setProperty('FIRM_NAME', 'Oakline Tax Group');
  if (!props.getProperty('ALERT_EMAIL')) props.setProperty('ALERT_EMAIL', Session.getEffectiveUser().getEmail());
  if (!props.getProperty('INTAKE_ADDRESS')) props.setProperty('INTAKE_ADDRESS', INTAKE_ADDRESS_DEFAULT);
  ss.setSpreadsheetTimeZone('America/Chicago');

  setupTabs_(ss);
  setupFolders_(props, ss);
  setupGmail_(props.getProperty('INTAKE_ADDRESS'));
  setupTriggers_(ss);
  log_('INFO', 'setup() finished.');
  return 'Setup done. Remaining by hand: CHAT_WEBHOOK_URL and REPORT_URL script properties.';
}

function ensureSheet_(ss, name, headers) {
  var sh = ss.getSheetByName(name) || ss.insertSheet(name);
  if (sh.getLastRow() === 0) {
    sh.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  return sh;
}

function setupTabs_(ss) {
  var clients = ensureSheet_(ss, TAB_CLIENTS, CLIENT_HEADERS);
  if (clients.getLastRow() === 1) {
    clients.getRange(2, 1, SEED_CLIENTS.length, CLIENT_HEADERS.length).setValues(SEED_CLIENTS);
  }
  var intake = ensureSheet_(ss, TAB_INTAKE, INTAKE_HEADERS);
  var log = ensureSheet_(ss, TAB_LOG, LOG_HEADERS);

  var maxRows = intake.getMaxRows() - 1;
  intake.getRange(2, COL['Received'], maxRows, 1).setNumberFormat('yyyy-mm-dd hh:mm');
  intake.getRange(2, COL['Assigned at'], maxRows, 1).setNumberFormat('yyyy-mm-dd hh:mm');
  intake.getRange(2, COL['Days to assign'], maxRows, 1).setNumberFormat('0.0');
  log.getRange(2, 1, log.getMaxRows() - 1, 1).setNumberFormat('yyyy-mm-dd hh:mm:ss');

  intake.getRange(2, COL['Status'], maxRows, 1).setDataValidation(
    SpreadsheetApp.newDataValidation().requireValueInList(STATUSES, true).setAllowInvalid(false).build());
  intake.getRange(2, COL['Assigned to'], maxRows, 1).setDataValidation(
    SpreadsheetApp.newDataValidation().requireValueInList(STAFF, true).setAllowInvalid(false).build());
  intake.getRange(2, COL['Client'], maxRows, 1).setDataValidation(
    SpreadsheetApp.newDataValidation().requireValueInRange(clients.getRange('A2:A'), true).setAllowInvalid(true).build());

  // Colour the statuses that need a person.
  var statusRange = intake.getRange(2, COL['Status'], maxRows, 1);
  var rules = [
    ['Needs assignment', '#fce8b2'], ['Needs attention', '#f4c7c3'], ['Waiting on client', '#d9d2e9'], ['Done', '#d9ead3']
  ].map(function (p) {
    return SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo(p[0]).setBackground(p[1]).setRanges([statusRange]).build();
  });
  intake.setConditionalFormatRules(rules);

  // Hide the machine columns from the people using the sheet.
  intake.hideColumns(COL['Message ID'], 2);

  var sheet1 = ss.getSheetByName('Sheet1');
  if (sheet1 && ss.getSheets().length > 1 && sheet1.getLastRow() === 0) ss.deleteSheet(sheet1);
  ss.setActiveSheet(intake);
}

function childFolder_(parent, name) {
  var it = parent.getFoldersByName(name);
  return it.hasNext() ? it.next() : parent.createFolder(name);
}

function setupFolders_(props, ss) {
  var root;
  var rootId = props.getProperty('ROOT_FOLDER_ID');
  if (rootId) { try { root = DriveApp.getFolderById(rootId); } catch (e) { root = null; } }
  if (!root) {
    var it = DriveApp.getFoldersByName('Oakline Tax Group');
    root = it.hasNext() ? it.next() : DriveApp.createFolder('Oakline Tax Group');
  }
  var clientFiles = childFolder_(root, 'Client Files');
  var unassigned = childFolder_(clientFiles, '_Unassigned');
  props.setProperties({
    ROOT_FOLDER_ID: root.getId(),
    CLIENT_FILES_FOLDER_ID: clientFiles.getId(),
    UNASSIGNED_FOLDER_ID: unassigned.getId()
  });
  // Keep the tracker next to the files.
  var file = DriveApp.getFileById(ss.getId());
  if (!file.getParents().hasNext() || file.getParents().next().getId() !== root.getId()) file.moveTo(root);
}

function setupGmail_(intakeAddress) {
  var intake = GmailApp.getUserLabelByName(LABEL_INTAKE) || GmailApp.createLabel(LABEL_INTAKE);
  GmailApp.getUserLabelByName(LABEL_DONE) || GmailApp.createLabel(LABEL_DONE);

  // Filter: mail to the intake address gets the label. Needs the Gmail advanced service.
  var labelId = Gmail.Users.Labels.list('me').labels.filter(function (l) { return l.name === LABEL_INTAKE; })[0].id;
  var existing = (Gmail.Users.Settings.Filters.list('me').filter || []).filter(function (f) {
    return f.criteria && f.criteria.to === intakeAddress;
  });
  if (!existing.length) {
    Gmail.Users.Settings.Filters.create({ criteria: { to: intakeAddress }, action: { addLabelIds: [labelId] } }, 'me');
  }
  return intake;
}

function setupTriggers_(ss) {
  var wanted = ['processInbox', 'onTrackerEdit', 'fridaySummary'];
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (wanted.indexOf(t.getHandlerFunction()) >= 0) ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('processInbox').timeBased().everyMinutes(1).create();
  ScriptApp.newTrigger('onTrackerEdit').forSpreadsheet(ss).onEdit().create();
  ScriptApp.newTrigger('fridaySummary').timeBased().onWeekDay(ScriptApp.WeekDay.FRIDAY).atHour(16).create();
}

/** Clears Intake and Log rows and empties the client folders, for a clean Loom take. */
function resetDemo() {
  var ss = tracker_();
  [TAB_INTAKE, TAB_LOG].forEach(function (name) {
    var sh = ss.getSheetByName(name);
    if (sh && sh.getLastRow() > 1) sh.getRange(2, 1, sh.getLastRow() - 1, sh.getLastColumn()).clearContent();
  });
  var c = cfg_();
  var clientFiles = DriveApp.getFolderById(c.clientFilesId);
  var folders = clientFiles.getFolders();
  while (folders.hasNext()) {
    var f = folders.next();
    var files = f.getFiles();
    while (files.hasNext()) files.next().setTrashed(true);
  }
  var threads = GmailApp.search('label:client-intake');
  var done = GmailApp.getUserLabelByName(LABEL_DONE);
  threads.forEach(function (t) { t.moveToTrash(); if (done) t.removeLabel(done); });
  return 'Demo reset: tracker rows cleared, client files trashed, intake threads trashed.';
}
