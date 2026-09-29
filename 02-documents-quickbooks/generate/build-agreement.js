// Turn the form submission into a purchase agreement and a DocuSign envelope.
//
// Pasted as-is into the "Build agreement" Code node in n8n. The agreement is
// plain HTML: DocuSign converts it to PDF when the envelope is created, so
// there is no PDF renderer to host. The sign-here and date tabs are placed on
// the anchor strings \s1\ and \d1\, printed in white so the signer never sees
// them.
const j = $input.first().json;
const pick = (key, label) => (j[key] ?? j[label] ?? '');

const company = String(pick('company', 'Customer company')).trim();
const signerName = String(pick('signer_name', 'Signer name')).trim();
const signerEmail = String(pick('signer_email', 'Signer email')).trim();
const site = String(pick('site', 'Job site address')).trim();
const scope = String(pick('scope', 'Scope of work')).trim();
const price = Number(String(pick('price', 'Contract price (USD)')).replace(/[$,\s]/g, ''));
const depositRaw = String(pick('deposit_pct', 'Deposit (%)')).replace(/[%\s]/g, '');
const depositPct = depositRaw === '' ? 30 : Number(depositRaw); // 0 is a real answer, blank means the default
const startDate = String(pick('start_date', 'Start date')).trim();
const finishDate = String(pick('finish_date', 'Completion date')).trim();

const problems = [];
if (!company) problems.push('customer company is empty');
if (!signerName) problems.push('signer name is empty');
if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(signerEmail)) problems.push('signer email does not look like an email');
if (!scope) problems.push('scope of work is empty');
if (!(price > 0)) problems.push('contract price must be more than zero');
if (!(depositPct >= 0 && depositPct <= 100)) problems.push('deposit must be between 0 and 100 percent');
if (startDate && finishDate && finishDate < startDate) problems.push('completion date is before the start date');
if (problems.length) throw new Error('Agreement not sent: ' + problems.join('; '));

const cents = (n) => Math.round(n * 100) / 100;
const deposit = cents(price * depositPct / 100);
const balance = cents(price - deposit);
const money = (n) => n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const niceDate = (d) => (d ? DateTime.fromISO(d).toFormat('LLLL d, yyyy') : 'to be agreed');

const now = DateTime.now().setZone('America/Chicago');
const number = 'PA-' + now.toFormat('yyyyLLdd-HHmmss');

const html = `<!doctype html>
<html><head><meta charset="utf-8"><title>Purchase agreement ${number}</title>
<style>
body { font-family: Helvetica, Arial, sans-serif; font-size: 11pt; color: #222; margin: 36px 48px; line-height: 1.4; }
h1 { font-size: 20pt; margin: 0; }
h2 { font-size: 12pt; margin: 22px 0 6px; border-bottom: 1px solid #ccc; padding-bottom: 3px; }
.sub { color: #666; margin-bottom: 18px; }
table.money { border-collapse: collapse; width: 60%; }
table.money td { padding: 4px 0; }
table.money td.amt { text-align: right; }
table.money tr.total td { border-top: 1px solid #999; font-weight: bold; }
table.sig { width: 100%; margin-top: 36px; }
table.sig td { width: 50%; vertical-align: top; padding-right: 24px; }
.line { border-bottom: 1px solid #333; height: 48px; }
.anchor { color: #ffffff; font-size: 8pt; }
.foot { margin-top: 36px; font-size: 8pt; color: #888; }
</style></head><body>
<h1>Purchase Agreement</h1>
<div class="sub">Agreement ${number} &middot; ${now.toFormat('LLLL d, yyyy')}</div>

<p><b>Contractor:</b> Craig's Design and Landscaping Services, 123 Sierra Way, San Pablo, CA</p>
<p><b>Customer:</b> ${esc(company)}, attention ${esc(signerName)} (${esc(signerEmail)})</p>
<p><b>Job site:</b> ${esc(site || 'As listed on the work order')}</p>

<h2>Scope of work</h2>
<p>${esc(scope).replace(/\n/g, '<br>')}</p>

<h2>Price and payment</h2>
<table class="money">
<tr><td>Contract price</td><td class="amt">$${money(price)}</td></tr>
<tr><td>Deposit due on signing (${depositPct}%)</td><td class="amt">$${money(deposit)}</td></tr>
<tr class="total"><td>Balance due on completion</td><td class="amt">$${money(balance)}</td></tr>
</table>

<h2>Schedule</h2>
<p>Work starts ${niceDate(startDate)} and is expected to be complete by ${niceDate(finishDate)}, weather permitting.</p>

<h2>Terms</h2>
<ol>
<li>Changes to the scope or price are made in writing and signed by both parties.</li>
<li>The balance is due within 15 days of completion.</li>
<li>The customer may cancel in writing within 3 business days of signing for a full refund of the deposit.</li>
<li>The contractor carries general liability insurance and will provide a certificate on request.</li>
</ol>

<table class="sig"><tr>
<td>Customer signature<div class="line"><span class="anchor">\\s1\\</span></div>${esc(signerName)}, ${esc(company)}</td>
<td>Date signed<div class="line"><span class="anchor">\\d1\\</span></div></td>
</tr></table>

<p class="foot">Demonstration document for the That's Automated portfolio. Not a real agreement.</p>
</body></html>`;

const envelope = {
  emailSubject: `Please sign: purchase agreement ${number} (demo)`,
  emailBlurb: `Hi ${signerName}, here is the purchase agreement for ${company}. It takes about a minute to sign.`,
  documents: [{
    documentId: '1',
    name: `Purchase agreement ${number}`,
    fileExtension: 'html',
    documentBase64: Buffer.from(html, 'utf8').toString('base64'),
  }],
  recipients: {
    signers: [{
      recipientId: '1',
      routingOrder: '1',
      name: signerName,
      email: signerEmail,
      tabs: {
        signHereTabs: [{ anchorString: '\\s1\\', anchorUnits: 'pixels', anchorXOffset: '0', anchorYOffset: '-4' }],
        dateSignedTabs: [{ anchorString: '\\d1\\', anchorUnits: 'pixels', anchorXOffset: '0', anchorYOffset: '-4' }],
      },
    }],
  },
  eventNotification: {
    url: 'https://n8n.danielparsons.io/webhook/p2-docusign-events',
    requireAcknowledgment: 'true',
    loggingEnabled: 'true',
    eventData: { version: 'restv2.1', format: 'json', includeData: ['custom_fields', 'recipients'] },
    envelopeEvents: [
      { envelopeEventStatusCode: 'completed' },
      { envelopeEventStatusCode: 'declined' },
      { envelopeEventStatusCode: 'voided' },
    ],
  },
  status: 'sent',
};

return [{
  json: {
    agreement_number: number,
    company,
    signer_name: signerName,
    signer_email: signerEmail,
    site,
    price,
    deposit_pct: depositPct,
    deposit,
    balance,
    price_text: money(price),
    deposit_text: money(deposit),
    start_date: startDate,
    finish_date: finishDate,
    envelope,
  },
}];
