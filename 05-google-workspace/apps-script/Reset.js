/**
 * Demo reset, run from the editor before recording. Kept in its own file so the
 * editor's Run button defaults to it when this file is open.
 */
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
