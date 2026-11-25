/* Modo contingencia del quiosco (Fase 3, docs/13 §9), cliente. Sin dependencias: solo IndexedDB (y crypto.subtle para la huella). Piezas:

   - Almacén (IndexedDB `golden-contingency-<evento>`): `roster` (huella → {h, n, c, s}), `queue` (ingresos hechos sin red: client_id, HUELLA h, nombre, marca de tiempo y método;
     NUNCA la cédula en claro), `review` (lo que el servidor marcó para revisar o no pudo registrar, hasta que el operador lo vea) y `meta` (versión, `expires_at`, sal).
   - Máquina de estados (normal / degradado / contingencia): chequeo de `/health` (3 s) cada 5 s; entra en contingencia tras 2 fallos seguidos o tras 2 escaneos consecutivos que
     agotaron sus reintentos; un fallo aislado solo deja «degradado»; sale tras 2 chequeos buenos seguidos Y una petición autenticada buena (`/api/ping-auth`; un 429 = servidor alcanzable).
     Con la sesión vencida (401) sigue en contingencia, la cola intacta y la franja pide iniciar sesión de nuevo.
   - Sincronización de la cola: lotes de hasta 500 a `/api/events/{id}/access-logs/sync` con espera creciente si falla; lo sincronizado se borra; los marcados «review» o desconocidos
     pasan a la lista de «revisar». Lo no sincronizado a los 7 días se elimina del dispositivo (política v1.1, texto C''' de la auditora) con aviso visible desde el día 3 (amarillo) y el 6 (rojo).
   - Franja visible con `aria-live="polite"` y registro sin red (`scanLocal` + `enqueue`; directory.js pone los avisos). Si falta IndexedDB o crypto.subtle, `start()` avisa y deja el modo normal.
   Retención: el roster dura hasta que el evento finalice (403/409 → se borra, con aviso) y como máximo 24 h desde el último refresco (`expires_at`); se borra al cerrar sesión (static/js/toast.js);
   la cola se conserva hasta sincronizar. */
