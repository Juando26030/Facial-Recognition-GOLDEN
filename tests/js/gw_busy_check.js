// Prueba de GW.busy (rueda y bloqueo de doble clic en botones que trabajan). Node puro, sin DOM real.
const assert = require('assert');
const { busy } = require('../../static/js/gw-busy.js');

function fakeBtn(text) {
    const attrs = {};
    return { children: [], textContent: text, setAttribute(k, v) { attrs[k] = String(v); }, removeAttribute(k) { delete attrs[k]; }, hasAttribute(k) { return k in attrs; }, attrs };
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
    // 1) aria-busy mientras trabaja y limpio al terminar; devuelve el valor
    let b = fakeBtn('Guardar'); let release;
    let p = busy(b, () => new Promise((r) => { release = r; }));
    assert.strictEqual(b.attrs['aria-busy'], 'true', 'ocupado mientras trabaja');
    release(42);
    assert.strictEqual(await p, 42, 'devuelve lo que devuelve el trabajo');
    assert.ok(!('aria-busy' in b.attrs), 'limpio al terminar');

    // 2) doble clic: el trabajo corre UNA sola vez
    b = fakeBtn('Guardar'); let runs = 0;
    const work = () => { runs++; return sleep(20); };
    const p1 = busy(b, work), p2 = busy(b, work);
    assert.strictEqual(p1, p2, 'la misma promesa');
    await p1; assert.strictEqual(runs, 1, 'una sola petición');
    await busy(b, work); assert.strictEqual(runs, 2, 'después de terminar se puede volver a usar');

    // 3) error: se limpia y se vuelve a lanzar
    b = fakeBtn('Guardar');
    await assert.rejects(busy(b, () => Promise.reject(new Error('falló'))), /falló/);
    assert.ok(!('aria-busy' in b.attrs), 'limpio también si falla');
    await assert.rejects(busy(b, () => { throw new Error('síncrono'); }), /síncrono/);
    assert.ok(!('aria-busy' in b.attrs));

    // 4) lento: cambia el texto y lo devuelve
    b = fakeBtn('Guardar cambios');
    p = busy(b, () => sleep(60), { slowMs: 20 });
    await sleep(35); assert.strictEqual(b.textContent, 'Sigue trabajando…'); assert.ok('data-gw-slow' in b.attrs);
    await p; assert.strictEqual(b.textContent, 'Guardar cambios'); assert.ok(!('data-gw-slow' in b.attrs));

    // 5) botón con íconos (no solo texto): no se toca el contenido
    b = fakeBtn('x'); b.children = [{}];
    p = busy(b, () => sleep(40), { slowMs: 10 }); await sleep(25); assert.strictEqual(b.textContent, 'x'); await p;

    // 6) sin botón: corre igual
    assert.strictEqual(await busy(null, () => 7), 7);
    console.log('gw-busy.js: rueda, doble clic, error y lento OK');
})().catch((e) => { console.error(e); process.exit(1); });
