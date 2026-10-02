const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../apps-script/Lib.js');

const clients = [
  { name: 'Marcus Rivera', emails: ['mrivera.demo@gmail.com'], domains: [] },
  { name: 'Brightline Dental', emails: [], domains: ['brightlinedental.com'] },
  { name: 'Gmail Claimer', emails: [], domains: ['gmail.com'] }, // a mistake in the Clients tab
];

test('parseAddress handles names, quotes and bare addresses', () => {
  assert.deepEqual(L.parseAddress('Marcus Rivera <MRivera.Demo@Gmail.com>'), { name: 'Marcus Rivera', email: 'mrivera.demo@gmail.com' });
  assert.deepEqual(L.parseAddress('"Rivera, Marcus" <m@x.com>'), { name: 'Rivera, Marcus', email: 'm@x.com' });
  assert.deepEqual(L.parseAddress('m@x.com'), { name: '', email: 'm@x.com' });
});

test('splitList trims, lowercases and drops blanks', () => {
  assert.deepEqual(L.splitList(' A@x.com, b@Y.com;\n ,c '), ['a@x.com', 'b@y.com', 'c']);
  assert.deepEqual(L.splitList(''), []);
});

test('matchClient: exact email wins', () => {
  assert.equal(L.matchClient('MRIVERA.DEMO@gmail.com', clients).name, 'Marcus Rivera');
});

test('matchClient: business domain matches', () => {
  assert.equal(L.matchClient('frontdesk@brightlinedental.com', clients).name, 'Brightline Dental');
});

test('matchClient: free-mail domain never matches by domain', () => {
  assert.equal(L.matchClient('mrivera.demo+hvac1@gmail.com', clients), null);
  assert.equal(L.matchClient('stranger@yahoo.com', clients), null);
});

test('matchClient: unknown and empty senders', () => {
  assert.equal(L.matchClient('someone@unknown.org', clients), null);
  assert.equal(L.matchClient('', clients), null);
});

test('classifyDocument from file names', () => {
  const cases = {
    'W-2 2025.pdf': 'W-2', 'w2_acme.pdf': 'W-2', 'Rivera_W2.PDF': 'W-2',
    '1099-NEC Uber.pdf': '1099', '1099-INT_chase.pdf': '1099', '1099.pdf': '1099',
    '1098 mortgage.pdf': '1098', 'mortgage interest statement.pdf': '1098',
    'K-1 Hollis LLC.pdf': 'K-1', 'k1.pdf': 'K-1',
    '2024 tax return.pdf': 'Prior-year return', '1040 last year.pdf': 'Prior-year return',
    'Chase bank statement March.pdf': 'Bank statement', 'stmt_0325.pdf': 'Bank statement',
    'Office Depot receipt.jpg': 'Receipt', 'invoice-4411.pdf': 'Receipt',
    'drivers license front.jpg': 'ID', 'passport.png': 'ID',
    'Signed engagement letter.pdf': 'Engagement letter',
    'scan0001.pdf': 'Other',
  };
  for (const [name, want] of Object.entries(cases)) {
    assert.equal(L.classifyDocument(name, ''), want, name);
  }
});

test('classifyDocument: 1099 in a name is not read as a W-2 or return', () => {
  assert.equal(L.classifyDocument('1099-R retirement.pdf', 'my return docs'), '1099');
});

test('classifyDocument falls back to the subject only when it names one type', () => {
  assert.equal(L.classifyDocument('scan0001.pdf', 'Here is my W-2'), 'W-2');
  assert.equal(L.classifyDocument('scan0001.pdf', 'W-2 and 1099 attached'), 'Other');
  assert.equal(L.classifyDocument('scan0001.pdf', 'Documents for my return'), 'Other');
});

test('isEncryptedPdf', () => {
  const plain = '%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>';
  const locked = '%PDF-1.7\n...\ntrailer << /Root 1 0 R /Encrypt 5 0 R /ID [<a><b>] >>';
  const lockedInline = '%PDF-1.4 trailer<</Encrypt<</Filter/Standard>>>>';
  assert.equal(L.isEncryptedPdf('a.pdf', 'application/pdf', plain), false);
  assert.equal(L.isEncryptedPdf('a.pdf', 'application/pdf', locked), true);
  assert.equal(L.isEncryptedPdf('a.pdf', 'application/octet-stream', lockedInline), true);
  assert.equal(L.isEncryptedPdf('a.jpg', 'image/jpeg', locked), false);
  assert.equal(L.isEncryptedPdf('a.pdf', 'application/pdf', '/EncryptMetadata false'), false);
});

