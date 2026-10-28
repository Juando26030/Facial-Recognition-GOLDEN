// «Mostrar la configuración de impresión» (por defecto): un DIGITADOR ve y usa el menú; lo local vale solo en este computador y se ignora al esconderlo. Corre el arnés con STATION=show.
const { spawnSync } = require('child_process');
const path = require('path');
const r = spawnSync(process.execPath, [path.resolve(__dirname, 'shared_print_rules_check.js')], { env: Object.assign({}, process.env, { STATION: 'show' }), encoding: 'utf8' });
process.stdout.write(r.stdout || ''); process.stderr.write(r.stderr || '');
process.exit(r.status === 0 && /station_show OK/.test(r.stdout) ? 0 : 1);
