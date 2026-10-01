/* Modo contingencia del quiosco (Fase 3, docs/13 §9), cliente. Sin dependencias: solo IndexedDB (y crypto.subtle para la huella). Piezas:

   - Almacén (IndexedDB `golden-contingency-<evento>`): `roster` (huella → {h, n, c, s}), `queue` (ingresos hechos sin red, con `client_id` y marca de tiempo) y `meta` (versión,
     hora de generación, `expires_at`, sal). El roster NUNCA trae la cédula en claro (ver docs/15: la huella es minimización, no protección fuerte); la COLA sí guarda la cédula
     normalizada de quien se admitió sin red porque `/api/events/{id}/access-logs/sync` la necesita; se vacía al sincronizar (commit 3).
   - Máquina de estados (normal / degradado / contingencia): chequeo de `/health` (3 s) cada 5 s; entra en contingencia tras 2 fallos seguidos o tras 2 escaneos consecutivos que
     agotaron sus reintentos; un fallo aislado solo deja «degradado» y se olvida con el siguiente acierto; sale tras 2 chequeos buenos seguidos Y una petición autenticada buena.
   - Franja visible con `aria-live="polite"`, refresco del roster cada pocos minutos con la red, y registro sin red (`scanLocal` + `enqueue`; directory.js pone los avisos).
   Si falta IndexedDB o crypto.subtle, `start()` avisa y deja el modo normal sin tocar nada.
   Retención del roster: hasta que el evento finalice (la descarga responde 409/403 → se borra) y como máximo 24 h desde el último refresco (`expires_at`); `wipeRoster()`/`wipeAll()` lo
   borran (el cierre de sesión y la sincronización los usan en los commits 3 y 4). */