test('shouldSkipAttachment only skips small images', () => {
  assert.equal(L.shouldSkipAttachment('logo.png', 'image/png', 8000), true);
  assert.equal(L.shouldSkipAttachment('receipt.jpg', 'image/jpeg', 250000), false);
  assert.equal(L.shouldSkipAttachment('tiny.pdf', 'application/pdf', 900), false);
});

test('daysBetween rounds to one decimal', () => {
  assert.equal(L.daysBetween('2026-09-28T09:00:00Z', '2026-09-29T21:00:00Z'), 1.5);
  assert.equal(L.daysBetween('2026-09-28T09:00:00Z', '2026-09-28T09:30:00Z'), 0);
});

test('intakeId pads and uses the received date', () => {
  assert.equal(L.intakeId(new Date(2026, 8, 29, 10), 7), 'INT-20260929-0007');
});

test('rowStatus covers the four cases', () => {
  assert.deepEqual(L.rowStatus(true, false), { status: 'New', note: '' });
  assert.equal(L.rowStatus(true, true).status, 'Needs attention');
  assert.match(L.rowStatus(true, true).note, /unlocked copy/);
  assert.deepEqual(L.rowStatus(false, false), { status: 'Needs assignment', note: 'Unknown sender.' });
  assert.match(L.rowStatus(false, true).note, /^Unknown sender\. Password-protected/);
});

test('ackBody lists files and flags locked ones', () => {
  const body = L.ackBody('Marcus', [
    { name: 'W-2.pdf', type: 'W-2', encrypted: false },
    { name: 'brokerage.pdf', type: 'Other', encrypted: true },
  ], 'Oakline Tax Group');
  assert.match(body, /^Hi Marcus,/);
  assert.match(body, /these 2 documents/);
  assert.match(body, /brokerage\.pdf \(Other\) - this one is password protected/);
  assert.match(body, /Oakline Tax Group$/);
  assert.match(L.ackBody('', [{ name: 'a.pdf', type: 'W-2' }], 'X'), /^Hello,[\s\S]*this document/);
});

test('chatIntakeText: known vs unknown sender', () => {
  const f = [{ name: 'a.pdf', type: 'W-2', encrypted: false }];
  assert.match(L.chatIntakeText('Marcus Rivera', 'p@g.com', f, 'https://t'), /^New documents from \*Marcus Rivera\*:\n- a\.pdf \(W-2\)\n<https:\/\/t\|Open the tracker>$/);
  assert.match(L.chatIntakeText('', 'x@y.com', f, ''), /Unknown sender\* x@y\.com are in _Unassigned/);
});

test('weeklySummary counts the last seven days and open items', () => {
  const now = new Date('2026-10-02T21:00:00Z');
  const rows = [
    { received: '2026-09-30T15:00:00Z', status: 'Assigned', assignedAt: '2026-10-01T15:00:00Z', daysToAssign: 1 },
    { received: '2026-10-01T15:00:00Z', status: 'Needs assignment', assignedAt: '', daysToAssign: NaN },
    { received: '2026-10-02T15:00:00Z', status: 'Assigned', assignedAt: '2026-10-02T16:00:00Z', daysToAssign: 0 },
    { received: '2026-09-10T15:00:00Z', status: 'Done', assignedAt: '2026-09-11T15:00:00Z', daysToAssign: 1 },
    { received: '2026-09-29T15:00:00Z', status: 'Waiting on client', assignedAt: '', daysToAssign: NaN },
  ];
  const s = L.weeklySummary(rows, now);
  assert.equal(s.received, 4);
  assert.equal(s.assigned, 2);
  assert.equal(s.avgDaysToAssign, 0.5);
  assert.deepEqual(s.open, { New: 0, 'Needs assignment': 1, 'Needs attention': 0, Assigned: 2, 'Waiting on client': 1 });
});

test('alertKey is bounded', () => {
  assert.ok(L.alertKey('processInbox', 'x'.repeat(1000)).length <= 240);
});
