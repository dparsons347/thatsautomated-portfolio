// Run an n8n Code node file outside n8n for tests: node run_code_node.js <file> '<input json>'
// Provides the three things these nodes use: $input, DateTime (a small stand-in
// for Luxon pinned to 2026-09-29 10:30:00 Central) and Buffer. Prints the output items as JSON.
const fs = require('fs');
const [file, input] = process.argv.slice(2);
const src = fs.readFileSync(file, 'utf8');
const fixed = { yyyyLLdd: '20260929', HHmmss: '103000', 'LLLL d, yyyy': 'September 29, 2026' };
const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const DateTime = {
  now: () => ({ setZone: () => ({ toFormat: (f) => f.split('-').map((p) => fixed[p] ?? p).join('-') }) }),
  fromISO: (d) => ({ toFormat: () => { const [y, m, day] = d.split('-').map(Number); return `${months[m - 1]} ${day}, ${y}`; } }),
};
const $input = { first: () => ({ json: JSON.parse(input) }) };
const run = new Function('$input', 'DateTime', 'Buffer', `return (async () => {\n${src}\n})();`);
run($input, DateTime, Buffer)
  .then((items) => process.stdout.write(JSON.stringify(items)))
  .catch((e) => { process.stdout.write(JSON.stringify({ error: e.message })); });
