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
    /* Directorio en vivo como TARJETAS de dos filas (25-oct-2026, celular vertical: el nombre quedaba fuera de la pantalla detrás de los botones). Solo con el modo touch;
       la tabla de escritorio no cambia. Fila 1: nombre grande, estado, empresa, cédula y tipo. Fila 2: los botones de siempre, grandes. Sin scroll de lado. */
    'body.touch-mode .golden-table thead{display:none}',
    'body.touch-mode .golden-table,body.touch-mode .golden-table tbody{display:block;width:100%}',
    'body.touch-mode .golden-table tbody tr{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;padding:12px 14px;margin:0 0 14px;border:2px solid #c9cdd8;border-left-width:8px;border-radius:14px;background:#fff;box-shadow:0 2px 6px rgba(10,14,46,.08)}',
    'body.touch-mode .golden-table tbody tr:nth-child(even){background:#f4f5f9}',
    'body.touch-mode .golden-table tbody tr.row-registrado,body.touch-mode .golden-table tbody tr.row-nuevo{border-color:#1e7e34}',
    'body.touch-mode .golden-table tbody td{display:block;border:none;padding:0;background:transparent;min-width:0;overflow-wrap:anywhere}',
    'body.touch-mode .golden-table tbody td.touch-only{display:block}',
    'body.touch-mode .golden-table tbody td[data-field=first_name],body.touch-mode .golden-table tbody td[data-field=last_name]{order:1;font-size:1.35rem;font-weight:800;color:#0a0e2e;line-height:1.2}',
    'body.touch-mode .golden-table tbody td[data-field=status]{order:2;margin-left:auto;font-size:0.95rem;padding:2px 10px;border-radius:999px;background:#eceef3}',
    'body.touch-mode .golden-table tbody tr.row-registrado td[data-field=status],body.touch-mode .golden-table tbody tr.row-nuevo td[data-field=status]{background:#1e7e34;color:#fff !important}',
    'body.touch-mode .golden-table tbody td[data-field=entity]{order:3;flex-basis:100%;font-size:1rem;font-weight:600;color:#333}',
    'body.touch-mode .golden-table tbody td[data-field=id]{order:4;font-size:1rem;color:#444}',
    "body.touch-mode .golden-table tbody td[data-field=id]::before{content:'C.C. ';font-weight:700}",
    'body.touch-mode .golden-table tbody td[data-field=opt_1]{order:5;font-size:0.95rem;color:#555}',
    'body.touch-mode .golden-table tbody td[data-field=opt_1]:empty,body.touch-mode .golden-table tbody td[data-field=entity]:empty{display:none}',
    'body.touch-mode .golden-table tbody td.action-cell{order:10;flex-basis:100%;display:flex;gap:10px;margin-top:8px}',
    'body.touch-mode .golden-table tbody td.action-cell .btn-table-action{flex:1 1 0;min-width:0;min-height:56px;font-size:1.05rem !important;margin:0;border-radius:12px;padding-left:8px !important;padding-right:8px !important;overflow-wrap:normal;word-break:keep-all;white-space:normal;line-height:1.15}',
    'body.touch-mode .golden-table tbody td.action-cell .btn-accredit-row{flex-grow:1.7}',                                    /* «✅ Acreditar» con más espacio: nunca se parte una palabra */
    "body.touch-mode .golden-table tbody td.action-cell .btn-table-action[title='Imprimir escarapela']{flex:0 0 64px;font-size:1.4rem !important}",
    'body.touch-mode .golden-table tbody tr td[colspan]{flex-basis:100%;text-align:center}',
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
      msg = (usb.viaTab ? `Impresora conectada en otra pestaña de este navegador (${usb.name}): se imprime a través de ella.` : `Impresora conectada (${usb.name}).`) + (route.serving ? ` Imprime también para ${route.serving} equipo(s).` : '');
    } else {
      kind = route.serving ? 'bad' : 'warn';
      msg = route.serving ? `Impresora DESCONECTADA: ${route.serving} equipo(s) imprimen aquí y sus escarapelas quedan en cola. Conéctela.`
        : 'Sin impresora USB: se usará la impresión normal del navegador.';
      if (usb.code === 'denied' || usb.code === 'disconnected' || usb.code === 'permission') msg += ` ${usb.lastError}`;       // el motivo y qué hacer, a la vista (no solo en un aviso que se va)
    }
    if (pending) msg += ` · ${pending} por confirmar`;
    text.textContent = msg;
    bar.className = kind;
    bar.querySelector('#spConnect').hidden = usb.ok || usb.busy || route.mode === 'shared' || !(window.QLUsb && QLUsb.supported());
  }

  /* ------------------------------------------------------------------ impresora USB */
  /* El estado «Impresora conectada» sale SOLO de lo que de verdad sirve para imprimir (25-oct-2026): la conexión abierta de QLUsb (`QLUsb.ready()`), o la de otra pestaña de este mismo
     navegador, a través de la cual también se imprime (`viaTab`). Un solo intento a la vez (`connectUsb` espera al que esté en marcha) y «Conectar» no vuelve a abrir lo que ya está abierto. */
  let busyTimer = null, connecting = null;
  const DISCONNECTED = (extra) => Object.assign({ ok: false, name: '', lastError: '', busy: false, viaTab: false, code: '' }, extra || {});
  function connectUsb(ask) {
    clearTimeout(busyTimer);
    if (connecting) return ask ? connecting.then(() => (usb.ok ? undefined : doConnectUsb(true))) : connecting;     // el que toca el botón no se queda con el resultado de un intento sin permiso
    connecting = doConnectUsb(ask).finally(() => { connecting = null; });
    return connecting;
  }
  async function doConnectUsb(ask) {
    if (usb.ok && (usb.viaTab || (window.QLUsb && QLUsb.ready()))) {                       // ya conectada y abierta: «Ya conectada», sin volver a abrir
      if (ask) toast('✅ La impresora ya está conectada.', 'success');
      render(); heartbeat(); return;
    }
    if (!(window.QLUsb && QLUsb.supported())) { usb = DISCONNECTED({ lastError: 'USB no disponible en este navegador', code: 'other' }); render(); return; }
    try {
      const d = await QLUsb.connect(ask);
      usb = d ? DISCONNECTED({ ok: true, name: d.productName || 'Brother' }) : DISCONNECTED();
    } catch (e) {
      const f = QLUsb.friendlyError ? QLUsb.friendlyError(e) : e;
      const remote = f && f.busy && QLUsb.remoteOwner ? await QLUsb.remoteOwner().catch(() => null) : null;
      if (remote) {                                    // otra pestaña de ESTE navegador tiene la impresora abierta: se muestra conectada y se imprime a través de ella
        usb = DISCONNECTED({ ok: true, name: remote.name, viaTab: true });
        if (ask) toast('ℹ️ La impresora ya está conectada en otra pestaña de este navegador: se imprime a través de ella.', 'info');
      } else {
        const busy = !!(f && f.busy);                  // en uso en otra pestaña que no responde: aviso amable y reintento solo, sin desconectar el cable
        usb = DISCONNECTED({ lastError: f && f.message ? f.message : String(e), busy, code: (f && f.code) || 'other' });
        if (busy) busyTimer = setTimeout(() => connectUsb(false), BUSY_RETRY_MS);
        else if (ask) toast('No se pudo conectar la impresora: ' + usb.lastError, 'error');
        try { console.info('[impresora] no se pudo conectar:', f && f.code, f && f.raw ? f.raw : e); } catch (e2) { /* sin consola */ }
      }
    }
    render();
    heartbeat();
  }
  if (window.QLUsb && QLUsb.supported()) {
    navigator.usb.addEventListener('connect', () => connectUsb(false));
    navigator.usb.addEventListener('disconnect', async () => {
      await QLUsb.close();
      usb = DISCONNECTED({ lastError: 'desconectada', code: 'disconnected' });
      render();
      toast('⚠️ Se desconectó la impresora USB.', 'warning');
      heartbeat();
    });
    // La impresora se SUELTA al cerrar o recargar la página (sin esperar promesas): si no, la página nueva puede recibir «Access denied» mientras Chrome termina de soltarla.
    ['pagehide', 'beforeunload'].forEach((ev) => window.addEventListener(ev, () => { try { QLUsb.releaseNow(); } catch (e) { /* ya suelta */ } }));
  }

  /* ------------------------------------------------------------------ pantalla siempre encendida */
  let wakeLock = null;
  async function keepAwake() {
    try { if ('wakeLock' in navigator && document.visibilityState === 'visible' && !wakeLock) { wakeLock = await navigator.wakeLock.request('screen'); wakeLock.addEventListener('release', () => { wakeLock = null; }); } } catch (e) { /* el sistema no lo permitió: se reintenta al volver */ }
  }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') { keepAwake(); heartbeat(); connectUsb(false); } });

  /* ------------------------------------------------------------------ señal con el servidor */
  let hbTimer = null, lastRecheck = 0;
  async function heartbeat() {
    clearTimeout(hbTimer);
    if (usb.ok && !usb.viaTab && window.QLUsb && QLUsb.ready && !QLUsb.ready() && Date.now() - lastRecheck > 5000) { lastRecheck = Date.now(); usb = DISCONNECTED({ lastError: 'desconectada', code: 'disconnected' }); connectUsb(false); }       // la conexión se cayó sin avisar: no se anuncia una impresora que no imprime
    if (usb.ok && usb.viaTab && window.QLUsb && QLUsb.remoteOwner && !(await QLUsb.remoteOwner().catch(() => null))) {                 // la pestaña dueña se cerró: esta intenta quedarse con la impresora
      usb = DISCONNECTED(); await connectUsb(false); return;
    }
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

  /* Valores de impresión: los del EVENTO (meta gw-print-settings, se editan en Parámetros) y, encima, lo que ESTE equipo sobrescribió en «⚙️ Impresión». */
  const eventPrefs = (() => { try { const m = document.querySelector('meta[name="gw-print-settings"]'); const v = m ? JSON.parse(m.getAttribute('content') || '{}') : {}; return v && typeof v === 'object' ? v : {}; } catch (e) { return {}; } })();
  function storage() { try { return window.localStorage; } catch (e) { return null; } }
  function resolved() { return QLUsb.resolvePrefs(storage(), eventPrefs); }
  function prefs() { return resolved().prefs; }
  let lastPrint = null;                       // con qué valores se imprimió lo último (indicador del panel y de la barra)
  const DPM = 300 / 25.4;                     // puntos por mm de la QL-800

  /* De la plantilla ya dibujada (canvas a 300 dpi) al trabajo para la cinta: tamaño REAL (sin estirar al ancho de la cinta), giro, centrado, recorte e invertir. */
  function composeJob(shot, tplW, tplH, p) {
    const lay = QLUsb.layout(p, tplW, tplH);
    const w = Math.max(1, Math.round(tplW * DPM * lay.scale)), h = Math.max(1, Math.round(tplH * DPM * lay.scale));
    const canvas = document.createElement('canvas');
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, w, h);
    ctx.drawImage(shot, 0, 0, w, h);
    const bm = QLUsb.bitmapFromRGBA(ctx.getImageData(0, 0, w, h).data, w, h, 140, false);
    const prep = QLUsb.prepareBitmap(bm, w, h, p, lay);
    const tapeDots = QLUsb.MEDIA[p.tapeWidth].printable;
    const job = QLUsb.buildJob({ bitmap: prep.bitmap, height: prep.height, mediaWidthMm: p.tapeWidth, mirror: p.mirror, autoCut: p.cut, feedDots: QLUsb.mmToDots(p.feedMm),
      lengthMm: p.tapeType === 'diecut' ? p.lengthMm : undefined });
    return { job, bitmap: prep.bitmap, tapeDots, height: prep.height, layout: lay, cropped: prep.cropped, widthMm: tplW, heightMm: tplH };
  }

  async function renderTemplate(template, data, holderScale) {
    const holder = document.createElement('div');
    stage.appendChild(holder);
    try {
      await BadgeRender.loadFonts(template);                         // la tipografía elegida ya cargada: la etiqueta impresa no cambia de letra
      BadgeRender.renderBadge(holder, template, data, { eventId: EID });
      if (document.fonts && document.fonts.ready) await document.fonts.ready;
      await Promise.all(Array.from(holder.querySelectorAll('img')).map((img) => (img.decode ? img.decode().catch(() => {}) : null)));
      // con el ancho REAL (con decimales) de la caja: offsetWidth redondea a px enteros y la etiqueta salía 2-3 puntos más ancha y estirada (25-oct-2026)
      const box = holder.getBoundingClientRect();
      return await html2canvas(holder, { width: box.width, height: box.height, scale: (template.width_mm * DPM) / box.width * (holderScale || 1), useCORS: true, backgroundColor: '#ffffff', logging: false });
    } finally {
      holder.remove();
    }
  }

  /* Parámetros con los que se imprime un pedido: los de ESTE equipo si lo imprime él mismo; los que mandó el equipo que lo pidió si es un pedido compartido (24-oct-2026: antes el
     equipo con la impresora los resolvía con SUS valores y se perdían los del que pidió). Un pedido viejo sin parámetros usa los del evento (nunca los locales de quien lo imprime). */
  function prefsForJob(job) {
    if (job && job.prefs && typeof job.prefs === 'object') {
      const r = QLUsb.resolvePrefs(null, job.prefs);
      Object.keys(r.source).forEach((k) => { if (r.source[k] === 'evento') r.source[k] = 'origen'; });
      return r;
    }
    return QLUsb.resolvePrefs(null, eventPrefs);
  }

  async function badgeBitmap(userId, given) {
    const dataRes = await fetch(`/api/users/${encodeURIComponent(userId)}/badge-print-data?event_id=${EID}`, { cache: 'no-store' });
    if (!dataRes.ok) throw new Error('No se encontró la persona en este evento.');
    const data = await dataRes.json();
    const tplRes = await BadgeRender.fetchTemplate(EID, data.template_category);           // la vigente, en cada etiqueta
    if (!tplRes.ok) throw new Error('El evento no tiene plantilla de escarapela.');
    const template = await tplRes.json();
    const r = given || resolved();
    const shot = await renderTemplate(template, data);
    const out = composeJob(shot, template.width_mm, template.height_mm, r.prefs);
    lastPrint = { text: QLUsb.describePrefs(r.prefs, r.source, out.layout), warn: out.layout.tooWide ? `La plantilla (${out.layout.acrossMm} mm) es más ancha que la cinta (${out.layout.availMm.toFixed(1)} mm imprimibles): se encogió.` : '', at: Date.now() };
    if (out.layout.tooWide) toast('⚠️ ' + lastPrint.warn, 'warning');
    bar.title = 'Última impresión: ' + lastPrint.text;
    return out.job;
  }

  let usbBusy = Promise.resolve();
  function printUsb(userId, given) {                // una impresión a la vez por equipo (la impresora no admite dos flujos a la vez)
    const run = usbBusy.then(async () => {
      if (!usb.ok || !(usb.viaTab || QLUsb.ready())) await connectUsb(false);
      if (!usb.ok) throw new Error('La impresora no está conectada.');
      await QLUsb.sendJob(await badgeBitmap(userId, given));                 // por la conexión de esta pestaña o, si la dueña es otra, a través de ella
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
        try { await printUsb(job.user_id, prefsForJob(job)); ok = true; } catch (e) { error = e && e.message ? e.message : String(e); }
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
  async function sendToPrinter(userId, reprint) {
    const requestId = uuid();
    let job = null;
    for (let i = 0; i < 2 && !job; i++) {           // el mismo request_id: si la primera respuesta se perdió, el servidor no duplica
      try {
        const res = await fetch(`/api/events/${EID}/print-jobs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: userId, request_id: requestId, reprint: !!reprint, prefs: prefs() }) });      // con los parámetros YA resueltos de este equipo
        const body = await res.json().catch(() => ({}));
        if (!res.ok) { toast(`⚠️ No se pudo enviar la escarapela a imprimir: ${body.detail || res.status}`, 'error'); return; }
        job = body;
      } catch (e) { await sleep(800); }
    }
    if (!job) { toast('⚠️ Sin conexión: la escarapela NO se envió a imprimir. Reintente con «Imprimir escarapela».', 'error'); return; }
    if (job.duplicate) { toast('ℹ️ Esta escarapela ya se mandó a imprimir hace un momento: no se repite.', 'info'); }
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
    if (auto && original.claim && !(await original.claim(userId))) return;          // una impresión automática por persona (entre pestañas del mismo equipo, 30 s)
    if (!auto && original.beginManual && !original.beginManual(userId)) return;       // doble clic / doble toque en «Imprimir»: una sola
    if (!(await registeredOrSay(userId))) return;
    let explicit = !!confirmed;                    // reimpresión EXPLÍCITA: desde la Cola o tras confirmar «¿imprimir de nuevo?»
    if (route.mode === 'shared') {
      if (!auto && !confirmed) {                    // el botón manual conserva el aviso de reimpresión de siempre
        try {
          const r = await fetch(`/api/users/${encodeURIComponent(userId)}/print-count?event_id=${EID}`);
          const c = r.ok ? await r.json() : { times_printed: 0 };
          if (c.times_printed > 0) explicit = true;
          if (c.times_printed > 0 && !(await window.showConfirm(`⚠️ Ya se ha impreso esta escarapela (${c.times_printed} ${c.times_printed === 1 ? 'vez' : 'veces'}).<br><br>¿Deseas imprimir de nuevo?`,
            { variant: 'warning', confirmLabel: 'Sí, imprimir de nuevo' }))) return;
        } catch (e) { /* si falla la consulta, no bloquea */ }
      }
      return sendToPrinter(userId, !auto && explicit);
    }
    if (usb.ok && (usb.viaTab || QLUsb.ready())) {
      try {
        if (!auto && !confirmed && original.openPrintWindow) { /* el aviso de reimpresión de siempre */
          const r = await fetch(`/api/users/${encodeURIComponent(userId)}/print-count?event_id=${EID}`).catch(() => null);
          const c = r && r.ok ? await r.json() : { times_printed: 0 };
          if (c.times_printed > 0 && !(await window.showConfirm(`⚠️ Ya se ha impreso esta escarapela (${c.times_printed} ${c.times_printed === 1 ? 'vez' : 'veces'}).<br><br>¿Deseas imprimir de nuevo?`,
            { variant: 'warning', confirmLabel: 'Sí, imprimir de nuevo' }))) return;
        }
        await printUsb(userId);
        await logPrint(userId);
        toast('🖨️ Escarapela impresa' + (lastPrint ? ` (${lastPrint.text})` : '.'), 'success');
        return;
      } catch (e) {
        toast(`⚠️ No se pudo imprimir por USB (${e && e.message ? e.message : e}). Se abre la impresión normal.`, 'warning');
      }
    }
    return auto ? (original.printNow ? original.printNow(userId) : original.maybeAutoPrint(userId)) : (original.openNow || original.openPrintWindow)(userId);
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

  /* ------------------------------------------------------------------ «⚙️ Impresión»: valores del evento + lo que este equipo sobrescribe */
  const TAPE_FIELDS = ['cut', 'feedMm', 'lengthMm', 'mirror', 'invert', 'tapeWidth', 'tapeType', 'rotation', 'crop', 'cropMarginMm'];
  let previewTemplate = null;
  async function loadPreviewTemplate(fresh) {                 // la vista previa también usa la vigente: se vuelve a pedir cada vez que se abre el panel
    if (previewTemplate && !fresh) return previewTemplate;
    try { const r = await BadgeRender.fetchTemplate(EID); if (r.ok) previewTemplate = await r.json(); } catch (e) { /* sin red: la última que se tuvo */ }
    return previewTemplate;
  }
  const SAMPLE = { id: '1020304050', first_name: 'Juan David', last_name: 'Pérez Gómez', entity: 'GoldenWeb 2.0', role: 'Coordinador', phone: '3001234567', email: 'juan@correo.com', opt_1: 'VIP', extra_fields: {}, has_photo: false };

  function showPrefs() {
    const old = document.getElementById('spPrefsPanel');
    if (old) { old.remove(); return; }
    const r = resolved();
    const tapes = Object.keys(QLUsb.MEDIA).map(Number).sort((a, b) => a - b);
    const panel = document.createElement('div');
    panel.id = 'spPrefsPanel';
    panel.setAttribute('role', 'dialog');
    panel.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px"><strong>Impresión de escarapelas</strong><button type="button" class="sp-btn" data-close>Cerrar</button></div>' +
      '<p data-last style="font-size:0.85rem;margin:6px 0;color:#444"></p>' +
      `<label>Cinta <select data-p="tapeWidth">${tapes.map((t) => `<option value="${t}">${t} mm</option>`).join('')}</select> <select data-p="tapeType"><option value="continuous">continua</option><option value="diecut">troquelada (largo fijo)</option></select></label>` +
      '<label data-row="length">Largo de la etiqueta <input type="number" data-p="lengthMm" min="10" max="1000" step="1"> mm</label>' +
      '<label>Giro <select data-p="rotation"><option value="auto">Automático</option><option value="0">0°</option><option value="90">90°</option><option value="180">180°</option><option value="270">270°</option></select></label>' +
      '<label data-row="crop"><input type="checkbox" data-p="crop"> Recortar al contenido, con margen <input type="number" data-p="cropMarginMm" min="0" max="30" step="0.5"> mm</label>' +
      '<label><input type="checkbox" data-p="cut"> Cortar la cinta al final de cada etiqueta</label>' +
      '<label>Margen de avance <input type="number" data-p="feedMm" min="0" max="10" step="0.5"> mm</label>' +
      '<label><input type="checkbox" data-p="mirror"> Espejo</label>' +
      '<label><input type="checkbox" data-p="invert"> Invertir (negativo)</label>' +
      '<div data-src style="font-size:0.78rem;color:#555"></div>' +
      '<div style="margin:8px 0"><canvas data-preview style="max-width:100%;border:1px solid #ccc;background:#fff"></canvas><div data-prevtext style="font-size:0.82rem;margin-top:4px"></div></div>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap"><button type="button" class="sp-btn" data-save>Guardar en este equipo</button><button type="button" class="sp-btn" data-test>🖨️ Imprimir prueba</button><button type="button" class="sp-btn" data-reset>↺ Restablecer</button></div>' +
      '<p style="font-size:0.8rem;color:#555;margin:8px 0 0">Los valores del evento los fija el coordinador en Parámetros. Lo que cambies aquí vale solo para este equipo y se aplica a toda la impresión (Registro, compartida y /impresion-usb).</p>';
    const q = (sel) => panel.querySelector(sel);
    const setForm = (prefs) => {
      TAPE_FIELDS.forEach((f) => {
        const el = q(`[data-p=${f}]`);
        if (!el) return;
        if (el.type === 'checkbox') el.checked = !!prefs[f]; else el.value = prefs[f] === null || prefs[f] === undefined ? '' : String(prefs[f]);
      });
    };
    const readForm = () => {
      const v = {};
      TAPE_FIELDS.forEach((f) => {
        const el = q(`[data-p=${f}]`);
        if (!el) return;
        if (el.type === 'checkbox') v[f] = el.checked;
        else if (f === 'rotation') v[f] = el.value === 'auto' ? 'auto' : Number(el.value);
        else if (f === 'tapeWidth') v[f] = Number(el.value);
        else if (f === 'tapeType') v[f] = el.value;
        else v[f] = el.value === '' ? null : Number(el.value);
      });
      return v;
    };
    const sync = () => {
      const v = readForm();
      q('[data-row=length]').style.display = v.tapeType === 'diecut' ? '' : 'none';
      q('[data-row=crop]').style.display = v.tapeType === 'diecut' ? 'none' : '';
    };
    const fromStorage = () => resolved();
    const paintSources = () => {
      const cur = fromStorage();
      const names = { equipo: 'este equipo', evento: 'el evento', defecto: 'valores de fábrica' };
      const counts = {};
      TAPE_FIELDS.forEach((f) => { counts[cur.source[f]] = (counts[cur.source[f]] || 0) + 1; });
      q('[data-src]').textContent = 'Valores tomados de: ' + Object.keys(counts).map((k) => `${names[k]} (${counts[k]})`).join(' · ');
      q('[data-last]').textContent = lastPrint ? `Última impresión: ${lastPrint.text}.` + (lastPrint.warn ? ' ⚠️ ' + lastPrint.warn : '') : 'Aún no se ha impreso nada en este equipo.';
    };
    let timer = null;
    const paintPreview = async () => {
      const v = readForm();
      const p = Object.assign({}, QLUsb.PREF_DEFAULTS, v);
      const tpl = await loadPreviewTemplate();
      const cv = q('[data-preview]'), txt = q('[data-prevtext]');
      if (!tpl) { txt.textContent = 'No se pudo cargar la plantilla para la vista previa.'; return; }
      try {
        const shot = await renderTemplate(tpl, SAMPLE);
        const out = composeJob(shot, tpl.width_mm, tpl.height_mm, p);
        const w = out.tapeDots, h = out.height;
        cv.width = w; cv.height = h;
        const ctx = cv.getContext('2d'), img = ctx.createImageData(w, h);
        for (let i = 0; i < out.bitmap.length; i++) { const k = out.bitmap[i] ? 0 : 255; img.data[i * 4] = k; img.data[i * 4 + 1] = k; img.data[i * 4 + 2] = k; img.data[i * 4 + 3] = 255; }
        ctx.putImageData(img, 0, 0);
        cv.style.width = Math.min(300, w / 2.2) + 'px';
        txt.innerHTML = `Saldrá de ${(w / DPM).toFixed(1)} × ${(h / DPM).toFixed(1)} mm, girada ${out.layout.rotation}°` + (out.cropped ? ' y recortada al contenido' : '') + '.' +
          (out.layout.tooWide ? ` <b style="color:#a12631">⚠️ La plantilla (${out.layout.acrossMm.toFixed(1)} mm) es más ancha que la cinta (${out.layout.availMm.toFixed(1)} mm imprimibles): se encoge a ${Math.round(out.layout.scale * 100)} %. Ajusta el diseño o el giro.</b>` : '');
      } catch (e) { txt.textContent = 'No se pudo dibujar la vista previa.'; }
    };
    const refresh = () => { sync(); clearTimeout(timer); timer = setTimeout(paintPreview, 250); };
    setForm(r.prefs); sync(); paintSources(); loadPreviewTemplate(true).then(paintPreview);
    panel.addEventListener('input', refresh);
    panel.addEventListener('change', refresh);
    const saveOverrides = () => {                       // solo lo que DIFIERE de lo del evento queda como sobrescritura de este equipo
      const ls = storage();
      if (!ls) { toast('Este navegador no permite guardar preferencias.', 'error'); return false; }
      const base = QLUsb.resolvePrefs(null, eventPrefs).prefs, v = readForm();
      TAPE_FIELDS.forEach((f) => {
        const same = (v[f] === null && (base[f] === null || base[f] === undefined)) || v[f] === base[f];
        if (same) { try { ls.removeItem(QLUsb.PREF_KEYS[f]); } catch (e) { /* nada */ } } else QLUsb.savePrefs(ls, { [f]: v[f] });
      });
      return true;
    };
    panel.addEventListener('click', async (e) => {
      if (e.target.closest('[data-close]')) { panel.remove(); return; }
      if (e.target.closest('[data-save]')) { if (saveOverrides()) { toast('Guardado en este equipo.', 'success'); paintSources(); } return; }
      if (e.target.closest('[data-reset]')) {
        const ls = storage();
        if (ls) QLUsb.clearPrefs(ls);
        setForm(QLUsb.resolvePrefs(null, eventPrefs).prefs); sync(); paintSources(); paintPreview();
        toast('Este equipo vuelve a usar los valores del evento.', 'success');
        return;
      }
      if (e.target.closest('[data-test]')) { if (saveOverrides()) { paintSources(); await printTest(); paintSources(); } }
    });
    document.body.appendChild(panel);
  }

  /* Etiqueta de prueba: horizontal (80×50 mm), asimétrica a propósito: la barra negra a la izquierda y la flecha muestran el giro, el espejo y el recorte.
     25-oct-2026: un marco fino JUSTO en el borde y una cruz en el centro: si se pierde un borde o el centro sale corrido, se ve en la etiqueta impresa. */
  function testJob() {
    const r = resolved(), p = r.prefs;
    const W = 80, H = 50;
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(W * DPM); canvas.height = Math.round(H * DPM);
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, 30, canvas.height);
    ctx.lineWidth = 4; ctx.strokeRect(2, 2, canvas.width - 4, canvas.height - 4);                       // marco en el borde de la plantilla
    const cx = canvas.width / 2, cy = canvas.height / 2, arm = Math.round(8 * DPM);                     // cruz de 16 mm en el centro
    ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(cx - arm, cy); ctx.lineTo(cx + arm, cy); ctx.moveTo(cx, cy - arm); ctx.lineTo(cx, cy + arm); ctx.stroke();
    ctx.font = 'bold 56px sans-serif'; ctx.textBaseline = 'top'; ctx.fillText('PRUEBA →', 60, 24);
    ctx.font = '30px sans-serif'; ctx.fillText(`cinta ${p.tapeWidth} mm · corte ${p.cut ? 'sí' : 'no'}`, 60, 110); ctx.fillText(`margen ${p.feedMm} mm · giro ${p.rotation}`, 60, 150);
    const out = composeJob(canvas, W, H, p);
    lastPrint = { text: QLUsb.describePrefs(p, r.source, out.layout), warn: out.layout.tooWide ? `La plantilla es más ancha que la cinta: se encogió.` : '', at: Date.now() };
    return out.job;
  }
  function printTest() {
    const run = usbBusy.then(async () => {
      if (!usb.ok || !(usb.viaTab || QLUsb.ready())) await connectUsb(false);
      if (!usb.ok) throw new Error(usb.busy ? QLUsb.BUSY_MSG : (usb.lastError || 'La impresora no está conectada a este equipo.'));
      await QLUsb.sendJob(testJob());
    });
    usbBusy = run.catch(() => {});
    return run.then(() => toast('🖨️ Etiqueta de prueba enviada.', 'success'), (e) => toast('⚠️ ' + (e && e.message ? e.message : e), 'error'));
  }

  bar.querySelector('#spConnect').addEventListener('click', () => connectUsb(true));
  bar.querySelector('#spPrefs').addEventListener('click', showPrefs);
  bar.querySelector('#spQueue').addEventListener('click', showQueue);
  function start() {
    QLUsb.dropLegacyPrefs(storage());                    // «Espejo» con el significado viejo no se hereda
    mount();
    wireEnter();
    applyTouch();
    render();
    keepAwake();
    connectUsb(false);                                    // reconoce la impresora ya autorizada (sin pedir permiso) y manda la primera señal
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  window.GoldenSharedPrint = { printFor, testJob, cleanCedula, prefsForJob, connectUsb, disconnectForTest: () => { usb = DISCONNECTED(); connecting = null; }, state: () => ({ route, usb, online, pending, deviceId, touch }) };
})();
