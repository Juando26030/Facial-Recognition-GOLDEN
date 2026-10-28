// Evento SIN impresión compartida: el modo por controlador (barra, impresión, prueba) funciona y no se llama a ninguna ruta compartida. Corre el mismo arnés con SHARED_OFF=1.
const { spawnSync } = require('child_process');
const path = require('path');
const r = spawnSync(process.execPath, [path.resolve(__dirname, 'shared_print_rules_check.js')], { env: Object.assign({}, process.env, { SHARED_OFF: '1', NOWEBUSB: '1' }), encoding: 'utf8' });
process.stdout.write(r.stdout || ''); process.stderr.write(r.stderr || '');
process.exit(r.status === 0 && /shared_print_off OK/.test(r.stdout) ? 0 : 1);
