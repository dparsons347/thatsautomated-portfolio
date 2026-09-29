// The reviewer can fix the yellow cells (vendor, invoice number, dates,
// total, tax) before ticking approve. Normalize what they typed and refuse
// anything that can't be read, so a typo comes back to them on the sheet
// instead of going to QuickBooks. One row per run.
const r = $input.first().json;

const money = (v) => {
  if (v === '' || v === null || v === undefined) return null;
  const n = Number(String(v).replace(/[$,\s]/g, ''));
  return Number.isFinite(n) ? Math.round(n * 100) / 100 : NaN;
};

const isoDate = (v) => {
  if (v === '' || v === null || v === undefined) return '';
  if (typeof v === 'number') {
    // Sheets date serial (days since 1899-12-30)
    return new Date(Date.UTC(1899, 11, 30) + v * 86400000).toISOString().slice(0, 10);
  }
  const s = String(v).trim();
  let m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (m) return `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}`;
  m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})$/);
  if (m) {
    const y = m[3].length === 2 ? '20' + m[3] : m[3];
    return `${y}-${m[1].padStart(2, '0')}-${m[2].padStart(2, '0')}`;
  }
  return 'BAD:' + s;
};

const problems = [];
const vendor = String(r.vendor ?? '').trim();
const invoiceNumber = String(r.invoice_number ?? '').trim();
const total = money(r.total);
const tax = money(r.tax);
const invoiceDate = isoDate(r.invoice_date);
const dueDate = isoDate(r.due_date);

if (!vendor) problems.push('vendor is empty');
if (!invoiceNumber) problems.push('invoice_number is empty');
if (total === null || Number.isNaN(total) || total <= 0) problems.push('total must be a positive number');
if (Number.isNaN(tax)) problems.push('tax must be a number or blank');
if (!invoiceDate || invoiceDate.startsWith('BAD:')) problems.push('invoice_date should look like 2026-09-22');
if (dueDate.startsWith('BAD:')) problems.push('due_date should look like 2026-10-22 or be blank');

return [{
  json: {
    document_id: Number(r.row_id),
    row_id: r.row_id,
    problems,
    fields: {
      vendor_name: vendor,
      invoice_number: invoiceNumber,
      invoice_date: invoiceDate,
      due_date: dueDate,
      total,
      tax,
    },
  },
}];
