/* Guardado global de «Parámetros del evento» (static/js/params-save.js): orden, fallos parciales, recarga y cambios hechos mientras se guarda. Lógica pura, sin DOM. */
const assert = require('assert');
const { createController } = require('../../static/js/params-save.js');

(async () => {
    const log = [];
    let reloads = 0;
    const states = [];
    const mk = (extra) => createController(Object.assign({ onChange: (s) => states.push(s.state), reload: () => { reloads += 1; } }, extra));

    // 1) Solo corre lo pendiente, en el orden declarado (no el de registro)
    let c = mk();
    c.register({ key: 'fields', label: 'Campos', order: 90, save: async () => { log.push('fields'); } });
    c.register({ key: 'idle', label: 'Inactividad', order: 10, save: async () => { log.push('idle'); } });
    c.register({ key: 'cc', label: 'Facial', order: 20, save: async () => { log.push('cc'); } });
    c.markDirty('fields'); c.markDirty('idle');
    assert.strictEqual(c.hasDirty(), true);
    let r = await c.saveAll();
    assert.deepStrictEqual(log, ['idle', 'fields']);
    assert.deepStrictEqual(r, { saved: ['idle', 'fields'], failed: [] });
    assert.strictEqual(c.hasDirty(), false);
    assert.strictEqual(c.snapshot().state, 'saved');
    assert.ok(states.includes('saving') && states.includes('dirty'));

    // 2) Un fallo no detiene lo demás: lo que salió bien queda limpio y lo fallido sigue pendiente con su motivo
    log.length = 0;
    c = mk();
    c.register({ key: 'a', label: 'A', order: 1, save: async () => { log.push('a'); } });
    c.register({ key: 'b', label: 'B', order: 2, save: async () => { throw new Error('Cédula repetida'); } });
    c.register({ key: 'd', label: 'D', order: 3, save: async () => { log.push('d'); } });
    ['a', 'b', 'd'].forEach((k) => c.markDirty(k));
    r = await c.saveAll();
    assert.deepStrictEqual(log, ['a', 'd']);
    assert.deepStrictEqual(r.saved, ['a', 'd']);
    assert.deepStrictEqual(r.failed, [{ key: 'b', label: 'B', error: 'Cédula repetida' }]);
    assert.deepStrictEqual(c.snapshot().dirty, ['b']);
    assert.strictEqual(c.snapshot().state, 'error');

    // 3) Recarga solo si algo que la pide se guardó y NO hubo fallos
    reloads = 0;
    c = mk();
    c.register({ key: 'logo', label: 'Logo', order: 1, reload: true, save: async () => {} });
    c.register({ key: 'x', label: 'X', order: 2, save: async () => { throw new Error('no'); } });
    c.markDirty('logo'); c.markDirty('x');
    await c.saveAll();
    assert.strictEqual(reloads, 0, 'con un fallo no se recarga (se perderían los datos sin guardar)');
    c = mk();
    c.register({ key: 'logo', label: 'Logo', order: 1, reload: true, save: async () => {} });
    c.markDirty('logo');
    await c.saveAll();
    assert.strictEqual(reloads, 1);
    c = mk();
    c.register({ key: 'p', label: 'P', order: 1, save: async () => {} });
    c.markDirty('p'); c.requestReload();
    await c.saveAll();
    assert.strictEqual(reloads, 2, 'requestReload (logo subido con otros cambios pendientes) recarga tras guardar');

    // 4) Lo editado MIENTRAS se guarda sigue pendiente
    c = mk();
    c.register({ key: 'slow', label: 'Lento', order: 1, save: async () => { c.markDirty('slow'); } });
    c.markDirty('slow');
    await c.saveAll();
    assert.deepStrictEqual(c.snapshot().dirty, ['slow']);
    assert.strictEqual(c.snapshot().state, 'dirty');

    // 5) saveKey (botones ocultos de cada bloque) guarda ese bloque aunque no esté marcado; flush solo si está pendiente
    log.length = 0;
    c = mk();
    c.register({ key: 'ps', label: 'Impresión', order: 1, save: async () => { log.push('ps'); } });
    await c.flush('ps');
    assert.deepStrictEqual(log, []);
    c.markDirty('ps');
    await c.flush('ps');
    assert.deepStrictEqual(log, ['ps']);
    await c.saveKey('ps');
    assert.deepStrictEqual(log, ['ps', 'ps']);

    // 6) Claves desconocidas y reentrada
    c = mk();
    c.markDirty('no-existe');
    assert.strictEqual(c.hasDirty(), false);
    let n = 0;
    c.register({ key: 'k', label: 'K', order: 1, save: () => new Promise((ok) => setTimeout(() => { n += 1; ok(); }, 5)) });
    c.markDirty('k');
    await Promise.all([c.saveAll(), c.saveAll()]);
    assert.strictEqual(n, 1, 'dos clics seguidos no guardan dos veces');

    console.log('params_save_check OK');
})().catch((e) => { console.error(e); process.exit(1); });
