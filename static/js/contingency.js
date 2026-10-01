/* Modo contingencia del quiosco (Fase 3, docs/13 §9), cliente. Sin dependencias: solo IndexedDB (y crypto.subtle para la huella). Piezas:

   - Almacén (IndexedDB `golden-contingency-<evento>`): `roster` (huella → {h, n, c, s}), `queue` (ingresos hechos sin red: client_id, HUELLA h, nombre, marca de tiempo y método;
     NUNCA la cédula en claro), `review` (lo que el servidor marcó para revisar o no pudo registrar, hasta que el operador lo vea) y `meta` (versión, `expires_at`, sal).
   - Máquina de estados (normal / degradado / contingencia): chequeo de `/health` (3 s) cada 5 s; entra en contingencia tras 2 fallos seguidos o tras 2 escaneos consecutivos que
     agotaron sus reintentos; un fallo aislado solo deja «degradado»; sale tras 2 chequeos buenos seguidos Y una petición autenticada buena (`/api/ping-auth`; un 429 = servidor alcanzable).
     Con la sesión vencida (401) sigue en contingencia, la cola intacta y la franja pide iniciar sesión de nuevo.
   - Sincronización de la cola: lotes de hasta 500 a `/api/events/{id}/access-logs/sync` con espera creciente si falla; lo sincronizado se borra; los marcados «review» o desconocidos
     pasan a la lista de «revisar». Entradas con más de 30 días sin sincronizar se descartan con aviso.
   - Franja visible con `aria-live="polite"` y registro sin red (`scanLocal` + `enqueue`; directory.js pone los avisos). Si falta IndexedDB o crypto.subtle, `start()` avisa y deja el modo normal.
   Retención: el roster dura hasta que el evento finalice (403/409 → se borra, con aviso) y como máximo 24 h desde el último refresco (`expires_at`); se borra al cerrar sesión (static/js/toast.js);
   la cola se conserva hasta sincronizar. */
