// Puesto configurado desde el servidor y digitador sin acceso a la configuración. Corre el mismo arnés con STATION=1.
const { spawnSync } = require('child_process');
const path = require('path');
const r = spawnSync(process.execPath, [path.resolve(__dirname, 'shared_print_rules_check.js')], { env: Object.assign({}, process.env, { STATION: '1' }), encoding: 'utf8' });
process.stdout.write(r.stdout || ''); process.stderr.write(r.stderr || '');
process.exit(r.status === 0 && /station_config OK/.test(r.stdout) ? 0 : 1);
