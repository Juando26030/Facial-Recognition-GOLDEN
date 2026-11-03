// denied_notice: ver el arnés tests/js/shared_print_rules_check.js (misma ejecución con variables de entorno).
const { spawnSync } = require('child_process');
const path = require('path');
const r = spawnSync(process.execPath, [path.resolve(__dirname, 'shared_print_rules_check.js')], { env: Object.assign({}, process.env, { DENIED: "1" }), encoding: 'utf8' });
process.stdout.write(r.stdout || ''); process.stderr.write(r.stderr || '');
process.exit(r.status === 0 && /denied_notice OK/.test(r.stdout) ? 0 : 1);
