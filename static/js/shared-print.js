/* Impresión compartida + impresión directa por USB (Brother QL-800, cinta continua de 62 mm) en la pantalla de Registro. Orden del 22-oct-2026.

   SOLO se carga si el evento tiene «Impresión compartida» encendida (kiosk_registro.html): con el interruptor apagado, la impresión es exactamente la de siempre.

   - Cada equipo reporta cada 10 s su plataforma, navegador y si tiene la impresora USB conectada (POST print-devices/heartbeat). El servidor responde dónde
     imprime este usuario («en su propio equipo» o «en el equipo de Y») y si este equipo atiende a otros (entonces pregunta por trabajos cada 1,5 s).
   - Imprimir (automático al registrar, o el botón «Imprimir escarapela»):
       · en su propio equipo con la impresora USB conectada → se dibuja la escarapela (BadgeRender + html2canvas) y se manda por USB (QLUsb), sin diálogo;
       · en su propio equipo sin impresora USB → la ventana de impresión de siempre;
       · en el equipo de Y → se crea un trabajo (con un id propio: un reintento no duplica) y se sigue su estado; «Impreso en Y», o el aviso y la cola visible.
   - El equipo Y imprime lo que el servidor le reserva (nunca dos veces: el servidor no vuelve a entregar un trabajo reservado) y confirma impreso/fallido.
   - Reconexión de la impresora sin pedir permiso de nuevo (navigator.usb.getDevices), pantalla siempre encendida (Wake Lock) y avisos si se pierde la conexión.
   - «Registro touch» (recordado en este equipo): botones grandes, solo lo esencial, el campo del lector conserva el foco y no abre el teclado (con botón para abrirlo). */
