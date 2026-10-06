/* Autorización biométrica voluntaria del quiosco (L1). La CÁMARA no se enciende sin una aceptación de la PERSONA registrada para este evento; quien no acepta sigue por cédula/QR sin restricción.
   El texto es el LITERAL de la auditora (app/legal_texts.py), que llega del servidor con su huella (SHA-256); aquí solo se muestra y se devuelve la huella con la decisión. SIN CONSTANCIA hasta que
   la auditora emita la suya. Piezas:
   - `ensure(cedula)` (camino 1): consulta la aceptación (en línea, o con la copia local sin red) y, si falta, muestra la pantalla completa. Devuelve 'camera' | 'cedula'.
   - `clickFlow()` (camino 2, solo eventos con pre-cálculo autorizado): pantalla para quien se acerca; con el botón 1 pide un token de UN clic. Devuelve el token o null.
   - Cada decisión (aceptar / rechazar, con la declaración de mayoría de edad) se registra con un UUID generado aquí: en línea va al servidor; sin conexión queda en la cola local (`consents`) y se
     sincroniza al volver la red, sin duplicar. Nada de esto se escribe en consola ni se guarda en claro más de lo necesario (la cola local usa la huella, no la cédula). */
(function (root) {
  function create(deps) {
    const d = Object.assign({ document: root.document, fetch: root.fetch && root.fetch.bind(root), eventId: root.EVENT_ID, gc: () => (root.GoldenContingency && root.GoldenContingency.instance) || null,
      uuid: () => (root.crypto && root.crypto.randomUUID ? root.crypto.randomUUID() : null), now: () => Date.now(), device: 'quiosco' }, deps || {});
    const g = { block: null };
    const el = (tag, css, text) => { const e = d.document.createElement(tag); if (css) e.style.cssText = css; if (text != null) e.textContent = text; return e; };
    const J = { 'Content-Type': 'application/json' };

    /* Texto del evento: del servidor; sin red, el que viajó con la copia local. null = no hay texto (el evento ingresa por cédula/QR). */
    g.loadBlock = async () => {
      try {
        const r = await d.fetch(`/api/events/${d.eventId}/consent-text`, { cache: 'no-store' });
        if (r.ok) { g.block = await r.json(); return g.block; }
        if (r.status === 503) { g.block = null; return null; }                     // el texto aún tiene datos de la empresa sin completar: no se muestra nada que no sea el texto final
      } catch (e) { /* sin red: se usa la copia local */ }
      const gc = d.gc(), meta = gc && gc.supported ? await gc.rosterMeta() : null;
      g.block = meta && meta.consent && !(meta.consent.blocked || []).length ? meta.consent : null;
      return g.block;
    };

    /* ¿Hay aceptación vigente? {accepted, mode, source: 'server' | 'local'}. Sin red: bandera `a` de la copia local y decisiones locales pendientes (la última manda). */
    g.status = async (cedula) => {
      try {
        const r = await d.fetch(`/api/events/${d.eventId}/consent-status/${encodeURIComponent(cedula)}`, { cache: 'no-store' });
        if (r.ok) { const j = await r.json(); return { accepted: !!j.accepted, blocked: !!j.blocked, known: true, face: j.face, mode: j.mode, source: 'server' }; }
      } catch (e) { /* sin red */ }
      const gc = d.gc();
      if (gc && gc.supported) { const s = await gc.consentLocal(cedula); return { accepted: !!s.accepted, blocked: !!s.blocked, known: !!s.known, mode: (g.block && g.block.mode) || 'once', source: 'local' }; }
      return { accepted: false, known: false, mode: 'once', source: 'local' };
    };

    /* Registra la decisión. En línea al servidor; si no hay red, a la cola local. Devuelve 'server' | 'local' | null (no se pudo guardar: NO se avanza hacia la cámara). */
    g.record = async (cedula, decision, adult) => {
      const b = g.block;
      const entry = { id: d.uuid(), decision, adult: !!adult, text_hash: b.hash, version: b.version, device: d.device, at: new Date(d.now()).toISOString() };
      if (!entry.id) return null;
      try {
        const r = await d.fetch(`/api/events/${d.eventId}/consents`, { method: 'POST', headers: J, cache: 'no-store', body: JSON.stringify({ entries: [{ ...entry, user_id: cedula }] }) });
        if (r.ok) return 'server';
        if (r.status >= 400 && r.status < 500 && r.status !== 401) return null;     // rechazado por el servidor (datos o permisos): no se finge que quedó registrado
      } catch (e) { /* sin red */ }
      const gc = d.gc();
      if (!gc || !gc.supported) return null;
      const h = await gc.hashFor(cedula);
      if (!h) return null;
      await gc.consentAdd({ ...entry, h });
      return 'local';
    };

    /* Pantalla completa. every=true: botones cortos de `every_scan`. Devuelve {decision: 'accept'|'reject', adult}. */
    g.showScreen = (opts) => new Promise((resolve) => {
      const b = g.block, doc = d.document, every = !!(opts && opts.every);
      const ov = el('div', 'position:fixed; inset:0; z-index:10050; background:#fff; overflow:auto; padding:clamp(14px,4vw,40px); font-family:var(--font-body, sans-serif); color:#0a0e2e;');
      ov.setAttribute('role', 'dialog'); ov.setAttribute('aria-modal', 'true'); ov.setAttribute('aria-labelledby', 'consentTitle'); ov.dataset.consentScreen = every ? 'every' : 'full';
      const box = el('div', 'max-width:760px; margin:0 auto;');
      const yes = el('button', 'padding:14px 22px; border:none; border-radius:10px; background:#0a0e2e; color:#fff; font-weight:700; font-size:1rem; cursor:pointer;');
      const no = el('button', 'padding:14px 22px; border:2px solid #0a0e2e; border-radius:10px; background:#fff; color:#0a0e2e; font-weight:700; font-size:1rem; cursor:pointer;');
      yes.type = 'button'; no.type = 'button'; yes.dataset.action = 'accept'; no.dataset.action = 'reject';
      let chk = null;
      if (every) {
        const q = b.every_scan || {};
        const h = el('h2', 'margin:0 0 18px;', q.question || ''); h.id = 'consentTitle'; box.appendChild(h);
        yes.textContent = q.yes || ''; no.textContent = q.no || '';
      } else {
        const h = el('h2', 'margin:0 0 14px;', b.title); h.id = 'consentTitle'; box.appendChild(h);
        b.body.forEach((p) => { const e = el('p', 'white-space:pre-line; line-height:1.55; margin:0 0 12px;', p); box.appendChild(e); });
        yes.textContent = b.buttons[0]; no.textContent = b.buttons[1];
        if (b.adult_checkbox) {                                   // variante 1 (tercero): el texto de la auditora no trae la declaración de mayoría de edad → casilla aparte, obligatoria
          const lab = el('label', 'display:flex; gap:10px; align-items:flex-start; margin:14px 0; font-weight:600;');
          chk = d.document.createElement('input'); chk.type = 'checkbox'; chk.style.cssText = 'width:20px; height:20px; margin-top:2px;'; chk.id = 'consentAdult';
          lab.appendChild(chk); lab.appendChild(el('span', '', b.adult_checkbox)); box.appendChild(lab);
          yes.disabled = true; yes.style.opacity = '.5'; yes.style.cursor = 'not-allowed';
          chk.addEventListener('change', () => { yes.disabled = !chk.checked; yes.style.opacity = chk.checked ? '1' : '.5'; yes.style.cursor = chk.checked ? 'pointer' : 'not-allowed'; });
        }
      }
      const row = el('div', 'display:flex; gap:12px; flex-wrap:wrap; margin-top:18px;'); row.appendChild(yes); row.appendChild(no); box.appendChild(row);
      ov.appendChild(box); doc.body.appendChild(ov);
      const adult = () => every || !b.adult_checkbox || !!(chk && chk.checked);      // variante 2: la declaración va DENTRO del texto del botón 1; variante 1: casilla aparte
      const done = (decision) => { ov.remove(); resolve({ decision, adult: decision === 'accept' && adult() }); };
      yes.addEventListener('click', () => { if (!yes.disabled) done('accept'); });
      no.addEventListener('click', () => done('reject'));
      if (typeof no.focus === 'function') no.focus();
    });

    /* CAMINO 1: cédula/QR primero. 'camera' solo con aceptación vigente (ya registrada o dada ahora); 'cedula' = sigue por cédula/QR. */
    g.ensure = async (cedula) => {
      if (!g.block) await g.loadBlock();
      if (!g.block) return 'cedula';
      const st = await g.status(cedula);
      if (st.blocked) return 'cedula';                           // menor de 18 años: ni pantalla de autorización ni cámara, solo cédula/QR
      const offline = st.source === 'local';                     // sin servidor no hay reconocimiento facial: la decisión se registra (cola local) pero la puerta sigue por cédula/QR
      if (offline && !st.known) return 'cedula';                 // alguien que no está en la copia local no se puede identificar sin red
      const every = (g.block.mode || st.mode) === 'every_scan';
      const face = st.face || 'none';                            // 'ready' (hay vector) | 'pending' (se está calculando) | 'none'
      const go = () => (face === 'ready' ? 'camera' : face === 'pending' ? 'pending' : 'enroll');      // sin vector: captura en vivo y el vector se calcula aparte (la puerta no espera)
      if (st.accepted && !every) return offline ? 'cedula' : go();
      if (st.accepted && every) {                               // cada uso: botones cortos; la autorización completa ya consta
        const r = await g.showScreen({ every: true });
        return r.decision === 'accept' && !offline ? go() : 'cedula';
      }
      const r = await g.showScreen({});
      const saved = await g.record(cedula, r.decision, r.adult);
      if (!saved) return 'cedula';
      return r.decision === 'accept' && r.adult && saved === 'server' ? go() : 'cedula';
    };

    /* CAMINO 2: la persona se acerca, ve la pantalla y pulsa el botón 1 → token de UN clic (el servidor solo lo da si el evento tiene el pre-cálculo autorizado). null = botón 2 o sin token. */
    g.clickFlow = async () => {
      if (!g.block) await g.loadBlock();
      if (!g.block || !g.block.click_mode) return null;
      const r = await g.showScreen({});
      if (r.decision !== 'accept' || !r.adult) return null;
      try {
        const res = await d.fetch(`/api/events/${d.eventId}/consent-click`, { method: 'POST', cache: 'no-store' });
        if (res.ok) return (await res.json()).click_token || null;
      } catch (e) { /* sin red no hay rostro: cédula/QR */ }
      return null;
    };
    return g;
  }
  const api = { create };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GoldenConsent = api;
})(typeof window !== 'undefined' ? window : globalThis);