(function (root) {
  const HEALTH_MS = 5000, HEALTH_TIMEOUT_MS = 3000, REFRESH_MS = 4 * 60 * 1000, PROBE_BACKOFF_MS = 30000;
  const FAILS_TO_ENTER = 2, EXHAUSTED_TO_ENTER = 2, OKS_TO_LEAVE = 2;
  const normalize = (v) => String(v == null ? '' : v).replace(/[\s.]/g, '');      // igual que roster_normalize (app/routers/api.py)

  /* ------------------------------------------------------------------------------------------------------------------ máquina de estados (pura) */
  function createMachine(onChange) {
    const m = { state: 'normal', healthFails: 0, healthOks: 0, exhausted: 0 };
    const set = (s) => { if (m.state !== s) { m.state = s; if (s === 'contingency') { m.healthOks = 0; } if (onChange) onChange(s); } };
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
    m.authGood = () => {                      // una petición autenticada buena (escaneo, refresco del roster, sonda de salida)
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

  function openStore(idb, name) {
    return new Promise((resolve, reject) => {
      const r = idb.open(name, 1);
      r.onupgradeneeded = () => {
        const db = r.result;
        db.createObjectStore('roster', { keyPath: 'h' });
        db.createObjectStore('queue', { keyPath: 'client_id' });
        db.createObjectStore('meta', { keyPath: 'k' });
      };
      r.onsuccess = () => {
        const db = r.result;
        const tx = (stores, mode) => db.transaction(stores, mode);
        resolve({
          get: async (store, key) => req(tx([store], 'readonly').objectStore(store).get(key)),
          getAll: async (store) => req(tx([store], 'readonly').objectStore(store).getAll()),
          put: async (store, value) => { const t = tx([store], 'readwrite'); t.objectStore(store).put(value); return done(t); },
          del: async (store, key) => { const t = tx([store], 'readwrite'); t.objectStore(store).delete(key); return done(t); },
          clear: async (stores) => { const t = tx(stores, 'readwrite'); stores.forEach((s) => t.objectStore(s).clear()); return done(t); },
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
    const d = Object.assign({ idb: root.indexedDB, fetch: root.fetch && root.fetch.bind(root), now: () => Date.now(), setInterval: root.setInterval, clearInterval: root.clearInterval,
      setTimeout: root.setTimeout, clearTimeout: root.clearTimeout, document: root.document, subtle: root.crypto && root.crypto.subtle, eventId: root.EVENT_ID, uuid: null }, deps || {});
    const c = { machine: null, db: null, supported: false, banner: null, queueSize: 0, probeAfter: 0, timers: [], listeners: [], lastError: null };
    const uuid = () => d.uuid ? d.uuid() : (root.crypto && root.crypto.randomUUID ? root.crypto.randomUUID() : `c${d.now()}${Math.random().toString(16).slice(2)}`);

    c.isSupported = () => !!(d.idb && d.subtle && d.fetch);
    c.active = () => !!(c.supported && c.machine && c.machine.state === 'contingency');
    c.state = () => (c.machine ? c.machine.state : 'normal');
    c.onChange = (f) => c.listeners.push(f);

    /* --- huella de la cédula (igual que roster_fingerprint del servidor) --- */
    c.fingerprint = async (salt, cedula) => {
      const bytes = new TextEncoder().encode(`${salt}:${normalize(cedula)}`);
      const hash = new Uint8Array(await d.subtle.digest('SHA-256', bytes));
      return Array.from(hash.slice(0, 8)).map((b) => b.toString(16).padStart(2, '0')).join('');
    };

    /* --- roster local --- */
    c.rosterMeta = async () => (c.db ? c.db.get('meta', 'roster') : null);
    c.rosterUsable = async () => { const m = await c.rosterMeta(); return !!(m && m.expires_at && d.now() < m.expires_at); };
    c.wipeRoster = async () => { if (c.db) await c.db.clear(['roster', 'meta']); };           // al cerrar sesión, al finalizar el evento y al vencer
    c.wipeAll = async () => { if (c.db) await c.db.clear(['roster', 'meta', 'queue']); c.queueSize = 0; render(); };

    /* Descarga/valida el roster: con `If-None-Match` (304 = nada cambió, solo se renueva la vigencia). Devuelve 'ok' | 'denied' (sesión vencida o evento finalizado) | 'error'.
       Un 429 cuenta como respuesta autenticada buena (el servidor contestó), pero no renueva nada. */
    c.refreshRoster = async () => {
      const meta = await c.rosterMeta();
      let res;
      try {
        res = await d.fetch(`/api/events/${d.eventId}/local-roster`, { headers: meta && meta.v ? { 'If-None-Match': `"${meta.v}"` } : {}, cache: 'no-store' });
      } catch (e) { return 'error'; }
      if (res.status === 429) return 'ok';
      if (res.status === 401 || res.status === 403 || res.status === 409) { if (res.status !== 401) await c.wipeRoster(); return 'denied'; }
      const fetchedAt = d.now();
      if (res.status === 304 && meta) {
        await c.db.put('meta', { ...meta, fetched_at: fetchedAt, expires_at: fetchedAt + (meta.max_age_s || 86400) * 1000 });
        return 'ok';
      }
      if (!res.ok) return 'error';
      const body = await res.json();
      await c.db.replaceRoster(body.people, { v: body.v, generated_at: body.generated_at, salt: body.salt, count: body.count, max_age_s: body.max_age_s,
        event_id: body.event && body.event.id, fetched_at: fetchedAt, expires_at: fetchedAt + (body.max_age_s || 86400) * 1000 });
      return 'ok';
    };

    /* --- registro sin red --- */
    c.queueList = async () => (c.db ? c.db.getAll('queue') : []);
    /* Busca la cédula en el roster local. status: 'found' (+ person, duplicate) | 'not_found' | 'expired'. `duplicate`: ya consta como registrado (copia local o cola de este quiosco). */
    c.scanLocal = async (raw) => {
      const meta = await c.rosterMeta();
      if (!meta || !meta.expires_at || d.now() >= meta.expires_at) return { status: 'expired' };
      const cedula = normalize(raw);
      const person = cedula ? await c.db.get('roster', await c.fingerprint(meta.salt, cedula)) : null;
      if (!person) return { status: 'not_found' };
      const queued = (await c.queueList()).some((q) => q.h === person.h);
      return { status: 'found', person, cedula, duplicate: queued || person.s !== 'No registrado', queued };
    };
    /* Encola el ingreso (client_id + marca de tiempo) y lo anota como registrado en la copia local. El servidor lo marcará para revisión al sincronizar si otro quiosco lo admitió. */
    c.enqueue = async (found, method, clientId) => {
      const rec = { client_id: clientId || uuid(), cedula: found.cedula, h: found.person.h, timestamp: new Date(d.now()).toISOString(), method: method === 'qr' ? 'qr' : 'cedula' };
      await c.db.put('queue', rec);
      await c.db.put('roster', { ...found.person, s: 'Registrado' });
      c.queueSize = (await c.queueList()).length;
      render();
      return rec;
    };

    /* --- señales desde directory.js --- */
    c.noteScanExhausted = () => { if (c.supported && c.machine) c.machine.scanExhausted(); };
    c.noteAuthGood = () => { if (c.supported && c.machine) c.machine.authGood(); };

    /* --- franja visible --- */
    function render() {
      const doc = d.document;
      if (!doc || !doc.body) return;
      const st = c.supported ? c.machine.state : (c.lastError ? 'unsupported' : 'normal');
      if (st === 'normal') { if (c.banner) { c.banner.remove(); c.banner = null; } return; }
      if (!c.banner) {
        c.banner = doc.createElement('div');
        c.banner.setAttribute('role', 'status'); c.banner.setAttribute('aria-live', 'polite');
        doc.body.appendChild(c.banner);
      }
      const palette = { degraded: ['#fff8e1', '#7a5b00', '#f0ad4e'], contingency: ['#fbe9ea', '#a12631', '#dc3545'], unsupported: ['#eef1f5', '#44505c', '#8a96a3'] }[st];
      c.banner.style.cssText = `position:fixed; top:0; left:0; right:0; z-index:10000; padding:8px 14px; text-align:center; font-size:.9rem; font-weight:600; background:${palette[0]}; color:${palette[1]}; border-bottom:3px solid ${palette[2]};`;
      c.banner.dataset.state = st;
      c.banner.textContent = {
        degraded: 'Conexión inestable: si se corta, el quiosco pasará solo al modo contingencia.',
        contingency: `MODO CONTINGENCIA (sin conexión): se admite por cédula/QR con la copia local y se sincroniza al volver la red${c.queueSize ? ` · ${c.queueSize} en cola` : ''}. Quien no esté en la copia: verificar manualmente.`,
        unsupported: 'Este navegador no permite el modo contingencia: sin conexión no se podrá acreditar.',
      }[st];
    }
    c.render = render;

    /* --- arranque --- */
    const checkHealth = async () => {
      let ok = false;
      const ctl = typeof AbortController === 'function' ? new AbortController() : null;
      const timer = ctl ? d.setTimeout(() => ctl.abort(), HEALTH_TIMEOUT_MS) : null;
      try { const r = await d.fetch('/health', { cache: 'no-store', signal: ctl ? ctl.signal : undefined }); ok = !!(r && r.ok); } catch (e) { ok = false; } finally { if (timer) d.clearTimeout(timer); }
      c.machine.health(ok);
      if (c.machine.readyToProbe() && d.now() >= c.probeAfter) {          // 2 chequeos buenos: falta UNA petición autenticada buena
        const r = await c.refreshRoster();
        if (r === 'ok') c.machine.authGood(); else c.probeAfter = d.now() + PROBE_BACKOFF_MS;
      }
    };
    c.checkHealth = checkHealth;
    c.start = async (opts) => {
      if (opts && opts.eventId) d.eventId = opts.eventId;
      c.machine = createMachine((s) => { render(); c.listeners.forEach((f) => f(s)); });
      if (!c.isSupported()) { c.lastError = 'unsupported'; render(); return c; }
      try { c.db = await openStore(d.idb, `golden-contingency-${d.eventId}`); } catch (e) { c.lastError = 'unsupported'; render(); return c; }
      c.supported = true;
      c.queueSize = (await c.queueList()).length;
      const meta = await c.rosterMeta();
      if (meta && meta.expires_at && d.now() >= meta.expires_at) await c.wipeRoster();           // vencido mientras el navegador estaba cerrado
      c.refreshRoster().then((r) => { if (r === 'ok') c.machine.authGood(); });
      c.timers.push(d.setInterval(checkHealth, HEALTH_MS));
      c.timers.push(d.setInterval(async () => { if (c.machine.state !== 'contingency') { const r = await c.refreshRoster(); if (r === 'ok') c.machine.authGood(); } }, REFRESH_MS));
      return c;
    };
    c.stop = () => { c.timers.forEach((t) => d.clearInterval(t)); c.timers = []; if (c.db) { c.db.close(); c.db = null; } };
    return c;
  }

  const api = { create, createMachine, normalize, HEALTH_MS, HEALTH_TIMEOUT_MS, REFRESH_MS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GoldenContingency = Object.assign(api, { instance: null, init(opts) { this.instance = create(opts); return this.instance.start(opts); } });
})(typeof window !== 'undefined' ? window : globalThis);
