/* Bandeja de salida del quiosco (docs/16, B8 rebanada R1): las ALTAS hechas sin red («Registrar nuevo», sin foto) se guardan en este dispositivo y se envían al volver la conexión.
   Son datos personales EN CLARO (cédula, nombre, teléfono, correo…), así que la protección va por delante:
   - CIFRADO EN REPOSO con WebCrypto (AES-GCM 256) de cada operación; la clave se genera en el dispositivo como NO EXTRAÍBLE y vive en el mismo IndexedDB. Protege contra copiar el archivo del perfil o un
     respaldo del equipo; NO contra quien controle el navegador abierto (límite real: la clave está en el mismo origen que los datos; iOS no da llavero a la web).
   - BORRADO TRAS SINCRONIZAR: apenas el servidor confirma (`ok`/`replayed`) se borran los campos (queda solo el nombre para mostrar y el resultado, 24 h, y se limpian solos).
   - CADUCIDAD DE 7 DÍAS para lo que NO se envió (pendiente, con error, en revisión): avisos visibles desde el día 3 (amarillo) y el 6 (rojo); a los 7 días lo no enviado se ELIMINA solo del dispositivo (texto C''' de la auditora: «se suprime de manera automática»), con un aviso visible que la persona debe ver (nunca en silencio);
     NUNCA se borra en silencio: solo la persona, con confirmación («Descartar»), o el servidor al confirmar la recepción. Cerrar sesión no la borra (se avisa, como la cola de ingresos).
   Estados: pendiente → ok | revision (la cédula YA existía: no se pisó; se registró para este evento) | duplicado (ya estaba registrada) | error (con motivo) | caducada.
   Cada operación lleva un `op_id` (UUID): reenviar nunca duplica (el servidor responde `replayed`). La foto, el consentimiento biométrico y la edición de personas existentes NO van en R1. */
