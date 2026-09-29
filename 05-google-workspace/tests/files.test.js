// Runs the pure logic against the real test-data files, and loads all three
// Apps Script files together to catch clashing or missing globals.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const L = require('../apps-script/Lib.js');

const dir = path.join(__dirname, '..', 'test-data');
const latin1 = (f) => fs.readFileSync(path.join(dir, f)).toString('latin1');

test('the locked test PDF is detected, the others are not', () => {
  assert.equal(L.isEncryptedPdf('Brokerage 1099-B locked.pdf', 'application/pdf', latin1('Brokerage 1099-B locked.pdf')), true);
  for (const f of ['W-2 2025 Marcus Rivera.pdf', '1099-NEC Rivera Consulting.pdf', 'Chase bank statement March.pdf']) {
    assert.equal(L.isEncryptedPdf(f, 'application/pdf', latin1(f)), false, f);
  }
});

test('test-data files classify as expected', () => {
  const want = {
    'W-2 2025 Marcus Rivera.pdf': 'W-2',
    '1099-NEC Rivera Consulting.pdf': '1099',
    'Chase bank statement March.pdf': 'Bank statement',
    'Brokerage 1099-B locked.pdf': '1099',
    'receipt office supplies.jpg': 'Receipt',
  };
  for (const [f, t] of Object.entries(want)) assert.equal(L.classifyDocument(f, ''), t, f);
});

test('receipt photo is kept, signature logo is skipped', () => {
  const size = (f) => fs.statSync(path.join(dir, f)).size;
  assert.equal(L.shouldSkipAttachment('receipt office supplies.jpg', 'image/jpeg', size('receipt office supplies.jpg')), false);
  assert.equal(L.shouldSkipAttachment('signature-logo.png', 'image/png', size('signature-logo.png')), true);
});

test('all Apps Script files load together in one global scope', () => {
  const ctx = vm.createContext({ console });
  const dir2 = path.join(__dirname, '..', 'apps-script');
  for (const f of fs.readdirSync(dir2).filter((x) => x.endsWith('.js')).sort()) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'apps-script', f), 'utf8'), ctx, { filename: f });
  }
  for (const fn of ['setup', 'processInbox', 'onTrackerEdit', 'fridaySummary', 'resetDemo', 'testChat', 'matchClient']) {
    assert.equal(typeof ctx[fn], 'function', fn);
  }
  assert.equal(ctx.COL['File ID'], 14);
  assert.equal(ctx.SEED_CLIENTS[0][1], 'parsodg@gmail.com');
});