(function (root) {
  const HEALTH_MS = 5000, HEALTH_TIMEOUT_MS = 3000, REFRESH_MS = 4 * 60 * 1000, PROBE_BACKOFF_MS = 30000;
  const FAILS_TO_ENTER = 2, EXHAUSTED_TO_ENTER = 2, OKS_TO_LEAVE = 2;
  const SYNC_BATCH = 500, SYNC_BACKOFF_BASE_MS = 5000, SYNC_BACKOFF_MAX_MS = 5 * 60 * 1000, QUEUE_MAX_AGE_MS = 30 * 24 * 3600 * 1000;
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
  const STORES = { roster: 'h', queue: 'client_id', meta: 'k', review: 'client_id' };

  function openStore(idb, name) {
    return new Promise((resolve, reject) => {
      const r = idb.open(name, 2);
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

    const recount = async () => { c.queueSize = (await c.queueList()).length; c.reviewCount = (await c.db.getAll('review')).length; render(); };

    c.recount = recount;

    /* --- roster local --- */
    c.rosterMeta = async () => (c.db ? c.db.get('meta', 'roster') : null);
    c.rosterUsable = async () => { const m = await c.rosterMeta(); return !!(m && m.expires_at && d.now() < m.expires_at); };
    c.wipeRoster = async () => { if (c.db) await c.db.clear(['roster', 'meta']); };           // al cerrar sesión, al finalizar el evento y al vencer
    c.wipeAll = async () => { if (c.db) { await c.db.clear(['roster', 'meta', 'queue']); await recount(); } };      // la lista de «revisar» se conserva hasta que el operador la vea

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
        return 'ok';
      }
      if (!res.ok) return 'error';
      const body = await res.json();
      await c.db.replaceRoster(body.people, { v: body.v, generated_at: body.generated_at, salt: body.salt, count: body.count, max_age_s: body.max_age_s,
        event_id: body.event && body.event.id, auto_register: !!(body.event && body.event.auto_register), fetched_at: fetchedAt, expires_at: fetchedAt + (body.max_age_s || 86400) * 1000 });
      return 'ok';
    };

    /* --- registro sin red --- */
    c.queueList = async () => (c.db ? c.db.getAll('queue') : []);
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
    c.hashFor = async (raw) => { const meta = await c.rosterMeta(); const cedula = normalize(raw); return meta && cedula ? c.fingerprint(meta.salt, cedula) : ''; };
    c.localPeople = async () => ((await c.rosterUsable()) ? c.db.getAll('roster') : []);
    /* Encola el ingreso (client_id + marca de tiempo; huella y nombre, NO la cédula) y lo anota como registrado en la copia local. */
    c.enqueue = async (found, method, clientId) => {
      const rec = { client_id: clientId || uuid(), h: found.person.h, n: found.person.n, timestamp: new Date(d.now()).toISOString(), method: ['qr', 'manual'].includes(method) ? method : 'cedula' };
      await c.db.put('queue', rec);
      await c.db.put('roster', { ...found.person, s: 'Registrado' });
      await recount();
      return rec;
    };

    /* --- sincronización de la cola --- */
    const REASONS = { review: 'ya había ingresado por otro quiosco (o por otro registro) durante la desconexión: verificar', unknown: 'no se pudo registrar en el servidor (persona no encontrada en el evento): verificar manualmente' };
    const addReview = (rec, reason) => c.db.put('review', { client_id: rec.client_id, n: rec.n || '', reason, at: new Date(d.now()).toISOString() });
    const syncFail = (kind) => { c.syncFails++; c.nextSyncAt = d.now() + Math.min(SYNC_BACKOFF_MAX_MS, SYNC_BACKOFF_BASE_MS * 2 ** (c.syncFails - 1)); return kind || 'error'; };
    /* Envía la cola en lotes de hasta 500 (en orden de marca de tiempo). `force` ignora la espera (cierre de sesión). Devuelve 'empty' | 'ok' | 'wait' | 'offline' | 'busy' | 'session' | 'denied' | 'error'. */
    c.syncQueue = async (force) => {
      if (!c.supported || c.syncing) return 'busy';
      if (c.machine.state === 'contingency') return 'offline';
      if (!force && d.now() < c.nextSyncAt) return 'wait';
      c.syncing = true; render();
      let synced = 0;
      try {
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
              body: JSON.stringify({ records: q.map((r) => ({ client_id: r.client_id, h: r.h, timestamp: r.timestamp, method: r.method })) }) });
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
    /* Entradas con más de 30 días sin sincronizar: se descartan CON aviso (tope de retención de datos en el dispositivo). */
    c.pruneOld = async () => {
      const old = (await c.queueList()).filter((r) => d.now() - Date.parse(r.timestamp) > QUEUE_MAX_AGE_MS);
      if (!old.length) return 0;
      await c.db.del('queue', old.map((r) => r.client_id));
      c.notice = { kind: 'pruned', text: () => `${old.length} ingreso(s) llevaban más de 30 días sin sincronizar y se descartaron de este dispositivo: verificar manualmente.` };
      await recount();
      return old.length;
    };
    /* Antes de cerrar sesión: intenta sincronizar y devuelve cuántos ingresos siguen sin sincronizar (la cola se conserva). */
    c.beforeLogout = async () => { if (c.supported) { await c.syncQueue(true); await recount(); } return c.queueSize; };

    /* --- lista de «revisar» --- */
    c.reviewList = async () => (c.db ? c.db.getAll('review') : []);
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
    c.noteAuthGood = () => { if (c.supported && c.machine) c.machine.authGood(); };

    /* --- franja visible --- */
    function banner() {
      if (!c.supported) return c.lastError ? { st: 'unsupported', text: 'Este navegador no permite el modo contingencia: sin conexión no se podrá acreditar.' } : null;
      const n = c.queueSize, st = c.machine.state;
      if (c.sessionExpired && (st === 'contingency' || n > 0)) return { st: 'session', text: `Sesión vencida: inicia sesión de nuevo; ${n} ingreso(s) guardados se sincronizarán.`, link: true };
      if (st === 'contingency') return { st: 'contingency', text: `MODO CONTINGENCIA (sin conexión): se admite por cédula/QR con la copia local y se sincroniza al volver la red${n ? ` · ${n} en cola` : ''}. Quien no esté en la copia: verificar manualmente.` };
      if (c.notice) return { st: 'notice', text: c.notice.text(n), dismiss: true };
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
      if (!b) return;
      const el = doc.createElement('div');
      const palette = { degraded: ['#fff8e1', '#7a5b00', '#f0ad4e'], contingency: ['#fbe9ea', '#a12631', '#dc3545'], session: ['#fbe9ea', '#a12631', '#dc3545'], notice: ['#fff8e1', '#7a5b00', '#f0ad4e'],
        syncing: ['#e8f1fb', '#1d4f87', '#4a90d9'], review: ['#fff8e1', '#7a5b00', '#f0ad4e'], unsupported: ['#eef1f5', '#44505c', '#8a96a3'] }[b.st];
      el.setAttribute('role', 'status'); el.setAttribute('aria-live', 'polite');
      el.style.cssText = `position:fixed; top:0; left:0; right:0; z-index:10000; padding:8px 14px; text-align:center; font-size:.9rem; font-weight:600; background:${palette[0]}; color:${palette[1]}; border-bottom:3px solid ${palette[2]};`;
      el.dataset.state = b.st;
      el.setAttribute('data-golden-banner', '1');          // toast.js desplaza los avisos bajo esta franja
      el.textContent = b.text;
      const button = (label, fn) => { const x = doc.createElement('button'); x.textContent = label; x.style.cssText = `margin-left:10px; padding:2px 10px; border:1px solid ${palette[2]}; border-radius:6px; background:#fff; color:${palette[1]}; cursor:pointer; font-weight:600;`; x.addEventListener('click', fn); el.appendChild(x); return x; };
      if (b.link) { const a = doc.createElement('a'); a.textContent = 'Iniciar sesión'; a.setAttribute('href', '/login'); a.setAttribute('target', '_blank'); a.setAttribute('rel', 'noopener'); a.style.cssText = `margin-left:10px; color:${palette[1]}; text-decoration:underline;`; el.appendChild(a); }
      if (b.dismiss) button('Entendido', () => { c.notice = null; render(); });
      if (c.reviewCount > 0) button(`Revisar (${c.reviewCount})`, () => c.openReview());
      doc.body.appendChild(el);
      c.banner = el;
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
      try { const r = await d.fetch('/health', { cache: 'no-store', signal: ctl ? ctl.signal : undefined }); ok = !!(r && r.ok); } catch (e) { ok = false; } finally { if (timer) d.clearTimeout(timer); }
      c.machine.health(ok);
      if (c.machine.readyToProbe() && d.now() >= c.probeAfter) {          // 2 chequeos buenos: falta UNA petición autenticada buena
        const r = await c.probe();
        if (r === 'ok') { c.sessionExpired = false; c.machine.authGood(); render(); }
        else { if (r === 'unauth') c.sessionExpired = true; c.probeAfter = d.now() + PROBE_BACKOFF_MS; render(); }
      } else if (ok && c.machine.state !== 'contingency' && c.queueSize > 0) c.syncQueue();
    };
    c.checkHealth = checkHealth;
    c.start = async (opts) => {
      if (opts && opts.eventId) d.eventId = opts.eventId;
      c.machine = createMachine((s, from) => {
        render(); c.listeners.forEach((f) => f(s));
        if (s === 'normal' && from === 'contingency') { c.refreshRoster(); c.syncQueue(true); }       // volvió la red: copia al día y cola al servidor
      });
      if (!c.isSupported()) { c.lastError = 'unsupported'; render(); c.markReady(); return c; }
      try { c.db = await openStore(d.idb, `golden-contingency-${d.eventId}`); } catch (e) { c.lastError = 'unsupported'; render(); c.markReady(); return c; }
      c.supported = true;
      if (d.document && d.document.head && d.document.createElement) {
        const st = d.document.createElement('style');
        st.textContent = '.btn-offline-accredit{display:none !important} body.golden-contingency .btn-offline-accredit{display:inline-block !important}';
        d.document.head.appendChild(st);
      }
      c.persistRequest = c.requestPersistence();                   // sin await: nunca bloquea el arranque
      await c.pruneOld();
      await recount();
      const meta = await c.rosterMeta();
      if (meta && meta.expires_at && d.now() >= meta.expires_at) await c.wipeRoster();           // vencido mientras el navegador estaba cerrado
      c.markReady();
      c.refreshRoster().then((r) => { if (r === 'ok') { c.machine.authGood(); c.syncQueue(); } });
      c.timers.push(d.setInterval(checkHealth, HEALTH_MS));
      c.timers.push(d.setInterval(async () => {
        if (c.machine.state !== 'contingency' && !c.eventFinished) { const r = await c.refreshRoster(); if (r === 'ok') c.machine.authGood(); }
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
