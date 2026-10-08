// static/js/direct-upload.js: el PUT firmado no intenta fijar cabeceras que el navegador prohíbe (Host: «Refused to set unsafe header»), pero sí las firmadas (Content-Type, x-goog-content-length-range).
const assert = require('assert');
const set = [];
global.XMLHttpRequest = class { open() {} setRequestHeader(k, v) { set.push(k); } get upload() { return {}; } send() { this.status = 200; setImmediate(() => this.onload()); } };
global.window = {};
global.fetch = async () => ({ ok: true, json: async () => ({ url: 'https://s/x', method: 'PUT', token: 'T', headers: { 'Content-Type': 'text/csv', 'x-goog-content-length-range': '0,10', Host: 'storage.googleapis.com', host: 'x', 'Content-Length': '5' } }) });
require('../../static/js/direct-upload.js');
(async () => {
  const token = await window.DirectUpload.upload({ name: 'a.csv', size: 5, type: 'text/csv' });
  assert.strictEqual(token, 'T');
  assert.deepStrictEqual(set, ['Content-Type', 'x-goog-content-length-range']);
  console.log('direct-upload.js: cabeceras prohibidas filtradas, firmadas enviadas OK');
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