(function () {
  'use strict';
  const EID = window.EVENT_ID;
  const HEARTBEAT_MS = 10000;
  const POLL_MS = 1500;
  const FOLLOW_MS = 1000;
  const BUSY_RETRY_MS = 4000;            // impresora tomada por otra pestaña de este equipo: se reintenta sola cada 4 s
  const FOLLOW_MAX = 20;                 // segundos que X sigue el estado de su trabajo antes de dejarlo en la cola visible
  const original = window.BadgePrint || {};
  const toast = (msg, kind) => (window.showToast ? window.showToast(msg, kind || 'info') : null);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const uuid = () => (window.crypto && crypto.randomUUID ? crypto.randomUUID() : `r${Date.now()}${Math.random().toString(16).slice(2)}`);
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* sin almacenamiento: vale para esta sesión */ } },
  };

  const deviceId = (() => { let v = store.get('gw_device_id', ''); if (!v) { v = uuid(); store.set('gw_device_id', v); } return v; })();
  const ua = navigator.userAgent || '';
  const platform = /Android/i.test(ua) ? 'Android' : /iPhone|iPad/i.test(ua) ? 'iOS' : /Windows/i.test(ua) ? 'Windows' : /Mac OS/i.test(ua) ? 'Mac' : /Linux/i.test(ua) ? 'Linux' : 'Otro';
  const browser = /EdgA?\//.test(ua) ? 'Edge' : /SamsungBrowser/.test(ua) ? 'Samsung Internet' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox' : /Safari\//.test(ua) ? 'Safari' : 'Otro';

  let route = { mode: 'self', printer_name: '', printer_ready: false, serving: 0, poll: false };
  let usb = { ok: false, name: '', lastError: '', busy: false };
  let online = true;
  let pending = 0;                       // trabajos de este equipo pendientes de confirmar

  /* ------------------------------------------------------------------ barra de estado */
  const bar = document.createElement('div');
  bar.id = 'sharedPrintBar';
  bar.setAttribute('role', 'status');
  bar.setAttribute('aria-live', 'polite');
  bar.innerHTML = '<span class="sp-dot" aria-hidden="true"></span><span class="sp-text">Impresión: comprobando…</span>' +
    '<button type="button" class="sp-btn" id="spConnect">🔌 Conectar impresora</button>' +
    '<button type="button" class="sp-btn" id="spQueue">🧾 Cola</button>' +
    '<button type="button" class="sp-btn" id="spPrefs">⚙️ Impresión</button>' +
    '<button type="button" class="sp-btn" id="spTouch" aria-pressed="false">📱 Registro touch</button>' +
    '<button type="button" class="sp-btn" id="spKeyboard" hidden>⌨️ Teclado</button>';
  const style = document.createElement('style');
  style.textContent = [
    '#sharedPrintBar{position:sticky;top:0;z-index:50;display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:8px 12px;margin:0 0 12px;border-radius:12px;background:#fff;border:2px solid #d0d4de;font-size:0.95rem}',
    '#sharedPrintBar .sp-dot{width:14px;height:14px;border-radius:50%;background:#999;flex:none}',
    '#sharedPrintBar.ok .sp-dot{background:#1e7e34}#sharedPrintBar.warn .sp-dot{background:#b26a00}#sharedPrintBar.bad .sp-dot{background:#a12631}',
    '#sharedPrintBar.bad{border-color:#a12631;background:#fdeeee}#sharedPrintBar.warn{border-color:#b26a00;background:#fff6e5}',
    '#sharedPrintBar .sp-text{flex:1 1 220px;font-weight:600}',
    '#sharedPrintBar .sp-btn{min-height:44px;padding:6px 14px;border-radius:10px;border:2px solid #0a0e2e;background:#fff;color:#0a0e2e;font-weight:700;cursor:pointer}',
    '#spQueuePanel{position:fixed;inset:auto 12px 12px 12px;max-height:60vh;overflow:auto;z-index:9998;background:#fff;border:2px solid #0a0e2e;border-radius:14px;padding:12px;box-shadow:0 10px 40px rgba(0,0,0,.25)}',
    '#spPrefsPanel{position:fixed;inset:auto 12px 12px 12px;max-height:80vh;overflow:auto;z-index:9998;background:#fff;border:2px solid #0a0e2e;border-radius:14px;padding:14px;box-shadow:0 10px 40px rgba(0,0,0,.25);font-size:1rem}',
    '#spPrefsPanel label{display:flex;gap:10px;align-items:center;min-height:44px}#spPrefsPanel input[type=checkbox],#spPrefsPanel input[type=radio]{width:24px;height:24px}#spPrefsPanel input[type=number]{width:90px;min-height:40px;font-size:1rem}',
    '#spQueuePanel table{width:100%;border-collapse:collapse;font-size:0.95rem}#spQueuePanel td,#spQueuePanel th{padding:6px;border-bottom:1px solid #eee;text-align:left}',
    /* Registro touch: lo esencial, grande y a un dedo */
    'body.touch-mode{font-size:18px}',
    'body.touch-mode input[type=text],body.touch-mode input[type=search]{min-height:56px;font-size:1.25rem !important}',
    'body.touch-mode button,body.touch-mode .golden-btn,body.touch-mode .small-btn{min-height:52px;font-size:1.05rem !important;padding-left:18px !important;padding-right:18px !important}',
    'body.touch-mode #searchNombre,body.touch-mode #searchEntidad,body.touch-mode #clearFiltersBtn,body.touch-mode .golden-sidebar-toggle{display:none !important}',
    'body.touch-mode label[for],body.touch-mode .badge-input-group label{font-size:1rem}',
  ].join('\n');
  document.head.appendChild(style);

  function mount() {
    const anchor = document.querySelector('.golden-container .tabs');        // encima de las pestañas: se ve en todas (Registro, Escáner, Directorio)
    if (anchor) anchor.parentNode.insertBefore(bar, anchor); else (document.querySelector('main') || document.body).prepend(bar);
  }

  function render() {
    const text = bar.querySelector('.sp-text');
    let kind = 'ok';
    let msg;
    if (!online) { kind = 'bad'; msg = 'Sin conexión con el servidor: la impresión compartida no funciona hasta que vuelva la red.'; }
    else if (route.mode === 'shared') {
      msg = route.printer_ready ? `Imprime en el equipo de ${route.printer_name}.` : `Imprime en el equipo de ${route.printer_name}, que NO está conectado con su impresora: las escarapelas quedan en cola.`;
      if (!route.printer_ready) kind = 'warn';
    } else if (usb.busy) {
      kind = 'warn';
      msg = `${QLUsb.BUSY_MSG} Se vuelve a intentar sola cada pocos segundos.`;
    } else if (usb.ok) {
      msg = `Impresora conectada (${usb.name}).` + (route.serving ? ` Imprime también para ${route.serving} equipo(s).` : '');
    } else {
      kind = route.serving ? 'bad' : 'warn';
      msg = route.serving ? `Impresora DESCONECTADA: ${route.serving} equipo(s) imprimen aquí y sus escarapelas quedan en cola. Conéctela.`
        : 'Sin impresora USB: se usará la impresión normal del navegador.';
    }
    if (pending) msg += ` · ${pending} por confirmar`;
    text.textContent = msg;
    bar.className = kind;
    bar.querySelector('#spConnect').hidden = usb.ok || usb.busy || route.mode === 'shared' || !(window.QLUsb && QLUsb.supported());
  }

  /* ------------------------------------------------------------------ impresora USB */
  let busyTimer = null;
  async function connectUsb(ask) {
    clearTimeout(busyTimer);
    if (!ask && usb.ok && window.QLUsb && QLUsb.info()) { render(); heartbeat(); return; }      // ya conectada: no se vuelve a abrir
    if (!(window.QLUsb && QLUsb.supported())) { usb = { ok: false, name: '', lastError: 'USB no disponible en este navegador', busy: false }; render(); return; }
    try {
      const d = await QLUsb.connect(ask);
      usb = { ok: !!d, name: d ? (d.productName || 'Brother') : '', lastError: '', busy: false };
    } catch (e) {
      const busy = !!(e && e.busy);                    // otra pestaña de este equipo tiene la impresora: aviso amable y reintento solo, sin desconectar el cable
      usb = { ok: false, name: '', lastError: e && e.message ? e.message : String(e), busy };
      if (busy) busyTimer = setTimeout(() => connectUsb(false), BUSY_RETRY_MS);
      else if (ask) toast('No se pudo conectar la impresora: ' + usb.lastError, 'error');
    }
    render();
    heartbeat();
  }
  if (window.QLUsb && QLUsb.supported()) {
    navigator.usb.addEventListener('connect', () => connectUsb(false));
    navigator.usb.addEventListener('disconnect', async () => {
      await QLUsb.close();
      usb = { ok: false, name: '', lastError: 'desconectada', busy: false };
      render();
      toast('⚠️ Se desconectó la impresora USB.', 'warning');
      heartbeat();
    });
  }

  /* ------------------------------------------------------------------ pantalla siempre encendida */
  let wakeLock = null;
  async function keepAwake() {
    try { if ('wakeLock' in navigator && document.visibilityState === 'visible' && !wakeLock) { wakeLock = await navigator.wakeLock.request('screen'); wakeLock.addEventListener('release', () => { wakeLock = null; }); } } catch (e) { /* el sistema no lo permitió: se reintenta al volver */ }
  }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') { keepAwake(); heartbeat(); connectUsb(false); } });

  /* ------------------------------------------------------------------ señal con el servidor */
  let hbTimer = null;
  async function heartbeat() {
    clearTimeout(hbTimer);
    try {
      const res = await fetch(`/api/events/${EID}/print-devices/heartbeat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store',
        body: JSON.stringify({ device_id: deviceId, platform, browser, printer_connected: usb.busy ? null : usb.ok, printer_name: usb.name || null }) });      // null: otra pestaña es la dueña, no se pisa su estado
      online = true;
      if (res.ok) { route = await res.json(); startPolling(); }
    } catch (e) { online = false; }
    render();
    hbTimer = setTimeout(heartbeat, HEARTBEAT_MS);
  }

  /* ------------------------------------------------------------------ dibujar e imprimir por USB */
  const stage = document.createElement('div');
  stage.setAttribute('aria-hidden', 'true');
  stage.style.cssText = 'position:fixed; left:-10000px; top:0; background:#fff;';
  document.body.appendChild(stage);

  async function badgeBitmap(userId) {
    const dataRes = await fetch(`/api/users/${encodeURIComponent(userId)}/badge-print-data?event_id=${EID}`, { cache: 'no-store' });
    if (!dataRes.ok) throw new Error('No se encontró la persona en este evento.');
    const data = await dataRes.json();
    const qs = data.template_category ? `?category=${encodeURIComponent(data.template_category)}` : '';
    const tplRes = await fetch(`/api/events/${EID}/badge-template${qs}`, { cache: 'no-store' });
    if (!tplRes.ok) throw new Error('El evento no tiene plantilla de escarapela.');
    const template = await tplRes.json();
    const holder = document.createElement('div');
    stage.appendChild(holder);
    try {
      BadgeRender.renderBadge(holder, template, data, { eventId: EID });
      if (document.fonts && document.fonts.ready) await document.fonts.ready;
      await Promise.all(Array.from(holder.querySelectorAll('img')).map((img) => (img.decode ? img.decode().catch(() => {}) : null)));
      const DOTS = QLUsb.MEDIA[62].printable;
      const scale = DOTS / holder.offsetWidth;
      const shot = await html2canvas(holder, { scale, useCORS: true, backgroundColor: '#ffffff', logging: false });
      const p = prefs();
      const drawn = Math.max(1, Math.round(shot.height * DOTS / shot.width));          // alto de la PLANTILLA (a escala del ancho imprimible de 62 mm)
      const height = p.lengthMm ? QLUsb.mmToDots(p.lengthMm) : drawn;                  // o el alto fijo que se eligió en «⚙️ Impresión»
      return jobFromCanvas((ctx) => ctx.drawImage(shot, 0, 0, DOTS, drawn), height, p);
    } finally {
      holder.remove();
    }
  }

  /* Preferencias de impresión de ESTE equipo (las mismas que /impresion-usb): corte automático, margen de avance, alto de etiqueta, espejo e invertir. */
  function prefs() { let ls = null; try { ls = window.localStorage; } catch (e) { /* bloqueado */ } return QLUsb.readPrefs(ls); }
  function jobFromCanvas(draw, height, p) {
    const DOTS = QLUsb.MEDIA[62].printable;
    const canvas = document.createElement('canvas');
    canvas.width = DOTS; canvas.height = height;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, DOTS, height);
    draw(ctx);
    const rgba = ctx.getImageData(0, 0, DOTS, height).data;
    return QLUsb.buildJob({ bitmap: QLUsb.bitmapFromRGBA(rgba, DOTS, height, 140, p.invert), height, mediaWidthMm: 62, mirror: p.mirror, autoCut: p.cut,
      feedDots: QLUsb.mmToDots(p.feedMm) });
  }

  let usbBusy = Promise.resolve();
  function printUsb(userId) {                       // una impresión a la vez por equipo (la impresora no admite dos flujos a la vez)
    const run = usbBusy.then(async () => {
      if (!usb.ok || !QLUsb.info()) await connectUsb(false);
      if (!usb.ok) throw new Error('La impresora no está conectada.');
      await QLUsb.sendJob(await badgeBitmap(userId));
    });
    usbBusy = run.catch(() => {});
    return run;
  }

  async function logPrint(userId) {
    try { await fetch(`/api/users/${encodeURIComponent(userId)}/print-log?event_id=${EID}`, { method: 'POST' }); } catch (e) { /* no bloquea */ }
  }

  /* ------------------------------------------------------------------ Y: atender a otros equipos */
  let polling = false;
  async function startPolling() {
    if (polling || !route.poll || !usb.ok) return;
    polling = true;
    while (route.poll && usb.ok) {
      let job = null;
      try {
        const res = await fetch(`/api/events/${EID}/print-jobs-next`, { cache: 'no-store' });
        if (res.ok) job = (await res.json()).job;
      } catch (e) { online = false; render(); }
      if (job) {
        let ok = false;
        let error = '';
        try { await printUsb(job.user_id); ok = true; } catch (e) { error = e && e.message ? e.message : String(e); }
        for (let i = 0; i < 3; i++) {             // la confirmación se reintenta: si se pierde, el trabajo caduca (nunca se reimprime solo)
          try {
            const r = await fetch(`/api/events/${EID}/print-jobs/${job.id}/result`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ok, error }) });
            if (r.ok) break;
          } catch (e) { await sleep(1000); }
        }
        if (!ok) toast(`⚠️ No se pudo imprimir la escarapela que pidió ${job.requested_by || 'otro equipo'}: ${error}`, 'error');
        continue;                                   // hay trabajo: se pregunta de nuevo enseguida
      }
      await sleep(POLL_MS);
    }
    polling = false;
  }

  /* ------------------------------------------------------------------ X: mandar a otro equipo y seguir el estado */
  async function sendToPrinter(userId) {
    const requestId = uuid();
    let job = null;
    for (let i = 0; i < 2 && !job; i++) {           // el mismo request_id: si la primera respuesta se perdió, el servidor no duplica
      try {
        const res = await fetch(`/api/events/${EID}/print-jobs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: userId, request_id: requestId }) });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) { toast(`⚠️ No se pudo enviar la escarapela a imprimir: ${body.detail || res.status}`, 'error'); return; }
        job = body;
      } catch (e) { await sleep(800); }
    }
    if (!job) { toast('⚠️ Sin conexión: la escarapela NO se envió a imprimir. Reintente con «Imprimir escarapela».', 'error'); return; }
    if (job.warning) toast('⚠️ ' + job.warning, 'warning');
    pending += 1; render();
    try {
      for (let s = 0; s < FOLLOW_MAX; s++) {
        await sleep(FOLLOW_MS);
        let st = null;
        try { const r = await fetch(`/api/events/${EID}/print-jobs/${job.id}`, { cache: 'no-store' }); if (r.ok) st = await r.json(); } catch (e) { /* se reintenta */ }
        if (!st) continue;
        if (st.status === 'printed') { toast(`✅ Impreso en ${st.printer_name}.`, 'success'); return; }
        if (st.status === 'failed') { toast(`⚠️ Falló la impresión en ${st.printer_name}: ${st.error || ''}. Está en la cola para reimprimir.`, 'error'); return; }
        if (st.status === 'expired') { toast('⚠️ La escarapela caducó sin imprimirse. Está en la cola para reimprimir.', 'error'); return; }
      }
      toast(`⚠️ Todavía no se confirma la impresión en ${job.printer_name}. Revise la «Cola».`, 'warning');
    } finally { pending -= 1; render(); }
  }

  /* ------------------------------------------------------------------ la cola visible */
  const STATUS = { queued: 'En cola', sent: 'Enviada', failed: 'Falló', expired: 'Caducó' };
  async function showQueue() {
    const old = document.getElementById('spQueuePanel');
    if (old) { old.remove(); return; }
    const panel = document.createElement('div');
    panel.id = 'spQueuePanel';
    panel.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px"><strong>Escarapelas sin imprimir (últimas 4 h)</strong><button type="button" class="sp-btn" data-close>Cerrar</button></div><div data-body>Cargando…</div>';
    document.body.appendChild(panel);
    panel.addEventListener('click', async (e) => {
      if (e.target.closest('[data-close]')) { panel.remove(); return; }
      const btn = e.target.closest('[data-reprint]');
      if (!btn) return;
      if (!(await window.showConfirm(`¿Reimprimir la escarapela de ${btn.dataset.reprint}?`, { confirmLabel: 'Sí, reimprimir' }))) return;
      btn.disabled = true;
      await printFor(btn.dataset.reprint, false, true);
      panel.remove();
    });
    const body = panel.querySelector('[data-body]');
    try {
      const res = await fetch(`/api/events/${EID}/print-jobs`, { cache: 'no-store' });
      const data = res.ok ? await res.json() : { jobs: [] };
      if (!data.jobs.length) { body.textContent = 'No hay escarapelas pendientes.'; return; }
      const table = document.createElement('table');
      table.innerHTML = '<tr><th>Cédula</th><th>Estado</th><th>Equipo</th><th></th></tr>';
      data.jobs.forEach((j) => {
        const tr = document.createElement('tr');
        [j.user_id, (STATUS[j.status] || j.status) + (j.printed_later ? ' (ya se imprimió después)' : ''), j.printer_name].forEach((t) => { const td = document.createElement('td'); td.textContent = t || ''; tr.appendChild(td); });
        const td = document.createElement('td');
        if (j.status !== 'queued' && j.status !== 'sent') {
          const b = document.createElement('button'); b.type = 'button'; b.className = 'sp-btn'; b.textContent = 'Reimprimir'; b.dataset.reprint = j.user_id; td.appendChild(b);
        }
        tr.appendChild(td);
        table.appendChild(tr);
      });
      body.replaceChildren(table);
    } catch (e) { body.textContent = 'Sin conexión con el servidor.'; }
  }

  /* ------------------------------------------------------------------ el punto único de impresión */
  /* Orden del 22-oct-2026: SOLO se imprime a quien está «Registrado» en este evento (botón, autoimpresión, Cola; local o compartida). El servidor también lo
     valida al crear el trabajo compartido. Si no se puede comprobar, NO se imprime. */
  async function registeredOrSay(userId) {
    for (let i = 0; i < 2; i++) {
      try {
        const r = await fetch(`/api/events/${EID}/print-check/${encodeURIComponent(userId)}`, { cache: 'no-store' });
        const c = await r.json().catch(() => ({}));
        if (r.ok && c.registered) return true;
        toast(c.detail || 'No se pudo comprobar si la persona está registrada: no se imprime.', 'error');
        return false;
      } catch (e) { await sleep(600); }
    }
    toast('⚠️ Sin conexión: no se pudo comprobar si la persona está registrada. No se imprime; reintenta.', 'error');
    return false;
  }

  async function printFor(userId, auto, confirmed) {
    if (!(await registeredOrSay(userId))) return;
    if (route.mode === 'shared') {
      if (!auto && !confirmed) {                    // el botón manual conserva el aviso de reimpresión de siempre
        try {
          const r = await fetch(`/api/users/${encodeURIComponent(userId)}/print-count?event_id=${EID}`);
          const c = r.ok ? await r.json() : { times_printed: 0 };
          if (c.times_printed > 0 && !(await window.showConfirm(`⚠️ Ya se ha impreso esta escarapela (${c.times_printed} ${c.times_printed === 1 ? 'vez' : 'veces'}).<br><br>¿Deseas imprimir de nuevo?`,
            { variant: 'warning', confirmLabel: 'Sí, imprimir de nuevo' }))) return;
        } catch (e) { /* si falla la consulta, no bloquea */ }
      }
      return sendToPrinter(userId);
    }
    if (usb.ok) {
      try {
        if (!auto && !confirmed && original.openPrintWindow) { /* el aviso de reimpresión de siempre */
          const r = await fetch(`/api/users/${encodeURIComponent(userId)}/print-count?event_id=${EID}`).catch(() => null);
          const c = r && r.ok ? await r.json() : { times_printed: 0 };
          if (c.times_printed > 0 && !(await window.showConfirm(`⚠️ Ya se ha impreso esta escarapela (${c.times_printed} ${c.times_printed === 1 ? 'vez' : 'veces'}).<br><br>¿Deseas imprimir de nuevo?`,
            { variant: 'warning', confirmLabel: 'Sí, imprimir de nuevo' }))) return;
        }
        await printUsb(userId);
        await logPrint(userId);
        toast('🖨️ Escarapela impresa.', 'success');
        return;
      } catch (e) {
        toast(`⚠️ No se pudo imprimir por USB (${e && e.message ? e.message : e}). Se abre la impresión normal.`, 'warning');
      }
    }
    return auto ? original.maybeAutoPrint(userId) : original.openPrintWindow(userId);
  }

  window.BadgePrint = Object.assign({}, original, {
    maybeAutoPrint(userId) { if (!window.EVENT_AUTO_PRINT) return; printFor(userId, true); },
    openPrintWindow(userId) { return printFor(userId, false); },
  });

  /* ------------------------------------------------------------------ Registro touch */
  const READER_IDS = ['searchCedula', 'regScanCedulaInput', 'bioCedula'];
  let touch = store.get('gw_touch_mode', '0') === '1';
  let keyboard = false;
  function readerField() { return READER_IDS.map((id) => document.getElementById(id)).find((el) => el && el.offsetParent !== null) || null; }
  function applyTouch() {
    document.body.classList.toggle('touch-mode', touch);
    const tbtn = bar.querySelector('#spTouch');
    tbtn.setAttribute('aria-pressed', touch ? 'true' : 'false');
    tbtn.textContent = touch ? '📱 Registro touch: ACTIVADO' : '📱 Registro touch';
    const kbtn = bar.querySelector('#spKeyboard');
    kbtn.hidden = !touch;
    kbtn.textContent = keyboard ? '⌨️ Ocultar teclado' : '⌨️ Teclado';
    READER_IDS.forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (!el.dataset.origInputmode) el.dataset.origInputmode = el.getAttribute('inputmode') || '';
      if (touch && !keyboard) el.setAttribute('inputmode', 'none');              // el lector USB escribe como teclado: sin abrir el teclado en pantalla
      else if (el.dataset.origInputmode) el.setAttribute('inputmode', el.dataset.origInputmode); else el.removeAttribute('inputmode');
    });
  }
  bar.querySelector('#spTouch').addEventListener('click', () => { touch = !touch; keyboard = false; store.set('gw_touch_mode', touch ? '1' : '0'); applyTouch(); const f = readerField(); if (touch && f) f.focus(); });
  bar.querySelector('#spKeyboard').addEventListener('click', () => { keyboard = !keyboard; applyTouch(); const f = readerField(); if (f) { f.blur(); setTimeout(() => f.focus(), 50); } });
  document.addEventListener('focusout', () => {                                   // el campo del lector recupera el foco (salvo que se esté usando otro campo o un diálogo)
    if (!touch) return;
    setTimeout(() => {
      const a = document.activeElement;
      if (a && a !== document.body && a.closest && !a.closest('#sharedPrintBar')) return;
      if (document.querySelector('[role="dialog"], .toast-confirm, #spQueuePanel')) return;
      const f = readerField();
      if (f) f.focus({ preventScroll: true });
    }, 250);
  });

  /* ------------------------------------------------------------------ arranque */
  /* ------------------------------------------------------------------ Enter del teclado en pantalla = buscar (como el lector USB) */
  /* En Android, la tecla de acción del teclado en pantalla pasaba al campo siguiente («Siguiente») en vez de buscar. Con enterkeyhint="search" Chrome manda Enter;
     y si el teclado no lo manda como tecla (keyCode 229, Samsung, etc.) se toma el salto de línea (beforeinput) o el Enter al soltar (keyup) y se manda un Enter.
     El lector USB ya manda Enter normal: no cambia (y no se repite: un Enter en el último segundo cuenta una sola vez). */
  const SEARCH_IDS = ['searchCedula', 'searchNombre', 'searchEntidad', 'regScanCedulaInput'];
  const ENTER_ONCE_MS = 1000;
  function wireEnter() {
    SEARCH_IDS.forEach((id) => document.querySelectorAll(`#${id}`).forEach((el) => {
      if (el.dataset.spEnter) return;
      el.dataset.spEnter = '1';
      el.setAttribute('enterkeyhint', 'search');
      let lastEnter = 0;
      const fire = () => { lastEnter = Date.now(); el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true })); };
      el.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter') return;
        lastEnter = Date.now();
        if (id === 'searchNombre' || id === 'searchEntidad') { e.preventDefault(); el.dispatchEvent(new Event('input', { bubbles: true })); el.blur(); }      // busca ya y baja el teclado para ver el resultado
      });
      el.addEventListener('beforeinput', (e) => {
        if (e.inputType !== 'insertLineBreak' && e.inputType !== 'insertParagraph') return;
        e.preventDefault();
        if (Date.now() - lastEnter > ENTER_ONCE_MS) fire();
      });
      el.addEventListener('keyup', (e) => { if ((e.key === 'Enter' || e.keyCode === 13) && Date.now() - lastEnter > ENTER_ONCE_MS) fire(); });
    }));
  }

  /* ------------------------------------------------------------------ pegar en cédula (limpia espacios y puntos) */
  const CEDULA_IDS = ['searchCedula', 'regScanCedulaInput', 'manualIdField'];
  const cleanCedula = (t) => String(t || '').replace(/[\s.]/g, '');
  document.addEventListener('keydown', (e) => {          // el blindaje contra atajos del lector bloqueaba también Ctrl+V/C/X/A: esos sí se dejan pasar
    const t = e.target;
    if (!t || !CEDULA_IDS.includes(t.id) || e.altKey || !(e.ctrlKey || e.metaKey)) return;
    if (['v', 'c', 'x', 'a', 'z'].includes(String(e.key || '').toLowerCase())) e.stopImmediatePropagation();
  }, true);
  document.addEventListener('paste', (e) => {
    const t = e.target;
    if (!t || !CEDULA_IDS.includes(t.id) || !e.clipboardData) return;
    const raw = e.clipboardData.getData('text') || '';
    const clean = cleanCedula(raw);
    if (clean === raw) return;
    e.preventDefault();
    const s = t.selectionStart == null ? t.value.length : t.selectionStart, en = t.selectionEnd == null ? s : t.selectionEnd;
    t.value = t.value.slice(0, s) + clean + t.value.slice(en);
    try { t.setSelectionRange(s + clean.length, s + clean.length); } catch (err) { /* campo sin selección */ }
    t.dispatchEvent(new Event('input', { bubbles: true }));
  }, true);

  /* ------------------------------------------------------------------ «⚙️ Impresión»: preferencias de este equipo */
  function showPrefs() {
    const old = document.getElementById('spPrefsPanel');
    if (old) { old.remove(); return; }
    const p = prefs();
    const panel = document.createElement('div');
    panel.id = 'spPrefsPanel';
    panel.setAttribute('role', 'dialog');
    panel.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px"><strong>Preferencias de impresión de este equipo</strong><button type="button" class="sp-btn" data-close>Cerrar</button></div>' +
      '<label><input type="checkbox" data-p="cut"> Cortar la cinta al final de cada etiqueta</label>' +
      '<label>Margen de avance <input type="number" data-p="feed" min="0" max="10" step="0.5"> mm</label>' +
      '<label><input type="radio" name="spLen" value="auto"> Alto de etiqueta: el de la plantilla</label>' +
      '<label><input type="radio" name="spLen" value="manual"> Alto fijo <input type="number" data-p="len" min="10" max="300" step="1"> mm</label>' +
      '<label><input type="checkbox" data-p="mirror"> Espejo</label>' +
      '<label><input type="checkbox" data-p="invert"> Invertir (negativo)</label>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px"><button type="button" class="sp-btn" data-save>Guardar</button><button type="button" class="sp-btn" data-test>🖨️ Imprimir prueba</button></div>' +
      '<p style="font-size:0.85rem;color:#555;margin:8px 0 0">Se guardan en este equipo y valen para el Registro, la impresión compartida y /impresion-usb.</p>';
    const q = (sel) => panel.querySelector(sel);
    q('[data-p=cut]').checked = p.cut; q('[data-p=feed]').value = String(p.feedMm); q('[data-p=mirror]').checked = p.mirror; q('[data-p=invert]').checked = p.invert;
    q('[data-p=len]').value = p.lengthMm ? String(p.lengthMm) : '';
    q(`input[name=spLen][value=${p.lengthMm ? 'manual' : 'auto'}]`).checked = true;
    const read = () => {
      const manual = q('input[name=spLen][value=manual]').checked;
      const len = parseFloat(q('[data-p=len]').value), feed = parseFloat(q('[data-p=feed]').value);
      return { cut: q('[data-p=cut]').checked, feedMm: isFinite(feed) && feed >= 0 ? feed : QLUsb.PREF_DEFAULTS.feedMm, lengthMm: manual && isFinite(len) && len >= 10 ? len : null,
        mirror: q('[data-p=mirror]').checked, invert: q('[data-p=invert]').checked };
    };
    const save = () => { let ls = null; try { ls = window.localStorage; } catch (e) { /* bloqueado */ } QLUsb.savePrefs(ls, read()); };
    panel.addEventListener('click', async (e) => {
      if (e.target.closest('[data-close]')) { panel.remove(); return; }
      if (e.target.closest('[data-save]')) { save(); toast('Preferencias de impresión guardadas en este equipo.', 'success'); panel.remove(); return; }
      if (e.target.closest('[data-test]')) { save(); await printTest(); }
    });
    document.body.appendChild(panel);
  }
  function testJob() {
    const p = prefs();
    const DOTS = QLUsb.MEDIA[62].printable;
    const height = QLUsb.mmToDots(p.lengthMm || 40);
    return jobFromCanvas((ctx) => {
      ctx.fillStyle = '#000'; ctx.fillRect(0, 0, 30, height);                                     // barra a la izquierda: se ve si sale en espejo
      ctx.lineWidth = 4; ctx.strokeRect(36, 4, DOTS - 40, height - 8);
      ctx.font = 'bold 56px sans-serif'; ctx.textBaseline = 'top'; ctx.fillText('PRUEBA →', 60, 20);
      ctx.font = '34px sans-serif'; ctx.fillText(`corte ${p.cut ? 'sí' : 'no'} · margen ${p.feedMm} mm · ${p.lengthMm ? p.lengthMm + ' mm' : 'alto 40 mm'}`, 60, 100);
    }, height, p);
  }
  function printTest() {
    const run = usbBusy.then(async () => {
      if (!usb.ok || !QLUsb.info()) await connectUsb(false);
      if (!usb.ok) throw new Error(usb.busy ? QLUsb.BUSY_MSG : 'La impresora no está conectada a este equipo.');
      await QLUsb.sendJob(testJob());
    });
    usbBusy = run.catch(() => {});
    return run.then(() => toast('🖨️ Etiqueta de prueba enviada.', 'success'), (e) => toast('⚠️ ' + (e && e.message ? e.message : e), 'error'));
  }

  bar.querySelector('#spConnect').addEventListener('click', () => connectUsb(true));
  bar.querySelector('#spPrefs').addEventListener('click', showPrefs);
  bar.querySelector('#spQueue').addEventListener('click', showQueue);
  function start() {
    mount();
    wireEnter();
    applyTouch();
    render();
    keepAwake();
    connectUsb(false);                                    // reconoce la impresora ya autorizada (sin pedir permiso) y manda la primera señal
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  window.GoldenSharedPrint = { printFor, testJob, cleanCedula, state: () => ({ route, usb, online, pending, deviceId, touch }) };
})();
