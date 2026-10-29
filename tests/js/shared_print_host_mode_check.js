// host_mode: estado explícito de impresión (usb / dialog / none) y avisos que dependen de él (29-oct-2026); ver el arnés tests/js/shared_print_rules_check.js (variable HOSTMODE).
const { spawnSync } = require('child_process');
const path = require('path');
const r = spawnSync(process.execPath, [path.resolve(__dirname, 'shared_print_rules_check.js')], { env: Object.assign({}, process.env, { HOSTMODE: "1" }), encoding: 'utf8' });
process.stdout.write(r.stdout || ''); process.stderr.write(r.stderr || '');
process.exit(r.status === 0 && /host_mode OK/.test(r.stdout) ? 0 : 1);
