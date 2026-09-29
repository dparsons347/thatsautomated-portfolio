# 05 - Google Workspace: client document intake for a small tax office

A small tax office's document intake, automated inside the Google Workspace it already pays for. Clients email documents to one address. Each file lands in that client's Drive folder, gets a row in the tracking sheet with its document type, the client gets one acknowledgement, and the team gets a Google Chat post. A Looker Studio report and a Friday summary email replace the status report someone used to write by hand.

The office, Oakline Tax Group, and its clients are fictional. The mailbox, Drive, Sheets, and Chat space are real.

**Status: built and tested live (Sep 29, 2026). Chat webhook and Looker Studio report still to add, then Loom.**

Changed on Sep 29, 2026 from Microsoft 365 (Power Automate, SharePoint, Power BI) to Google Workspace. Same client story, same failure cases.

## What this proves

- An office that runs on Gmail, Drive, and Sheets can get intake, filing, and reporting automated with no new subscription and no new login.
- Apps Script is real code: it lives in Git, deploys with clasp, and has tests. The odd cases (free-mail senders, signature logos, locked PDFs, the same email processed twice) are handled on purpose.
- Failures are loud. Out of the box Apps Script emails a daily failure digest; this sends an alert and a Chat post within the minute, and nothing is lost while it is broken.

## How it works

```
Gmail  daniel+intake@thatsautomated.com
  | filter adds label "Client Intake"
  v
processInbox (every minute)
  | match sender -> client (exact email, then business domain; gmail.com etc. never match by domain)
  | per attachment: skip images < 20 KB, save to Drive, classify, check for PDF encryption
  | one tracker row per file, dedupe on Gmail message ID
  | reply to the client once, post to Chat, label thread "Client Intake/Processed"
  v
Tracker sheet "Oakline Intake Tracker"  (Clients | Intake | Log)
  | onTrackerEdit: Status -> Assigned stamps Assigned at + Days to assign, posts to Chat
  | onTrackerEdit: Client filled in on an _Unassigned row moves the file to that client's folder
  v
Looker Studio report + fridaySummary email (Fridays 4 PM Central)
```

| File | What |
|---|---|
| `apps-script/Lib.js` | Pure logic: client matching, document classification, encrypted-PDF check, attachment skip rule, summary math. No Google services, so it runs under Node. |
| `apps-script/Main.js` | Entry points `processInbox`, `onTrackerEdit`, `fridaySummary`, and the error wrapper. |
| `apps-script/Setup.js` | `setup()` (tabs, folders, Gmail labels and filter, triggers; safe to rerun) and `resetDemo()`. |
| `apps-script/appsscript.json` | Manifest: Central time, V8, Gmail advanced service (for the filter). |
| `tests/` | `node --test` suites: 22 tests, including the real test-data files. |
| `test-data/` | Fake W-2, 1099-NEC, bank statement, a password-protected 1099-B (password `oakline`), a phone-photo receipt, a signature logo. `make_test_data.py` rebuilds them. |

## Document types

Classified from the file name, then from the subject only if the subject names exactly one type: W-2, 1099, 1098, K-1, Prior-year return, Bank statement, Receipt, ID, Engagement letter, Other. First match wins, in that order.

## Statuses

New, Needs assignment (unknown sender), Needs attention (locked PDF or no attachment), Assigned, Waiting on client, Done.

## Script properties

| Property | Set by |
|---|---|
| `SPREADSHEET_ID`, `ROOT_FOLDER_ID`, `CLIENT_FILES_FOLDER_ID`, `UNASSIGNED_FOLDER_ID` | `setup()` |
| `FIRM_NAME`, `ALERT_EMAIL`, `INTAKE_ADDRESS` | `setup()` defaults, editable |
| `CHAT_WEBHOOK_URL` | by hand (Chat space > Apps & integrations > Webhooks) |
| `REPORT_URL` | by hand, after the Looker Studio report exists |

## Setup

1. `npm i -g @google/clasp`, `clasp login` as daniel@thatsautomated.com, and turn on the Apps Script API at script.google.com/home/usersettings.
2. `clasp create --type sheets --title "Oakline Intake Tracker" --rootDir apps-script` (creates the sheet and a bound script; `.clasp.json` is gitignored).
3. `clasp push`, open the script, run `setup()`, approve the scopes.
4. Create the Chat space "Oakline Intake", add an incoming webhook, paste its URL into the `CHAT_WEBHOOK_URL` script property.
5. Build the Looker Studio report on the Intake tab, put its link in `REPORT_URL`.

## Live test (Sep 29, 2026)

Sheet "Oakline Intake Tracker" and its bound script, created with clasp and set up with `setup()`. Test emails sent from parsodg@gmail.com (client Marcus Rivera) to daniel+intake@thatsautomated.com. Chat webhook not yet set, so Chat posts were logged instead.

| # | Case | Result |
|---|---|---|
| 1 | Client email, W-2 + 1099-NEC + a 700-byte signature logo | Pass. Two rows (W-2, 1099), status New, logo skipped, client folder created, one threaded acknowledgement listing both files |
| 2 | Password-protected 1099-B | Pass. Saved, row Needs attention with the unlock note |
| 3 | Unknown sender (Marcus's email blanked in Clients for one send) | Pass. Filed to `_Unassigned`, row Needs assignment. Picking Marcus Rivera in the row moved the file to his folder and set status New |
| 4 | Status set to Assigned | Pass. Assigned at and Days to assign stamped |
| 5 | `Intake` tab renamed to `Intake2`, then an email sent | Pass. processInbox failed with the rename message, alert sent on the first failure and muted on the next, error in Log. After renaming back, the waiting email was filed on the next run |

Found and fixed during the run: Sheets turned the document type "1099" into a number. The Document type and Intake ID columns are now formatted as plain text in `setup()`.

## Tests

```
npm test
```

## When it breaks

| Failure | What happens |
|---|---|
| Unknown sender | Filed in `Client Files/_Unassigned`, row marked Needs assignment, Chat asks someone to assign it. Picking the client in the row moves the file. |
| Password-protected PDF | Saved anyway, row marked Needs attention with a note, the client's acknowledgement asks for an unlocked copy, the run carries on. |
| `Intake` tab renamed | The run throws a clear error, an alert email and Chat post go out (once per hour per error), the run shows Failed in Executions. The email keeps its label, so it is filed on the first run after the tab is renamed back. |
| Same email seen twice | Skipped on Gmail message ID. |
| Chat webhook down | Logged as a warning; intake carries on. |

Known limit: if a run dies after saving a file to Drive but before writing its row, the retry saves the file again. The row is written once.