(function (root) {
  const HEALTH_MS = 5000, HEALTH_TIMEOUT_MS = 3000, REFRESH_MS = 4 * 60 * 1000, PROBE_BACKOFF_MS = 30000;
  const FAILS_TO_ENTER = 2, EXHAUSTED_TO_ENTER = 2, OKS_TO_LEAVE = 2;
  const SYNC_BATCH = 500, SYNC_BACKOFF_BASE_MS = 5000, SYNC_BACKOFF_MAX_MS = 5 * 60 * 1000, DAY_MS = 24 * 3600 * 1000, QUEUE_MAX_AGE_MS = 7 * DAY_MS, WARN_AGE_MS = 3 * DAY_MS, URGENT_AGE_MS = 6 * DAY_MS;
  const normalize = (v) => String(v == null ? '' : v).replace(/[\s.]/g, '');      // igual que roster_normalize (app/routers/api.py)

  /* ------------------------------------------------------------------------------------------------------------------ máquina de estados (pura) */
  function createMachine(onChange) {
    const m = { state: 'normal', healthFails: 0, healthOks: 0, exhausted: 0 };
    const set = (s) => { if (m.state !== s) { const from = m.state; m.state = s; if (s === 'contingency') { m.healthOks = 0; } if (onChange) onChange(s, from); } };
    m.health = (ok) => {
      if (ok) {
        m.healthFails = 0;
        if (m.state === 'contingency') m.healthOks++;
        else if (m.state === 'degraded' && m.exhausted === 0) set('normal');
      } else {
        m.healthOks = 0; m.healthFails++;
        if (m.healthFails >= FAILS_TO_ENTER) set('contingency'); else if (m.state === 'normal') set('degraded');
      }
    };
    m.scanExhausted = () => {                 // un escaneo agotó sus reintentos de red
      m.exhausted++;
      if (m.exhausted >= EXHAUSTED_TO_ENTER) set('contingency'); else if (m.state === 'normal') set('degraded');
    };
    m.authGood = () => {                      // una petición autenticada buena (escaneo, sonda de salida, refresco, sincronización)
      m.exhausted = 0;
      if (m.state === 'contingency') {
        if (m.healthOks >= OKS_TO_LEAVE) { m.healthFails = 0; m.healthOks = 0; set('normal'); }
      } else { m.healthFails = 0; set('normal'); }
    };
    m.readyToProbe = () => m.state === 'contingency' && m.healthOks >= OKS_TO_LEAVE;
    return m;
  }

  /* ------------------------------------------------------------------------------------------------------------------ almacén IndexedDB */
  const req = (r) => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error || new Error('idb')); });
  const done = (tx) => new Promise((res, rej) => { tx.oncomplete = () => res(); tx.onerror = () => rej(tx.error || new Error('idb')); tx.onabort = () => rej(tx.error || new Error('idb abort')); });
  const STORES = { roster: 'h', queue: 'client_id', meta: 'k', review: 'client_id', consents: 'id', keys: 'k', people: 'k', cache: 'k' };
  const PEOPLE_CHUNK = 400;                    // personas por bloque cifrado de la copia completa

  function openStore(idb, name) {
    return new Promise((resolve, reject) => {
      const r = idb.open(name, 6);
      r.onupgradeneeded = () => {
        const db = r.result;
        Object.keys(STORES).forEach((s) => { if (!db.objectStoreNames.contains(s)) db.createObjectStore(s, { keyPath: STORES[s] }); });
      };
      r.onsuccess = () => {
        const db = r.result;
        const tx = (stores, mode) => db.transaction(stores, mode);
        resolve({
          get: async (store, key) => req(tx([store], 'readonly').objectStore(store).get(key)),
          getAll: async (store) => req(tx([store], 'readonly').objectStore(store).getAll()),
          put: async (store, value) => { const t = tx([store], 'readwrite'); t.objectStore(store).put(value); return done(t); },
          del: async (store, keys) => { const t = tx([store], 'readwrite'); [].concat(keys).forEach((k) => t.objectStore(store).delete(k)); return done(t); },
          clear: async (stores) => { const t = tx(stores, 'readwrite'); stores.forEach((s) => t.objectStore(s).clear()); return done(t); },
          putMany: async (store, values) => { const t = tx([store], 'readwrite'); const os = t.objectStore(store); values.forEach((v) => os.put(v)); return done(t); },
          replaceRoster: async (people, meta) => {                   // todo o nada: una transacción
            const t = tx(['roster', 'meta'], 'readwrite');
            const rs = t.objectStore('roster'); rs.clear(); people.forEach((p) => rs.put(p)); t.objectStore('meta').put({ k: 'roster', ...meta });
            return done(t);
          },
          close: () => db.close(),
        });
      };
      r.onerror = () => reject(r.error || new Error('idb open'));
      r.onblocked = () => reject(new Error('idb blocked'));
    });
  }

  /* ------------------------------------------------------------------------------------------------------------------ controlador */
  function create(deps) {
    const bound = (name) => (typeof root[name] === 'function' ? root[name].bind(root) : undefined);       // sin `bind`, el navegador lanza «Illegal invocation» al llamarlas como d.setInterval(...)
    const d = Object.assign({ idb: root.indexedDB, fetch: bound('fetch'), now: () => Date.now(), setInterval: bound('setInterval'), clearInterval: bound('clearInterval'),
      storage: root.navigator && root.navigator.storage, setTimeout: bound('setTimeout'), clearTimeout: bound('clearTimeout'), document: root.document, subtle: root.crypto && root.crypto.subtle, eventId: root.EVENT_ID, uuid: null }, deps || {});
    const c = { machine: null, db: null, supported: false, banner: null, bannerSig: '', queueSize: 0, reviewCount: 0, probeAfter: 0, timers: [], listeners: [], lastError: null,
      sessionExpired: false, notice: null, syncing: false, syncFails: 0, nextSyncAt: 0, eventFinished: false };
    const uuid = () => d.uuid ? d.uuid() : (root.crypto && root.crypto.randomUUID ? root.crypto.randomUUID() : `c${d.now()}${Math.random().toString(16).slice(2)}`);

    /* Almacenamiento persistente: el navegador no borra IndexedDB «por falta de espacio» (Safari además la borra tras 7 días sin uso del sitio; Chrome/Edge pueden concederlo solos). Se pide al arrancar,
       SIN esperar ni depender de la respuesta: si se niega o no existe la API, todo sigue igual (`c.persistent`: true / false / null = sin API). */
    c.persistent = null;
    c.requestPersistence = async () => {
      const st = d.storage;
      if (!st || typeof st.persist !== 'function') return null;
      try { c.persistent = (typeof st.persisted === 'function' && await st.persisted()) || await st.persist(); } catch (e) { c.persistent = false; }
      c.persistent = !!c.persistent;
      return c.persistent;
    };

    c.ready = new Promise((resolve) => { c.markReady = resolve; });       // se resuelve cuando start() termina (con o sin soporte): directory.js lo espera antes de usar la copia local
    c.isSupported = () => !!(d.idb && d.subtle && d.fetch);
    c.active = () => !!(c.supported && c.machine && c.machine.state === 'contingency');
    c.state = () => (c.machine ? c.machine.state : 'normal');
    c.onChange = (f) => c.listeners.push(f);
    c.syncListeners = [];
    c.onSynced = (f) => c.syncListeners.push(f);                                  // se llama al vaciar la cola con (cuántos se sincronizaron)

    /* --- huella de la cédula (igual que roster_fingerprint del servidor) --- */
    c.fingerprint = async (salt, cedula) => {
      const bytes = new TextEncoder().encode(`${salt}:${normalize(cedula)}`);
      const hash = new Uint8Array(await d.subtle.digest('SHA-256', bytes));
      return Array.from(hash.slice(0, 8)).map((b) => b.toString(16).padStart(2, '0')).join('');
    };

    /* --- cifrado en reposo de lo que se guarda SIN conexión (cola de ingresos, decisiones de autorización y lista de «revisar»): AES-GCM 256 con una clave NO extraíble generada en este dispositivo
       (misma técnica que la bandeja de salida, static/js/outbox.js). En claro solo quedan lo que no identifica a nadie (client_id/id y marca de tiempo); huella, nombre, método y decisión van cifrados.
       La clave vive en su propio almacén (`keys`): sobrevive al borrado de la lista local, que no debe dejar la cola ilegible. Registros viejos en claro se cifran al arrancar. */
    const SECRET = { queue: ['h', 'n', 'method', 'prev'], consents: ['h', 'decision', 'adult', 'text_hash', 'version', 'device'], review: ['n', 'reason'] };
    const randomIv = () => (d.random ? d.random(12) : root.crypto.getRandomValues(new Uint8Array(12)));
    c.qkey = null;
    const getKey = async () => {
      if (c.qkey) return c.qkey;
      const stored = await c.db.get('keys', 'q');
      if (stored && stored.key) { c.qkey = stored.key; return c.qkey; }
      c.qkey = await d.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);      // extractable: false
      await c.db.put('keys', { k: 'q', key: c.qkey });
      return c.qkey;
    };
    const seal = async (store, rec) => {
      const secret = {}, open = {};
      Object.keys(rec).forEach((k) => { (SECRET[store].includes(k) ? secret : open)[k] = rec[k]; });
      const iv = randomIv();
      const ct = await d.subtle.encrypt({ name: 'AES-GCM', iv }, await getKey(), new TextEncoder().encode(JSON.stringify(secret)));
      return { ...open, enc: { iv, ct: new Uint8Array(ct) } };
    };
    const unseal = async (rec) => {
      if (!rec || !rec.enc) return rec;                                         // registro viejo en claro
      const { enc, ...rest } = rec;
      try { return { ...rest, ...JSON.parse(new TextDecoder().decode(await d.subtle.decrypt({ name: 'AES-GCM', iv: enc.iv }, await getKey(), enc.ct))) }; }
      catch (e) { return { ...rest, h: '', n: '', method: 'cedula', reason: 'unknown', unreadable: true }; }       // clave perdida o dato dañado: no se inventa nada; el servidor lo marcará para revisar
    };
    const putSealed = async (store, rec) => c.db.put(store, await seal(store, rec));
    const listSealed = async (store) => Promise.all((await c.db.getAll(store)).map(unseal));
    c.sealLegacy = async () => { for (const store of Object.keys(SECRET)) for (const rec of await c.db.getAll(store)) if (!rec.enc) await putSealed(store, rec); };

    const recount = async () => { const cons = await c.consentList(), q = await c.queueList(); c.consentSize = cons.length; c.queueSize = q.length;
      const stamps = q.map((r) => Date.parse(r.timestamp)).concat(cons.map((r) => Date.parse(r.at))).filter((t) => !Number.isNaN(t)); c.oldestAgeMs = stamps.length ? d.now() - Math.min(...stamps) : 0; c.reviewCount = (await c.db.getAll('review')).length; render(); };

    c.recount = recount;

    /* --- autorización biométrica sin red (L1): decisiones de la persona guardadas con la HUELLA (nunca la cédula) hasta sincronizar --- */
    c.consentSize = 0;
    c.consentList = async () => (c.db ? listSealed('consents') : []);
    c.consentAdd = async (entry) => { await putSealed('consents', entry); await recount(); };
    /* Estado local de una persona: la última decisión pendiente manda; si no hay, la bandera `a` de la copia. */
    c.consentLocal = async (raw) => {
      const h = await c.hashFor(raw);
      if (!h) return { known: false, accepted: false, blocked: false };
      const mine = (await c.consentList()).filter((e) => e.h === h).sort((a, b) => (a.at < b.at ? -1 : 1)), last = mine[mine.length - 1];
      if (last) return { known: true, accepted: last.decision === 'accept' && !!last.adult, blocked: !!(await c.db.get('roster', h) || {}).b };
      const person = await c.db.get('roster', h);
      return { known: !!person, accepted: !!(person && person.a === 1), blocked: !!(person && person.b === 1) };
    };
    /* Sincroniza las decisiones locales (lotes de 100; el servidor es idempotente por `id`). Devuelve cuántas quedaron en el servidor. */
    c.flushConsents = async () => {
      let sent = 0;
      for (;;) {
        const list = (await c.consentList()).sort((a, b) => (a.at < b.at ? -1 : 1)).slice(0, 100);
        if (!list.length) return sent;
        let res;
        try {
          res = await d.fetch(`/api/events/${d.eventId}/consents`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store',
            body: JSON.stringify({ entries: list.map((e) => ({ id: e.id, h: e.h, decision: e.decision, adult: e.adult, text_hash: e.text_hash, version: e.version, device: e.device, at: e.at })) }) });
        } catch (e) { return sent; }
        if (!res.ok) return sent;                                           // 401/403/5xx: se conservan y se reintenta (la bandeja avisa)
        await c.db.del('consents', list.map((e) => e.id)); sent += list.length; await recount();
      }
    };

    /* --- roster local --- */
    c.rosterMeta = async () => (c.db ? c.db.get('meta', 'roster') : null);
    /* Total de personas que el SERVIDOR informó la última vez que la lista en vivo se cargó en este dispositivo (`server_total` en `meta`): para el contador «LISTA LOCAL: N de N». */
    c.noteServerTotal = async (n) => {
      if (!c.supported || !c.db || !Number.isInteger(n)) return;
      try { const cur = await c.db.get('meta', 'server_total'); if (cur && cur.n === n && d.now() - cur.at < 60000) return; await c.db.put('meta', { k: 'server_total', n, at: d.now() }); } catch (e) { /* sin total: se avisa */ }
    };
    c.serverTotal = async () => { try { return (c.supported && c.db && (await c.db.get('meta', 'server_total'))) || null; } catch (e) { return null; } };
    c.rosterUsable = async () => { const m = await c.rosterMeta(); return !!(m && m.expires_at && d.now() < m.expires_at); };
    /* Formulario de persona (Fase 1A, pieza 5): la definición VERSIONADA (sin datos personales) vive en `meta` para que alta y edición funcionen igual sin red. Sobrevive a los borrados de la lista
       (cerrar sesión, vencer): no es un dato de nadie y sin ella el quiosco no sabría cómo dibujar el formulario sin red. */
    c.personForm = async () => { try { const m = c.db ? await c.db.get('meta', 'person_form') : null; return m && m.definition ? m.definition : null; } catch (e) { return null; } };
    c.savePersonForm = async (definition) => { if (!c.db) return; if (definition) await c.db.put('meta', { k: 'person_form', definition, saved_at: d.now() }); else await c.db.del('meta', 'person_form'); };
    /* Pide la definición vigente (solo si la pantalla se abrió con el formulario de persona: `personForm: true` en init). El servidor dice «apagado» → se borra la copia. Nunca rompe el refresco. */
    c.refreshPersonForm = async () => {
      try {
        const res = await d.fetch(`/api/events/${d.eventId}/person-form`, { cache: 'no-store' });
        if (!res.ok) return null;
        const body = await res.json();
        if (!body.enabled || !body.definition) { await c.savePersonForm(null); return null; }
        await c.savePersonForm(body.definition);
        return body.definition;
      } catch (e) { return null; }
    };
    c.wipeRoster = async () => { if (!c.db) return; const pf = await c.personForm(); await c.db.clear(['roster', 'meta', 'people', 'cache']); c.peopleIdx = null; if (pf) await c.savePersonForm(pf); };           // al cerrar sesión, al finalizar el evento y al vencer
    c.wipeAll = async () => { if (c.db) { const pf = await c.personForm(); await c.db.clear(['roster', 'meta', 'queue', 'people', 'cache']); c.peopleIdx = null; if (pf) await c.savePersonForm(pf); await recount(); } };      // la lista de «revisar» se conserva hasta que el operador la vea

    /* Descarga/valida el roster (`If-None-Match`: 304 = nada cambió, solo se renueva la vigencia). Devuelve 'ok' | 'unauth' (sesión vencida) | 'denied' (evento finalizado o sin
       permiso: se borra la copia y se avisa) | 'error'. Un 429 cuenta como respuesta buena (el servidor contestó) pero no renueva nada. */
    c.refreshRoster = async () => {
      const meta = await c.rosterMeta();
      let res;
      try {
        res = await d.fetch(`/api/events/${d.eventId}/local-roster`, { headers: meta && meta.v ? { 'If-None-Match': `"${meta.v}"` } : {}, cache: 'no-store' });
      } catch (e) { return 'error'; }
      if (res.status === 429) return 'ok';
      if (res.status === 401) { c.sessionExpired = true; render(); return 'unauth'; }
      if (res.status === 403 || res.status === 409) {
        if (res.status === 409) c.eventFinished = true;
        await c.wipeRoster();
        if (!c.notice) c.notice = { kind: 'denied', text: (n) => `${c.eventFinished ? 'El evento finalizó' : 'Ya no tienes acceso a este evento'}: se borró la copia local. ${n} ingreso(s) pendientes de sincronizar.` };
        render();
        return 'denied';
      }
      c.sessionExpired = false;
      const fetchedAt = d.now();
      if (res.status === 304 && meta) {
        await c.db.put('meta', { ...meta, fetched_at: fetchedAt, expires_at: fetchedAt + (meta.max_age_s || 86400) * 1000 });
        if (d.personForm) await c.refreshPersonForm();
        return 'ok';
      }
      if (!res.ok) return 'error';
      const body = await res.json();
      if (!body || !Array.isArray(body.people) || !body.salt) return 'error';          // una respuesta 200 que no es la lista (p. ej. una página de un portal de red): la copia buena no se toca
      await c.db.replaceRoster(body.people, { v: body.v, generated_at: body.generated_at, salt: body.salt, count: body.count, max_age_s: body.max_age_s, consent: body.consent || null,
        event_id: body.event && body.event.id, auto_register: !!(body.event && body.event.auto_register), fetched_at: fetchedAt, expires_at: fetchedAt + (body.max_age_s || 86400) * 1000 });
      if (d.personForm) await c.refreshPersonForm();
      return 'ok';
    };

    /* --- COPIA COMPLETA de las personas del evento (25-nov-2026, «registro completo sin conexión»; aprobado por la auditora según Juan David). Son las MISMAS filas que el
       directorio ya baja con red (`/api/users` y sus cambios): no hay descarga aparte ni consulta extra al servidor. Aquí van datos personales en claro (cédula, teléfono, correo…),
       así que SIEMPRE cifrados en reposo (AES-GCM 256, la clave no extraíble de este equipo), en bloques de PEOPLE_CHUNK personas. Vive y muere con la lista local: se borra al cerrar
       sesión, al finalizar el evento, al perder el permiso y al vencer (24 h sin refrescar). Sin fotos ni vectores biométricos (el directorio no los trae). --- */
    c.peopleIdx = null;                                                           // Map(cédula → nº de bloque), en memoria
    const cidIds = new Map();                                                     // client_id → cédula de lo acreditado sin red en esta sesión (solo memoria)
    const sealBlock = async (k, rows) => { const iv = randomIv(); const ct = await d.subtle.encrypt({ name: 'AES-GCM', iv }, await getKey(), new TextEncoder().encode(JSON.stringify(rows))); return { k, n: Array.isArray(rows) ? rows.length : 1, enc: { iv, ct: new Uint8Array(ct) } }; };
    const openBlock = async (rec) => { try { return JSON.parse(new TextDecoder().decode(await d.subtle.decrypt({ name: 'AES-GCM', iv: rec.enc.iv }, await getKey(), rec.enc.ct))); } catch (e) { return null; } };
    const clean = (u) => { const o = {}; Object.keys(u).forEach((k) => { if (k.slice(0, 2) !== '__') o[k] = u[k]; }); return o; };          // sin marcas internas de la pantalla
    c.peopleMeta = async () => { try { return c.db ? await c.db.get('meta', 'people') : null; } catch (e) { return null; } };
    /* Reemplaza la copia completa (carga inicial o recarga del directorio). Devuelve cuántas personas guardó (0 = no se pudo / sin soporte). */
    c.peopleSave = async (users) => {
      if (!c.supported || !c.db || !Array.isArray(users)) return 0;
      try {
        const blocks = [], idx = new Map();
        for (let i = 0, k = 0; i < users.length; i += PEOPLE_CHUNK, k++) { const rows = users.slice(i, i + PEOPLE_CHUNK).map(clean); rows.forEach((u) => idx.set(String(u.id), k)); blocks.push(await sealBlock(k, rows)); }
        await c.db.clear(['people']);
        await c.db.putMany('people', blocks);
        await c.db.put('meta', { k: 'people', n: users.length, blocks: blocks.length, saved_at: d.now(), event_id: d.eventId });
        c.peopleIdx = idx;
        return users.length;
      } catch (e) { return 0; }
    };
    const loadIdx = async () => {
      if (c.peopleIdx) return c.peopleIdx;
      const idx = new Map();
      for (const rec of await c.db.getAll('people')) { const rows = await openBlock(rec); if (rows) rows.forEach((u) => idx.set(String(u.id), rec.k)); }
      c.peopleIdx = idx; return idx;
    };
    /* Aplica cambios (filas completas nuevas o cambiadas) sobre la copia: solo se reescriben los bloques tocados. Sin copia previa no hace nada (la crea la próxima carga completa). */
    c.peoplePatch = async (users) => {
      if (!c.supported || !c.db || !Array.isArray(users) || !users.length) return 0;
      try {
        const meta = await c.peopleMeta(); if (!meta) return 0;
        const idx = await loadIdx(), byBlock = new Map(); let last = Math.max(0, meta.blocks - 1), added = 0;
        const blockOf = async (k) => { if (!byBlock.has(k)) { const rec = await c.db.get('people', k); byBlock.set(k, (rec && await openBlock(rec)) || []); } return byBlock.get(k); };
        for (const u of users) {
          const id = String(u.id), row = clean(u);
          if (idx.has(id)) { const rows = await blockOf(idx.get(id)), i = rows.findIndex((x) => String(x.id) === id); if (i >= 0) rows[i] = row; else rows.push(row); continue; }
          let rows = await blockOf(last);
          if (rows.length >= PEOPLE_CHUNK * 1.5) { last += 1; rows = await blockOf(last); }
          rows.push(row); idx.set(id, last); added++;
        }
        const out = []; for (const [k, rows] of byBlock) out.push(await sealBlock(k, rows));
        await c.db.putMany('people', out);
        await c.db.put('meta', { ...meta, n: meta.n + added, blocks: Math.max(meta.blocks, last + 1), saved_at: d.now() });
        return users.length;
      } catch (e) { return 0; }
    };
    /* Cambia campos de UNA persona de la copia (acreditar, deshacer o editar sin red). `patch` puede traer `extra_fields` (se mezclan). Devuelve la fila resultante o null. */
    c.peopleApply = async (id, patch) => {
      if (!c.supported || !c.db || id == null || id === '') return null;
      try {
        const idx = await loadIdx(), k = idx.get(String(id)); if (k === undefined) return null;
        const rec = await c.db.get('people', k), rows = (rec && await openBlock(rec)) || [], i = rows.findIndex((x) => String(x.id) === String(id)); if (i < 0) return null;
        rows[i] = { ...rows[i], ...patch, ...(patch && patch.extra_fields ? { extra_fields: { ...(rows[i].extra_fields || {}), ...patch.extra_fields } } : {}) };
        await c.db.put('people', await sealBlock(k, rows));
        return rows[i];
      } catch (e) { return null; }
    };
    /* Copias de LECTURAS del servidor para trabajar sin red en Áreas e Inventario (docs/28): zonas, quién está adentro, productos, entregas, lo asignado y los dependientes. Cada una
       va cifrada (misma clave), se reemplaza cada vez que la red responde y se borra con la lista local. `cacheGet` devuelve null si no hay copia. */
    c.cachePut = async (key, data) => { if (!c.supported || !c.db) return false; try { const rec = await sealBlock(String(key), data); rec.at = d.now(); await c.db.put('cache', rec); return true; } catch (e) { return false; } };
    c.cacheGet = async (key) => { if (!c.supported || !c.db) return null; try { const rec = await c.db.get('cache', String(key)); return rec ? await openBlock(rec) : null; } catch (e) { return null; } };
    /* Quita a una persona de la copia (eliminada sin red) o le cambia la cédula (corrección sin red). */
    c.peopleRemove = async (id, newId) => {
      if (!c.supported || !c.db || id == null || id === '') return false;
      try {
        const idx = await loadIdx(), k = idx.get(String(id)); if (k === undefined) return false;
        const rec = await c.db.get('people', k), rows = (rec && await openBlock(rec)) || [], i = rows.findIndex((x) => String(x.id) === String(id)); if (i < 0) return false;
        if (newId) { rows[i] = { ...rows[i], id: String(newId) }; idx.set(String(newId), k); } else { rows.splice(i, 1); const meta = await c.peopleMeta(); if (meta) await c.db.put('meta', { ...meta, n: Math.max(0, meta.n - 1) }); }
        idx.delete(String(id));
        await c.db.put('people', await sealBlock(k, rows));
        return true;
      } catch (e) { return false; }
    };
    /* Todas las personas de la copia completa, o null si no hay copia vigente de ESTE evento (vale mientras valga la lista local). */
    c.peopleLoad = async () => {
      if (!c.supported || !c.db) return null;
      try {
        const meta = await c.peopleMeta();
        if (!meta || String(meta.event_id) !== String(d.eventId) || !(await c.rosterUsable())) return null;
        const out = [], idx = new Map();
        for (const rec of (await c.db.getAll('people')).sort((a, b) => a.k - b.k)) { const rows = await openBlock(rec); if (!rows) return null; rows.forEach((u) => { idx.set(String(u.id), rec.k); out.push(u); }); }          // un bloque ilegible: la copia no sirve (se usa la lista mínima)
        c.peopleIdx = idx;
        return out;
      } catch (e) { return null; }
    };

    /* --- registro sin red --- */
    c.queueList = async () => (c.db ? listSealed('queue') : []);
    /* «Deshacer» de una acreditación hecha SIN red que todavía no se sincronizó: se quita de la cola. Devuelve true si estaba. */
    c.unqueue = async (clientId) => {
      if (!c.db) return false;
      const q = (await c.queueList()).find((r) => r.client_id === clientId);
      if (!q) return false;
      await c.db.del('queue', clientId);
      const person = (await c.db.getAll('roster')).find((p) => p.h === q.h);
      if (person && q.prev && person.s === 'Registrado' && q.prev !== 'Registrado') await c.db.put('roster', { ...person, s: q.prev });          // la copia local vuelve a como estaba
      const pid = cidIds.get(clientId); cidIds.delete(clientId);
      if (pid && q.prev && q.prev !== 'Registrado') await c.peopleApply(pid, { status: q.prev });
      await c.recount();
      return true;
    };
    /* Busca la cédula en el roster local. status: 'found' (+ person, duplicate) | 'not_found' | 'expired'. `duplicate`: ya consta como registrado (copia local o cola de este quiosco).
       Si ya lo admitió OTRO quiosco durante el corte, aquí no se puede saber: el servidor lo marca para revisión al sincronizar. */
    c.scanLocal = async (raw) => {
      const meta = await c.rosterMeta();
      if (!meta || !meta.expires_at || d.now() >= meta.expires_at) return { status: 'expired' };
      const cedula = normalize(raw);
      const person = cedula ? await c.db.get('roster', await c.fingerprint(meta.salt, cedula)) : null;
      return person ? await found(person, cedula) : { status: 'not_found' };
    };
    const found = async (person, cedula) => {
      const queued = (await c.queueList()).some((q) => q.h === person.h);
      return { status: 'found', person, cedula, duplicate: queued || person.s !== 'No registrado', queued };
    };
    /* La misma búsqueda por HUELLA (filas de la lista local, que no tienen la cédula) y utilidades para la lista/búsqueda sin red. */
    c.findByHash = async (h) => {
      const meta = await c.rosterMeta();
      if (!meta || !meta.expires_at || d.now() >= meta.expires_at) return { status: 'expired' };
      const person = h ? await c.db.get('roster', h) : null;
      return person ? await found(person, '') : { status: 'not_found' };
    };
    /* «Modo autoregistro» del evento, tal como vino con la copia (se guarda en IndexedDB: vale tras recargar sin red). Apagado o desconocido → NO acredita al escanear, solo busca. */
    c.autoRegister = async () => { const m = await c.rosterMeta(); return !!(m && m.auto_register === true); };
    /* PR3 (causa E): el autorregistro sin red usaba la bandera de la última DESCARGA de la copia (hasta 4 min de antigüedad). Cada sondeo bueno del directorio trae la bandera actual del servidor
       (`flags` de /users/changes) y se guarda aquí, así que al cortarse la red vale la de hace segundos. Sin copia local no hay dónde guardarla. */
    c.setAutoRegister = async (v) => {
      if (!c.supported || !c.db || typeof v !== 'boolean') return;
      try { const m = await c.rosterMeta(); if (m && m.auto_register !== v) await c.db.put('meta', { ...m, auto_register: v }); } catch (e) { /* se queda la de la descarga */ }
    };
    c.hashFor = async (raw) => { const meta = await c.rosterMeta(); const cedula = normalize(raw); return meta && cedula ? c.fingerprint(meta.salt, cedula) : ''; };
    c.localPeople = async () => ((await c.rosterUsable()) ? c.db.getAll('roster') : []);
    /* Encola el ingreso (client_id + marca de tiempo; huella y nombre, NO la cédula) y lo anota como registrado en la copia local. */
    c.enqueue = async (found, method, clientId, timing) => {
      const rec = { client_id: clientId || uuid(), h: found.person.h, n: found.person.n, timestamp: new Date(d.now()).toISOString(), method: ['qr', 'manual'].includes(method) ? method : 'cedula', prev: found.person.s };
      if (timing && Number.isFinite(timing.took_ms)) { rec.took_ms = timing.took_ms; rec.ui_flow = String(timing.ui_flow || 'v0'); }          // 1A: tiempo medido (solo una duración y una etiqueta); se envía al sincronizar          // `prev`: estado que tenía en la copia local (para «Deshacer»)
      await putSealed('queue', rec);
      await c.db.put('roster', { ...found.person, s: 'Registrado' });
      if (found.cedula) { cidIds.set(rec.client_id, String(found.cedula)); await c.peopleApply(found.cedula, { status: 'Registrado' }); }          // la cola NUNCA guarda la cédula: el vínculo vive solo en memoria (para «Deshacer»)
      await recount();
      return rec;
    };

    /* --- sincronización de la cola --- */
    const REASONS = { review: 'ya había ingresado por otro quiosco (o por otro registro) durante la desconexión: verificar', unknown: 'no se pudo registrar en el servidor (persona no encontrada en el evento): verificar manualmente' };
    const addReview = (rec, reason) => putSealed('review', { client_id: rec.client_id, n: rec.n || '', reason, at: new Date(d.now()).toISOString() });
    const syncFail = (kind) => { c.syncFails++; c.nextSyncAt = d.now() + Math.min(SYNC_BACKOFF_MAX_MS, SYNC_BACKOFF_BASE_MS * 2 ** (c.syncFails - 1)); return kind || 'error'; };
    /* Envía la cola en lotes de hasta 500 (en orden de marca de tiempo). `force` ignora la espera (cierre de sesión). Devuelve 'empty' | 'ok' | 'wait' | 'offline' | 'busy' | 'session' | 'denied' | 'error'. */
    c.syncQueue = async (force) => {
      if (!c.supported || c.syncing) return 'busy';
      if (c.machine.state === 'contingency') return 'offline';
      if (!force && d.now() < c.nextSyncAt) return 'wait';
      c.syncing = true; render();
      let synced = 0;
      try {
        await c.flushConsents();
        for (;;) {
          const q = (await c.queueList()).sort((a, b) => (a.timestamp < b.timestamp ? -1 : 1)).slice(0, SYNC_BATCH);
          if (!q.length) {
            c.syncFails = 0; if (c.eventFinished) await c.wipeAll();
            if (synced) { if (!c.eventFinished) c.refreshRoster(); c.syncListeners.forEach((f) => f(synced)); }          // lo sincronizado cambia el estado en el servidor: copia local y lista al día
            return 'empty';
          }
          let res;
          try {
            res = await d.fetch(`/api/events/${d.eventId}/access-logs/sync`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store',
              body: JSON.stringify({ records: q.map((r) => ({ client_id: r.client_id, h: r.h, timestamp: r.timestamp, method: r.method, took_ms: r.took_ms, ui_flow: r.ui_flow })) }) });
          } catch (e) { return syncFail(); }
          if (res.status === 401) { c.sessionExpired = true; return syncFail('session'); }
          if (res.status === 403 || res.status === 404 || res.status === 400) {
            c.notice = { kind: 'syncdenied', text: (n) => `No se pudo sincronizar (sin permiso o el evento cerró hace más de 7 días): ${n} ingreso(s) siguen guardados en este dispositivo.` };
            return syncFail('denied');
          }
          if (!res.ok) return syncFail();                                   // 429 / 5xx: espera creciente
          const body = await res.json();
          const byId = new Map((body.results || []).map((r) => [r.client_id, r]));
          const finished = [];
          for (const rec of q) {
            const r = byId.get(rec.client_id);
            if (!r) continue;                                                // sin respuesta para este: se conserva y se reintenta
            if (r.result === 'created' && r.review) await addReview(rec, 'review');
            else if (r.result === 'unknown' || r.result === 'invalid') await addReview(rec, 'unknown');
            finished.push(rec.client_id);
          }
          if (!finished.length) return syncFail();                           // sin progreso: no repetir en bucle
          await c.db.del('queue', finished); synced += finished.length;
          c.syncFails = 0; c.sessionExpired = false;
          if (c.notice && c.notice.kind === 'syncdenied') c.notice = null;
          await recount();
        }
      } finally { c.syncing = false; render(); }
    };
    /* Lo no sincronizado a los 7 días se ELIMINA del dispositivo (texto C''' de la auditora: «se suprime de manera automática»), pero NUNCA en silencio: aviso visible desde el día 3 y, al borrar, un aviso que el operador debe ver. */
    c.pruneOld = async () => {
      const tooOld = (t) => d.now() - Date.parse(t) > QUEUE_MAX_AGE_MS;
      const old = (await c.queueList()).filter((r) => tooOld(r.timestamp)), oldConsents = (await c.consentList()).filter((r) => tooOld(r.at));
      if (!old.length && !oldConsents.length) return 0;
      if (old.length) await c.db.del('queue', old.map((r) => r.client_id));
      if (oldConsents.length) await c.db.del('consents', oldConsents.map((r) => r.id));
      const n = old.length + oldConsents.length;
      c.notice = { kind: 'pruned', text: () => `${n} registro(s) llevaban más de 7 días sin sincronizar y se eliminaron de este dispositivo, como indica la política de privacidad: verificar manualmente.` };
      await recount();
      return n;
    };
    /* Antes de cerrar sesión: intenta sincronizar y devuelve cuántos ingresos siguen sin sincronizar (la cola se conserva). */
    c.beforeLogout = async () => { if (c.supported) { await c.syncQueue(true); await recount(); } return c.queueSize; };

    /* --- lista de «revisar» --- */
    c.reviewList = async () => (c.db ? listSealed('review') : []);
    c.clearReview = async () => { if (c.db) { await c.db.clear(['review']); await recount(); } };
    c.openReview = async () => {
      const doc = d.document, items = await c.reviewList();
      if (!doc || !items.length) return;
      const overlay = doc.createElement('div'), box = doc.createElement('div'), ul = doc.createElement('ul'), btn = doc.createElement('button'), h = doc.createElement('h3');
      overlay.style.cssText = 'position:fixed; inset:0; background:rgba(10,14,46,.45); z-index:10001; display:flex; align-items:center; justify-content:center; padding:1rem;';
      box.style.cssText = 'background:#fff; border-radius:14px; padding:1.4rem; max-width:520px; width:100%; max-height:80vh; overflow:auto; font-family:var(--font-body, sans-serif);';
      overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-label', 'Ingresos para revisar');
      h.textContent = 'Ingresos para revisar'; h.style.marginTop = '0';
      items.forEach((it) => { const li = doc.createElement('li'); li.textContent = `${it.n || 'Persona'}: ${REASONS[it.reason] || it.reason}`; li.style.marginBottom = '6px'; ul.appendChild(li); });
      btn.textContent = 'Entendido'; btn.style.cssText = 'margin-top:12px; padding:8px 18px; border:none; border-radius:8px; background:#0a0e2e; color:#fff; cursor:pointer;';
      btn.addEventListener('click', async () => { overlay.remove(); await c.clearReview(); });
      [h, ul, btn].forEach((x) => box.appendChild(x)); overlay.appendChild(box); doc.body.appendChild(overlay);
    };

    /* --- señales desde directory.js --- */
    c.noteScanExhausted = () => { if (c.supported && c.machine) c.machine.scanExhausted(); };
    /* Una petición de la pantalla acaba de fallar por red: se comprueba la salud YA (sin esperar al siguiente ciclo) para pasar antes al modo contingencia. */
    c.noteNetFail = () => { if (c.supported && c.machine && !c.checking) { c.checking = true; Promise.resolve().then(() => c.checkHealth()).catch(() => {}).then(() => { c.checking = false; }); } };
    c.noteAuthGood = () => { if (c.supported && c.machine) c.machine.authGood(); };

    /* --- franja visible --- */
    /* La franja NO tapa nada (25-nov-2026, pedido de Juan David: en el celular tapaba «Guardar»): reserva su propio espacio. Publica su alto en --gw-banner-h y una hoja de estilos baja
       el contenido de la página y todo lo que ocupa la pantalla completa (ventanas, bandeja, menú lateral, recorrido). En pantallas angostas el texto es corto para que ocupe poco. */
    const win = () => (d.document && d.document.defaultView) || (typeof window !== 'undefined' ? window : null);
    const narrow = () => { const w = win(); return !!(w && w.innerWidth && (w.innerWidth < 900 || (w.innerHeight && w.innerHeight < 560))); };          // celular o tableta pequeña, en cualquier posición
    const SPACE_CSS = 'html body{padding-top:var(--gw-banner-h,0px)}'
      + '.gw-modal-backdrop,.gw-registro__overlay,.gw-outbox__modal,.gw-tour,.gwe-preview,.gw-gx__dialog,.golden-sidebar,.golden-sidebar-backdrop{top:var(--gw-banner-h,0px)!important}'
      + '.golden-sidebar{height:calc(100% - var(--gw-banner-h,0px))!important}'
      + '.gw-nav,.gw-search,.golden-header{top:var(--gw-banner-h,0px)!important}'
      + '.gw-workarea__bar{top:calc(3.4rem + var(--gw-banner-h,0px))!important}'
      + '.gw-modal-backdrop .gw-modal,.gw-registro__overlay>*{max-height:calc(100dvh - var(--gw-banner-h,0px) - var(--gw-outbox-h,0px))}';
    function space() {
      const doc = d.document;
      if (!doc || !doc.documentElement || !doc.documentElement.style || !doc.documentElement.style.setProperty) return;
      let h = 0;
      try { if (c.banner && c.banner.getBoundingClientRect) h = Math.ceil(c.banner.getBoundingClientRect().height || 0); } catch (e) { h = 0; }
      doc.documentElement.style.setProperty('--gw-banner-h', h + 'px');
      if (h && doc.head && doc.getElementById && !doc.getElementById('gw-banner-space')) { const st = doc.createElement('style'); st.id = 'gw-banner-space'; st.textContent = SPACE_CSS; doc.head.appendChild(st); }
    }
    c.space = space;
    function banner() {
      if (!c.supported) return c.lastError ? { st: 'unsupported', text: 'Este navegador no permite el modo contingencia: sin conexión no se podrá acreditar.' } : null;
      const n = c.queueSize, st = c.machine.state;
      if (c.sessionExpired && (st === 'contingency' || n > 0)) return { st: 'session', text: `Sesión vencida: inicia sesión de nuevo; ${n} ingreso(s) guardados se sincronizarán.`, link: true };
      if (st === 'contingency') return { st: 'contingency', text: narrow() ? `Sin conexión: todo se guarda aquí y se envía al volver la red${n ? ` · ${n} en cola` : ''}.`
        : `MODO CONTINGENCIA (sin conexión): sigue trabajando; todo se guarda en este dispositivo y se envía solo al volver la red${n ? ` · ${n} en cola` : ''}. Quien no esté en la copia: verificar manualmente.` };
      if (c.notice) return { st: 'notice', text: c.notice.text(n), dismiss: true };
      if ((n > 0 || c.consentSize > 0) && c.oldestAgeMs >= WARN_AGE_MS) {      // lo guardado envejece: avisar ANTES de que se elimine (día 3 amarillo, día 6 rojo)
        const days = Math.floor(c.oldestAgeMs / DAY_MS), left = Math.max(0, 7 - days);
        return { st: c.oldestAgeMs >= URGENT_AGE_MS ? 'aging2' : 'aging', text: `Hay registros sin sincronizar hace ${days} días: conecta este dispositivo a internet y sincroniza. A los 7 días se eliminan de forma automática (${left === 0 ? 'hoy' : `faltan ${left}`}).` };
      }
      if (st === 'degraded') return { st: 'degraded', text: 'Conexión inestable: si se corta, el quiosco pasará solo al modo contingencia.' };
      if (n > 0) return { st: 'syncing', text: `${c.syncing ? 'Sincronizando' : 'Pendientes de sincronizar:'} ${n} ingreso(s) guardados sin conexión…` };
      if (c.reviewCount > 0) return { st: 'review', text: `${c.reviewCount} ingreso(s) para revisar tras la sincronización.` };
      return null;
    }
    function render() {
      const doc = d.document;
      if (!doc || !doc.body) return;
      if (doc.body.classList) doc.body.classList.toggle('golden-contingency', !!(c.supported && c.machine && c.machine.state === 'contingency'));       // muestra los botones «Acreditar sin red» de las filas
      const b = banner();
      const sig = b ? `${b.st}|${b.text}|${c.reviewCount}` : '';
      if (sig === c.bannerSig) return;
      c.bannerSig = sig;
      if (c.banner) { c.banner.remove(); c.banner = null; }
      if (!b) { space(); return; }
      const el = doc.createElement('div');
      const palette = { degraded: ['#fff8e1', '#7a5b00', '#f0ad4e'], contingency: ['#fbe9ea', '#a12631', '#dc3545'], session: ['#fbe9ea', '#a12631', '#dc3545'], notice: ['#fff8e1', '#7a5b00', '#f0ad4e'],
        syncing: ['#e8f1fb', '#1d4f87', '#4a90d9'], review: ['#fff8e1', '#7a5b00', '#f0ad4e'], aging: ['#fff8e1', '#7a5b00', '#f0ad4e'], aging2: ['#fbe9ea', '#a12631', '#dc3545'], unsupported: ['#eef1f5', '#44505c', '#8a96a3'] }[b.st];
      el.setAttribute('role', 'status'); el.setAttribute('aria-live', 'polite');
      el.style.cssText = `position:fixed; top:0; left:0; right:0; z-index:10000; box-sizing:border-box; padding:${narrow() ? '5px 10px' : '8px 14px'}; text-align:center; font-size:${narrow() ? '.8rem' : '.9rem'}; line-height:1.3; font-weight:600; background:${palette[0]}; color:${palette[1]}; border-bottom:3px solid ${palette[2]};`;
      el.dataset.state = b.st;
      el.setAttribute('data-golden-banner', '1');          // toast.js desplaza los avisos bajo esta franja
      el.textContent = b.text;
      const button = (label, fn) => { const x = doc.createElement('button'); x.textContent = label; x.style.cssText = `margin-left:10px; padding:2px 10px; border:1px solid ${palette[2]}; border-radius:6px; background:#fff; color:${palette[1]}; cursor:pointer; font-weight:600;`; x.addEventListener('click', fn); el.appendChild(x); return x; };
      if (b.link) { const a = doc.createElement('a'); a.textContent = 'Iniciar sesión'; a.setAttribute('href', '/login'); a.setAttribute('target', '_blank'); a.setAttribute('rel', 'noopener'); a.style.cssText = `margin-left:10px; color:${palette[1]}; text-decoration:underline;`; el.appendChild(a); }
      if (b.dismiss) button('Entendido', () => { c.notice = null; render(); });
      if (c.reviewCount > 0) button(`Revisar (${c.reviewCount})`, () => c.openReview());
      doc.body.appendChild(el);
      c.banner = el;
      space();
    }
    c.render = render;

    /* --- sonda de salida: petición AUTENTICADA liviana --- */
    c.probe = async () => {
      const ctl = typeof AbortController === 'function' ? new AbortController() : null;
      const timer = ctl ? d.setTimeout(() => ctl.abort(), HEALTH_TIMEOUT_MS) : null;
      try {
        const r = await d.fetch('/api/ping-auth', { cache: 'no-store', signal: ctl ? ctl.signal : undefined });
        if (r.status === 200 || r.status === 429) return 'ok';              // 429: el servidor contestó (alcanzable)
        return r.status === 401 ? 'unauth' : 'error';
      } catch (e) { return 'error'; } finally { if (timer) d.clearTimeout(timer); }
    };

    /* --- arranque --- */
    const checkHealth = async () => {
      let ok = false;
      const ctl = typeof AbortController === 'function' ? new AbortController() : null;
      const timer = ctl ? d.setTimeout(() => ctl.abort(), HEALTH_TIMEOUT_MS) : null;
      const h0 = d.now();
      try { const r = await d.fetch('/health', { cache: 'no-store', signal: ctl ? ctl.signal : undefined }); ok = !!(r && r.ok); } catch (e) { ok = false; } finally { if (timer) d.clearTimeout(timer); }
      T('contingency:health', { ok, ms: d.now() - h0 });
      c.machine.health(ok);
      c.healthListeners.forEach((f) => { try { f(ok); } catch (e) { /* un oyente no tumba el chequeo */ } });
      if (c.machine.readyToProbe() && d.now() >= c.probeAfter) {          // 2 chequeos buenos: falta UNA petición autenticada buena
        const r = await c.probe();
        if (r === 'ok') { c.sessionExpired = false; c.machine.authGood(); render(); }
        else { if (r === 'unauth') c.sessionExpired = true; c.probeAfter = d.now() + PROBE_BACKOFF_MS; render(); }
      } else if (ok && c.machine.state !== 'contingency' && (c.queueSize > 0 || c.consentSize > 0)) c.syncQueue();
    };
    c.checkHealth = checkHealth;
    /* Avisa el resultado de cada chequeo de salud (lo usa la bandeja de salida para reintentar sola lo pendiente: p. ej. tras recargar la página sin red, donde no hay «volvió la red» que escuchar). */
    c.healthListeners = [];
    c.onHealth = (f) => { c.healthListeners.push(f); };
    const T = (n, x) => { if (root.GoldenTrace) root.GoldenTrace.mark(n, x); };          // marcas de arranque (static/js/boot-trace.js)
    c.start = async (opts) => {
      T('contingency:start');
      if (opts && opts.eventId) d.eventId = opts.eventId;
      c.machine = createMachine((s, from) => {
        T('contingency:state:' + s, { from });
        render(); c.listeners.forEach((f) => f(s));
        if (s === 'normal' && from === 'contingency') { c.refreshRoster(); c.syncQueue(true); }       // volvió la red: copia al día y cola al servidor
      });
      { const w = win(); if (w && w.addEventListener) w.addEventListener('resize', () => { c.bannerSig = ''; render(); }); }          // al girar o cambiar el tamaño: texto corto/largo y espacio reservado al día
      if (!c.isSupported()) { c.lastError = 'unsupported'; render(); c.markReady(); return c; }
      try { c.db = await openStore(d.idb, `golden-contingency-${d.eventId}`); } catch (e) { c.lastError = 'unsupported'; render(); c.markReady(); return c; }
      c.supported = true;
      T('contingency:idb-open');
      if (d.document && d.document.head && d.document.createElement) {
        const st = d.document.createElement('style');
        st.textContent = '.btn-offline-accredit{display:none !important} body.golden-contingency .btn-offline-accredit{display:inline-block !important}';
        d.document.head.appendChild(st);
      }
      try { await getKey(); await c.sealLegacy(); } catch (e) { c.lastError = 'unsupported'; c.supported = false; render(); c.markReady(); return c; }      // sin WebCrypto/IndexedDB no se guarda nada sin cifrar: modo normal
      c.persistRequest = c.requestPersistence();                   // sin await: nunca bloquea el arranque
      await c.pruneOld();
      await recount();
      const meta = await c.rosterMeta();
      if (meta && meta.expires_at && d.now() >= meta.expires_at) await c.wipeRoster();           // vencido mientras el navegador estaba cerrado
      c.markReady();
      T('contingency:ready');
      c.refreshRoster().then((r) => { if (r === 'ok') { c.machine.authGood(); c.syncQueue(); } });
      c.timers.push(d.setInterval(checkHealth, HEALTH_MS));
      const gw = root.GW;                                            // toast.js: pestaña sin uso 60 s → no se refresca la lista (consulta la base); al volver se hace de inmediato. /health y la cola NO se pausan.
      let staleRoster = false;
      const refreshNow = async () => { staleRoster = false; if (c.machine.state !== 'contingency' && !c.eventFinished) { const r = await c.refreshRoster(); if (r === 'ok') c.machine.authGood(); } };
      if (gw && gw.onResume) gw.onResume(() => { if (staleRoster) refreshNow(); });
      c.timers.push(d.setInterval(async () => {
        await c.pruneOld();
        if (gw && gw.idle) { staleRoster = true; return; }
        await refreshNow();
      }, REFRESH_MS));
      return c;
    };
    c.stop = () => { c.timers.forEach((t) => d.clearInterval(t)); c.timers = []; if (c.db) { c.db.close(); c.db = null; } };
    return c;
  }

  const api = { create, createMachine, normalize, HEALTH_MS, HEALTH_TIMEOUT_MS, REFRESH_MS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GoldenContingency = Object.assign(api, { instance: null, init(opts) { this.instance = create(opts); return this.instance.start(opts); } });
})(typeof window !== 'undefined' ? window : globalThis);