(function (root) {
  const DAY_MS = 24 * 3600 * 1000, TTL_DAYS = 7, WARN_DAY = 3, URGENT_DAY = 6, OK_KEEP_MS = DAY_MS, BATCH = 50;
  const UNSENT = ['pendiente', 'error', 'revision', 'duplicado'];                 // lo que todavía necesita a una persona o un envío (caduca)

  const req = (r) => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error || new Error('idb')); });
  const done = (tx) => new Promise((res, rej) => { tx.oncomplete = () => res(); tx.onerror = () => rej(tx.error || new Error('idb')); tx.onabort = () => rej(tx.error || new Error('idb abort')); });

  function openStore(idb, name) {
    return new Promise((resolve, reject) => {
      const r = idb.open(name, 1);
      r.onupgradeneeded = () => { const db = r.result; if (!db.objectStoreNames.contains('ops')) db.createObjectStore('ops', { keyPath: 'op_id' }); if (!db.objectStoreNames.contains('meta')) db.createObjectStore('meta', { keyPath: 'k' }); };
      r.onsuccess = () => {
        const db = r.result;
        resolve({
          get: async (store, key) => req(db.transaction([store], 'readonly').objectStore(store).get(key)),
          getAll: async (store) => req(db.transaction([store], 'readonly').objectStore(store).getAll()),
          put: async (store, value) => { const t = db.transaction([store], 'readwrite'); t.objectStore(store).put(value); return done(t); },
          del: async (store, key) => { const t = db.transaction([store], 'readwrite'); t.objectStore(store).delete(key); return done(t); },
          close: () => db.close(),
        });
      };
      r.onerror = () => reject(r.error || new Error('idb open'));
      r.onblocked = () => reject(new Error('idb blocked'));
    });
  }

  /* Textos y niveles (puros, probados en Node). */
  function effectiveStatus(rec, now) { return now > rec.expires_at && UNSENT.includes(rec.status) ? 'caducada' : rec.status; }
  function levelOf(daysOld, status) {
    if (status === 'caducada') return 'expired';
    if (!UNSENT.includes(status)) return 'ok';
    return daysOld >= URGENT_DAY ? 'urgent' : (daysOld >= WARN_DAY ? 'warn' : 'ok');
  }
  function bannerText(stats) {
    if (!stats.unsent && !stats.expired && !stats.pruned) return '';
    const parts = [];
    if (stats.pruned) parts.push(`${stats.pruned} ${stats.pruned === 1 ? 'persona nueva llevaba' : 'personas nuevas llevaban'} ${TTL_DAYS} días sin enviarse y se eliminaron de este dispositivo, como indica la política de privacidad: vuelve a registrarlas`);
    if (stats.expired) parts.push(`${stats.expired} ${stats.expired === 1 ? 'persona nueva CADUCÓ' : 'personas nuevas CADUCARON'} sin enviarse (pasaron ${TTL_DAYS} días): no se envían solas; revísalas en la bandeja`);
    if (stats.unsent) {
      const left = Math.max(0, Math.ceil(stats.min_days_left));
      parts.push(`${stats.unsent} ${stats.unsent === 1 ? 'persona nueva sin enviar' : 'personas nuevas sin enviar'} (la más antigua, hace ${Math.floor(stats.oldest_days)} ${Math.floor(stats.oldest_days) === 1 ? 'día' : 'días'}; caduca${stats.unsent === 1 ? '' : 'n'} en ${left} ${left === 1 ? 'día' : 'días'})`);
    }
    return parts.join(' · ');
  }
  function statusLabel(st) {
    return { pendiente: 'Pendiente de envío', ok: 'Enviada', revision: 'Revisar: la cédula ya existía', duplicado: 'Ya estaba registrada', error: 'Error', caducada: 'Caducada (sin enviar)' }[st] || st;
  }

  function create(deps) {
    const d = Object.assign({
      idb: root.indexedDB, subtle: root.crypto && root.crypto.subtle, random: (n) => root.crypto.getRandomValues(new Uint8Array(n)), now: () => Date.now(),
      fetch: root.fetch ? root.fetch.bind(root) : undefined, eventId: root.EVENT_ID, uuid: () => (root.crypto && root.crypto.randomUUID ? root.crypto.randomUUID() : null),
    }, deps || {});
    const o = { db: null, key: null, supported: false, listeners: [], lastError: null };
    const emit = () => o.listeners.forEach((f) => { try { f(); } catch (e) { /* un oyente roto no frena a los demás */ } });
    o.onChange = (f) => o.listeners.push(f);
    o.isSupported = () => !!(d.idb && d.subtle && d.fetch && d.eventId);

    o.init = async () => {
      if (!o.isSupported()) { o.lastError = 'unsupported'; return o; }
      try {
        o.db = await openStore(d.idb, `golden-outbox-${d.eventId}`);
        const stored = await o.db.get('meta', 'key');
        if (stored && stored.key) o.key = stored.key;
        else { o.key = await d.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']); await o.db.put('meta', { k: 'key', key: o.key }); }   // extractable: false
        o.supported = true;
        await o.purge();
      } catch (e) { o.lastError = 'unsupported'; o.supported = false; }
      return o;
    };

    const enc = async (obj) => {
      const iv = d.random(12);
      const ct = await d.subtle.encrypt({ name: 'AES-GCM', iv }, o.key, new TextEncoder().encode(JSON.stringify(obj)));
      return { iv, ct: new Uint8Array(ct) };
    };
    const dec = async (blob) => JSON.parse(new TextDecoder().decode(await d.subtle.decrypt({ name: 'AES-GCM', iv: blob.iv }, o.key, blob.ct)));

    /* Encola un alta (`fields` = lo que iría a POST /register, SIN foto). `label` = nombre para mostrar. */
    o.enqueue = async (fields, label, opts) => {
      if (!o.supported) throw new Error('Este dispositivo no puede guardar la bandeja de salida (falta IndexedDB o WebCrypto)');
      const now = d.now();
      const rec = { op_id: d.uuid() || `o${now}${Math.random().toString(16).slice(2)}`, event_id: d.eventId, type: (opts && opts.type) || 'create_person', status: 'pendiente', created_at: now, expires_at: now + TTL_DAYS * DAY_MS, attempts: 0, result: null, blob: await enc({ fields, label }) };
      if (opts && opts.form_version != null) { rec.form_version = opts.form_version; if (opts.form_sig) rec.form_sig = opts.form_sig; }       // formulario de persona: con qué copia del formulario se hizo (no es un dato personal)
      await o.db.put('ops', rec);
      emit();
      return { op_id: rec.op_id };
    };

    /* PETICIONES GUARDADAS (25-nov-2026, registro completo sin conexión, docs/28): lo que la pantalla le habría pedido al servidor (editar, cambiar cédula, estado, firmas, inventario…)
       se guarda tal cual (método, ruta y cuerpo), cifrado como todo lo demás, y al volver la red se REPITE en el mismo orden contra las mismas rutas de siempre: el servidor aplica
       exactamente sus reglas de en línea y no hay rutas nuevas ni carga extra. `opts` es lo que se le pasaría a fetch (body: texto JSON o FormData; los archivos van en base64). */
    const b64 = (buf) => { const u = new Uint8Array(buf); let t = ''; for (let i = 0; i < u.length; i += 0x8000) t += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000)); return btoa(t); };
    const unb64 = (t) => { const bin = atob(t), u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return u; };
    o.enqueueHttp = async (url, opts, label) => {
      const spec = { method: String((opts && opts.method) || 'GET').toUpperCase(), url: String(url) };
      const body = opts && opts.body;
      if (opts && Array.isArray(opts.expect)) spec.expect = opts.expect;          // respuestas 200 que traen `result`: solo estos valores cuentan como hecho
      if (typeof body === 'string') spec.json = body;
      else if (body && typeof body.entries === 'function') {
        spec.form = [];
        for (const [k, v] of body.entries()) spec.form.push(typeof v === 'string' ? [k, v] : [k, { b64: b64(await v.arrayBuffer()), type: v.type || 'application/octet-stream', name: v.name || 'archivo' }]);
      }
      return o.enqueue(spec, label, { type: 'http' });
    };
    const sendHttp = async (rec, summary) => {
      const { fields: spec, label } = await dec(rec.blob);
      const init = { method: spec.method, headers: { 'X-Op-Id': rec.op_id } };
      if (spec.json != null) { init.headers['Content-Type'] = 'application/json'; init.body = spec.json; }
      else if (spec.form) { const fd = new FormData(); spec.form.forEach(([k, v]) => { if (typeof v === 'string') fd.append(k, v); else fd.append(k, new Blob([unb64(v.b64)], { type: v.type }), v.name); }); init.body = fd; }
      let res;
      try { res = await d.fetch(spec.url, init); } catch (e) { summary.stopped = 'red'; return; }
      if (res.status === 401) { summary.stopped = 'sesion'; return; }
      if (res.status >= 500 || res.status === 429) { summary.stopped = 'servidor'; return; }
      summary.sent++;
      if (res.ok && spec.expect) {                                          // p. ej. un movimiento de zona que el servidor contestó «ya había entrado»: no quedó hecho
        let body = null; try { body = await res.json(); } catch (e) { body = null; }
        if (!body || !spec.expect.includes(body.result)) { await o.db.put('ops', { ...rec, status: 'error', result: String((body && (body.details || body.detail)) || 'El servidor no aplicó el cambio'), attempts: rec.attempts + 1 }); summary.error++; return; }
      }
      if (res.ok) { await o.db.put('ops', { ...rec, status: 'ok', result: null, expires_at: d.now() + OK_KEEP_MS, blob: await enc({ fields: null, label }) }); summary.ok++; return; }
      let detail = '';
      try { const data = await res.json(); detail = data && data.detail && typeof data.detail === 'object' ? (data.detail.message || '') : ((data && data.detail) || ''); } catch (e) { /* sin detalle */ }
      await o.db.put('ops', { ...rec, status: 'error', result: String(detail || `El servidor no aceptó el cambio (${res.status})`), attempts: rec.attempts + 1 }); summary.error++;
    };

    /* Lista descifrada para la pantalla de la bandeja (nunca incluye la cédula: solo el nombre para mostrar y el resultado). */
    o.list = async () => {
      if (!o.supported) return [];
      const now = d.now(), out = [];
      for (const rec of await o.db.getAll('ops')) {
        let label = '';
        try { label = (await dec(rec.blob)).label || ''; } catch (e) { label = '(no se pudo descifrar)'; }
        const status = effectiveStatus(rec, now), days = (now - rec.created_at) / DAY_MS;
        out.push({ op_id: rec.op_id, status, base_status: rec.status, label, detail: rec.result, created_at: rec.created_at, expires_at: rec.expires_at, days_old: days, days_left: (rec.expires_at - now) / DAY_MS, level: levelOf(days, status), attempts: rec.attempts });
      }
      return out.sort((a, b) => a.created_at - b.created_at);
    };

    o.stats = async () => {
      if (o.supported) await o.purge();
      const items = await o.list();
      const unsent = items.filter((i) => UNSENT.includes(i.status)), expired = items.filter((i) => i.status === 'caducada');
      const pend = items.filter((i) => i.status === 'pendiente'), needs = items.filter((i) => ['error', 'revision', 'duplicado'].includes(i.status));
      const all = [...unsent, ...expired], oldest = all.length ? Math.max(...all.map((i) => i.days_old)) : 0, minLeft = unsent.length ? Math.min(...unsent.map((i) => i.days_left)) : 0;
      const pruned = await o.prunedCount();
      const level = pruned ? 'expired' : (all.length ? (expired.length ? 'expired' : (oldest >= URGENT_DAY ? 'urgent' : (oldest >= WARN_DAY ? 'warn' : 'ok'))) : 'ok');
      const s = { pruned, total: items.length, pending: pend.length, needs_attention: needs.length, expired: expired.length, unsent: unsent.length, oldest_days: oldest, min_days_left: minLeft, level };
      s.banner = bannerText(s);
      return s;
    };

    /* Envía lo pendiente (no caducado, salvo `force`) por lotes. Con cualquier fallo de red o de sesión se detiene SIN perder nada (queda pendiente y se reintenta). */
    o.sync = async ({ force = false } = {}) => {
      if (!o.supported) return { sent: 0 };
      const now = d.now(), summary = { sent: 0, ok: 0, revision: 0, duplicado: 0, error: 0, stopped: null };
      const recs = (await o.db.getAll('ops')).filter((r) => r.status === 'pendiente' && (force || now <= r.expires_at)).sort((a, b) => a.created_at - b.created_at);          // en el orden en que se hicieron
      for (let i = 0; i < recs.length && !summary.stopped;) {
        if (recs[i].type === 'http') { await sendHttp(recs[i], summary); if (!summary.stopped) i++; continue; }
        const chunk = [], ops = [];
        while (i < recs.length && recs[i].type !== 'http' && chunk.length < BATCH) chunk.push(recs[i++]);
        for (const rec of chunk) { const { fields } = await dec(rec.blob); ops.push({ op_id: rec.op_id, type: rec.type, timestamp: new Date(rec.created_at).toISOString(), fields, ...(rec.form_version != null ? { form_version: rec.form_version, ...(rec.form_sig ? { form_sig: rec.form_sig } : {}) } : {}) }); }
        let res;
        try { res = await d.fetch(`/api/events/${d.eventId}/outbox/sync`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ops }) }); } catch (e) { summary.stopped = 'red'; break; }
        if (res.status === 401 || res.status === 403) { summary.stopped = 'sesion'; break; }
        if (!res.ok) { summary.stopped = 'servidor'; break; }
        const data = await res.json();
        const byId = new Map((data.results || []).map((r) => [r.op_id, r]));
        for (const rec of chunk) {
          const r = byId.get(rec.op_id); if (!r) continue;
          summary.sent++;
          if (r.warnings && r.warnings.length) (summary.warnings = summary.warnings || []).push(...r.warnings);          // copia anterior del formulario: se guardó, con avisos
          if (r.result === 'ok' || r.result === 'replayed') {
            const { label } = await dec(rec.blob);
            await o.db.put('ops', { ...rec, status: 'ok', result: null, expires_at: d.now() + OK_KEEP_MS, blob: await enc({ fields: null, label }) });       // borrado tras sincronizar: fuera los campos
            summary.ok++;
          } else if (r.result === 'existente') { await o.db.put('ops', { ...rec, status: 'revision', result: r.existing_name || '' }); summary.revision++; }
          else if (r.result === 'duplicado') { await o.db.put('ops', { ...rec, status: 'duplicado', result: r.existing_name || '' }); summary.duplicado++; }
          else { await o.db.put('ops', { ...rec, status: 'error', result: r.detail || 'Error', attempts: rec.attempts + 1 }); summary.error++; }
        }
      }
      if (summary.stopped) o.lastError = summary.stopped; else o.lastError = null;
      emit();
      return summary;
    };

    o.retry = async (opId) => { const rec = await o.db.get('ops', opId); if (rec && rec.status === 'error') { await o.db.put('ops', { ...rec, status: 'pendiente', result: null }); emit(); } };
    /* Descartar es SIEMPRE una acción de la persona (la pantalla pide confirmación): nada se borra en silencio. */
    o.discard = async (opId) => { await o.db.del('ops', opId); emit(); };
    /* Lo ya ENTREGADO (`ok`) se limpia solo a las 24 h (ya no lleva datos personales). Lo NO entregado se ELIMINA a los 7 días (política v1.1, texto C'''), dejando un aviso persistente hasta que la persona abra la bandeja. */
    o.purge = async () => {
      const now = d.now(); let gone = 0;
      for (const rec of await o.db.getAll('ops')) {
        if (now <= rec.expires_at) continue;
        if (rec.status === 'ok') await o.db.del('ops', rec.op_id);
        else if (UNSENT.includes(rec.status)) { await o.db.del('ops', rec.op_id); gone++; }
      }
      if (gone) { const prev = await o.db.get('meta', 'pruned'); await o.db.put('meta', { k: 'pruned', n: (prev ? prev.n : 0) + gone, at: now }); emit(); }
      return gone;
    };
    o.prunedCount = async () => { const m = o.supported ? await o.db.get('meta', 'pruned') : null; return m ? m.n : 0; };
    o.dismissPruned = async () => { if (o.supported) { await o.db.del('meta', 'pruned'); emit(); } };
    o.countUnsent = async () => (o.supported ? (await o.db.getAll('ops')).filter((r) => UNSENT.includes(r.status)).length : 0);
    o.stop = () => { if (o.db) { o.db.close(); o.db = null; } };
    return o;
  }

  /* gwFetch (docs/28): un `fetch` que SIN RED guarda la petición en la bandeja de salida y responde «aceptado» (202) para que la pantalla siga igual que con conexión; con red es el fetch de
     siempre. Solo para cambios (nunca GET). `fake` = lo que la pantalla leería de la respuesta. Sin bandeja disponible, falla como un fetch sin red. */
  function offlineNow() { const gc = root.GoldenContingency && root.GoldenContingency.instance; return !!(gc && gc.active && gc.active()); }
  function fakeResponse(data) { const r = { ok: true, status: 202, queued: true, headers: { get: () => null }, json: async () => data || {}, text: async () => JSON.stringify(data || {}), clone: () => r }; return r; }
  async function gwFetch(url, opts, label, fake) {
    const box = root.GoldenOutbox && root.GoldenOutbox.instance;
    const method = String((opts && opts.method) || 'GET').toUpperCase();
    if (method === 'GET' || !offlineNow() || !box || !box.supported) return root.fetch(url, opts);
    await box.enqueueHttp(url, opts, label || 'Cambio hecho sin conexión');
    return fakeResponse(fake);
  }
  if (typeof window !== 'undefined') { root.gwFetch = gwFetch; root.gwOffline = offlineNow; }

  const api = { create, effectiveStatus, levelOf, bannerText, statusLabel, TTL_DAYS, WARN_DAY, URGENT_DAY };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GoldenOutbox = Object.assign(api, { instance: null, async init(opts) { this.instance = create(opts); return this.instance.init(); } });
})(typeof window !== 'undefined' ? window : globalThis);
