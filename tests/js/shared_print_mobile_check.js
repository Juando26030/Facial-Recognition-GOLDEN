// Celular y tablet: la barra nunca habla de «controlador de Windows» ni de «cuadro de diálogo». Corre el mismo arnés con MOBILE=1 (navegador Android).
const { spawnSync } = require('child_process');
const path = require('path');
const r = spawnSync(process.execPath, [path.resolve(__dirname, 'shared_print_rules_check.js')], { env: Object.assign({}, process.env, { MOBILE: '1' }), encoding: 'utf8' });
process.stdout.write(r.stdout || ''); process.stderr.write(r.stderr || '');
process.exit(r.status === 0 && /mobile_bar OK/.test(r.stdout) ? 0 : 1);
