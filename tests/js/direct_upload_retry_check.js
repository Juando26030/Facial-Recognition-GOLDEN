// static/js/direct-upload.js (hotfix 21-nov-2026): si el PUT se corta («error de red» en el celular) se reintenta solo con una URL NUEVA; un archivo que el celular ya no deja
// leer da un mensaje claro (no «error de red»); un 4xx de la firma (tamaño, formato) no se reintenta.
const assert = require('assert');
let puts = 0, signs = 0, failPuts = 2;
global.setTimeout = (fn) => setImmediate(fn);                 // sin esperas reales
global.XMLHttpRequest = class { open() {} setRequestHeader() {} get upload() { return {}; }
  send() { puts++; setImmediate(() => { if (puts <= failPuts) this.onerror(); else { this.status = 200; this.onload(); } }); } };
global.window = {};
let signStatus = 200;
global.fetch = async () => { signs++; return { ok: signStatus === 200, status: signStatus, json: async () => (signStatus === 200 ? { url: 'https://s/x', token: 'T' + signs, headers: {} } : { detail: 'El archivo pesa más de 10 MB' }) }; };
require('../../static/js/direct-upload.js');
const D = window.DirectUpload;
(async () => {
  // 1) dos cortes de red y luego sube: token de la ÚLTIMA firma
  assert.strictEqual(await D.upload(new Blob(['abc'], { type: 'application/pdf' })), 'T3');
  assert.strictEqual(puts, 3); assert.strictEqual(signs, 3);
  // 2) siempre se corta: mensaje claro, 4 intentos
  puts = 0; signs = 0; failPuts = 99;
  await assert.rejects(D.upload(new Blob(['abc'])), /se cortó la conexión/);
  assert.strictEqual(puts, 4);
  // 3) archivo que ya no se puede leer
  const broken = { name: 'arl.pdf', size: 3, type: 'application/pdf', arrayBuffer: () => Promise.reject(new Error('NotReadableError')) };
  await assert.rejects(D.upload(broken), /No se pudo leer el archivo «arl.pdf»/);
  // 4) error de la firma (tamaño): sin reintentos
  signs = 0; signStatus = 400;
  await assert.rejects(D.upload(new Blob(['abc'])), /pesa más de 10 MB/);
  assert.strictEqual(signs, 1);
  // 5) la copia en memoria se hace una sola vez y se reutiliza
  const f = new Blob(['xyz']); const c1 = await D._readCopy(f); const c2 = await D._readCopy(f);
  assert.ok(c1 === c2 && c1 !== f && c1.size === 3);
  console.log('direct-upload.js: reintentos, archivo ilegible y copia en memoria OK');
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
