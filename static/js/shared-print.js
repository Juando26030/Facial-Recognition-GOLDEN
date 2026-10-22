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
  let usb = { ok: false, name: '', lastError: '' };
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
    bar.querySelector('#spConnect').hidden = usb.ok || route.mode === 'shared' || !(window.QLUsb && QLUsb.supported());
  }

  /* ------------------------------------------------------------------ impresora USB */
  async function connectUsb(ask) {
    if (!ask && usb.ok && window.QLUsb && QLUsb.info()) { render(); heartbeat(); return; }      // ya conectada: no se vuelve a abrir
    if (!(window.QLUsb && QLUsb.supported())) { usb = { ok: false, name: '', lastError: 'USB no disponible en este navegador' }; render(); return; }
    try {
      const d = await QLUsb.connect(ask);
      usb = { ok: !!d, name: d ? (d.productName || 'Brother') : '', lastError: '' };
    } catch (e) {
      usb = { ok: false, name: '', lastError: e && e.message ? e.message : String(e) };
      if (ask) toast('No se pudo conectar la impresora: ' + usb.lastError, 'error');
    }
    render();
    heartbeat();
  }
  if (window.QLUsb && QLUsb.supported()) {
    navigator.usb.addEventListener('connect', () => connectUsb(false));
    navigator.usb.addEventListener('disconnect', async () => {
      await QLUsb.close();
      usb = { ok: false, name: '', lastError: 'desconectada' };
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
        body: JSON.stringify({ device_id: deviceId, platform, browser, printer_connected: usb.ok, printer_name: usb.name || null }) });
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
      const height = Math.max(1, Math.round(shot.height * DOTS / shot.width));
      const canvas = document.createElement('canvas');
      canvas.width = DOTS; canvas.height = height;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, DOTS, height);
      ctx.drawImage(shot, 0, 0, DOTS, height);
      const rgba = ctx.getImageData(0, 0, DOTS, height).data;
      const invert = store.get('ql_invert', '0') === '1';
      const mirror = store.get('ql_mirror', '0') === '1';
      const cut = store.get('ql_cut', '1') !== '0';
      return QLUsb.buildJob({ bitmap: QLUsb.bitmapFromRGBA(rgba, DOTS, height, 140, invert), height, mediaWidthMm: 62, mirror, autoCut: cut });
    } finally {
      holder.remove();
    }
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
  async function printFor(userId, auto, confirmed) {
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
  bar.querySelector('#spConnect').addEventListener('click', () => connectUsb(true));
  bar.querySelector('#spQueue').addEventListener('click', showQueue);
  function start() {
    mount();
    applyTouch();
    render();
    keepAwake();
    connectUsb(false);                                    // reconoce la impresora ya autorizada (sin pedir permiso) y manda la primera señal
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  window.GoldenSharedPrint = { printFor, state: () => ({ route, usb, online, pending, deviceId, touch }) };
})();
