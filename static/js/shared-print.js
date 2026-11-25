/* Impresión compartida + impresión directa por USB (Brother QL-800, cinta continua de 62 mm) en la pantalla de Registro. Orden del 22-oct-2026.

   27-oct-2026: la IMPRESIÓN y la impresión compartida son las del domingo 25-oct 18:00 (c10c3d2). Se carga en todos los eventos (kiosk_registro.html) para el modo touch, «solo lector»,
   la barra y el menú; con «Impresión compartida» APAGADA no toca la impresión: se imprime con la ventana de siempre, exactamente como el domingo. Solo USB directo (con la compartida) o la ventana de siempre.

   - Cada equipo reporta cada 10 s su plataforma, navegador y si tiene la impresora USB conectada (POST print-devices/heartbeat). El servidor responde dónde
     imprime este usuario («en su propio equipo» o «en el equipo de Y») y si este equipo atiende a otros (entonces pregunta por trabajos cada 1,5 s).
   - Imprimir (automático al registrar, o el botón «Imprimir escarapela»):
       · en su propio equipo con la impresora USB conectada → se dibuja la escarapela (BadgeRender + html2canvas) y se manda por USB (QLUsb), sin diálogo;
       · en su propio equipo sin impresora USB → la ventana de impresión de siempre;
       · en el equipo de Y → se crea un trabajo (con un id propio: un reintento no duplica) y se sigue su estado; «Impreso en Y», o el aviso y la cola visible.
   - El equipo Y imprime lo que el servidor le reserva (nunca dos veces: el servidor no vuelve a entregar un trabajo reservado) y confirma impreso/fallido.
   - Reconexión de la impresora sin pedir permiso de nuevo (navigator.usb.getDevices), pantalla siempre encendida (Wake Lock) y avisos si se pierde la conexión.
   - «Registro touch» (AUTOMÁTICO en celular o tableta, static/js/touch-detect.js): botones grandes y los TRES buscadores; la cédula abre el teclado numérico. «Solo lector» (opción del PUESTO en Parámetros, para lectores
     USB/Bluetooth): la cédula no abre teclado, conserva el foco y un ícono ⌨️ pegado al campo lo abre.
   - Menú de impresión (⚙️, Conectar, Cola): para TODO el personal; el interruptor del puesto en Parámetros («Mostrar» por defecto) lo esconde y deja solo la línea de estado.
   - Trabajos de otros equipos: los reclama SOLO la ventana que puede imprimir sin confirmar (la dueña de la impresora USB); sin ella esperan en «Imprimir pendientes», que reclama al tocarlo. */
(function () {
  'use strict';
  const EID = window.EVENT_ID;
  const HEARTBEAT_MS = 10000;
  const HOST_HEARTBEAT_MS = 2000;       // anfitrión: la cola (y «Imprimir pendientes») se refresca casi al instante
  const POLL_MS = 1500;
  const FOLLOW_MS = 1000;
  const BUSY_RETRY_MS = 4000;            // impresora tomada por otra pestaña de este equipo: se reintenta sola cada 4 s
  const FOLLOW_MAX = 20;                 // segundos que X sigue el estado de su trabajo antes de dejarlo en la cola visible
  const original = window.BadgePrint || {};
  const toast = (msg, kind) => (window.showToast ? window.showToast(msg, kind || 'info') : null);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const offline = () => !!(window.gwOffline && window.gwOffline());          // sin red (docs/28): se imprime en ESTE equipo (USB o ventana); la impresión compartida necesita al servidor
  const fetchT = (url, opts, ms) => {         // una petición que se cuelga (red suspendida) no debe detener el latido ni el sondeo para siempre
    if (typeof AbortController === 'undefined') return fetch(url, opts);
    const ac = new AbortController(); const t = setTimeout(() => ac.abort(), ms || 10000);
    return fetch(url, Object.assign({}, opts || {}, { signal: ac.signal })).finally(() => clearTimeout(t));
  };
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
  /* Cómo imprime este equipo (29-oct-2026): «usb» (impresora abierta por WebUSB), «dialog» (con la ventana de Chrome: lo DECLARA la persona con el control de la barra, recordado por equipo) o «none».
     Solo usb y dialog pueden atender a otros equipos; con «none» la barra avisa en vez de decir que la impresora está desconectada. */
  const MOBILE = platform === 'Android' || platform === 'iOS';
  let dialogDeclared = !MOBILE;                                 // un computador SIEMPRE imprime con la ventana de Chrome (no hay nada que marcar); un celular solo atiende con USB
  let printingPending = false;
  /* «Impresión compartida» (interruptor del evento): solo con ella se usa la impresión directa por USB, el latido, los trabajos y la Cola. Apagada, la impresión es la de siempre. */
  const SHARED = window.SHARED_PRINT_ENABLED !== false;
  /* PUESTO (Parámetros): «Puesto de impresión», «solo lector» y «Mostrar/Esconder la configuración». Lo demás que haya guardado (modo, calibración, ancho, giro, recorte…) se IGNORA:
     la etiqueta sale con los valores del evento y lo de ⚙️ de este equipo, como el domingo. */
  let isAdmin = false, isStation = false, stationCfg = null, recoveredUntil = 0;
  const configShown = () => !(stationCfg && stationCfg.showConfig === false);
  const waitingCount = () => (route && route.waiting) | 0;      // trabajos de otros equipos que esperan EN EL SERVIDOR a este puesto

  /* ------------------------------------------------------------------ barra de estado */
  const bar = document.createElement('div');
  bar.id = 'sharedPrintBar';
  bar.setAttribute('role', 'status');
  bar.setAttribute('aria-live', 'polite');
  bar.innerHTML = '<span class="sp-dot" aria-hidden="true"></span><span class="sp-text">Impresión: comprobando…</span>' +
    '<button type="button" class="sp-btn" id="spConnect">Conectar impresora</button>' +
    '<button type="button" class="sp-btn" id="spPending" hidden>Imprimir pendientes</button>' +
    '<button type="button" class="sp-btn" id="spQueue">Cola</button>' +
    '<button type="button" class="sp-btn" id="spPrefs">Impresión</button>' +
    '<button type="button" class="sp-btn" id="spKeyboard" hidden>Teclado</button>';
  const style = document.createElement('style');
  style.textContent = [
    '#sharedPrintBar{position:sticky;top:0;z-index:50;display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:8px 12px;margin:0 0 12px;border-radius:12px;background:#fff;border:2px solid #d0d4de;font-size:0.95rem}',
    '#sharedPrintBar .sp-dot{width:14px;height:14px;border-radius:50%;background:#999;flex:none}',
    '#sharedPrintBar.ok .sp-dot{background:#1e7e34}#sharedPrintBar.warn .sp-dot{background:#b26a00}#sharedPrintBar.bad .sp-dot{background:#a12631}',
    '#sharedPrintBar.bad{border-color:#a12631;background:#fdeeee}#sharedPrintBar.warn{border-color:#b26a00;background:#fff6e5}',
    '#sharedPrintBar .sp-text{flex:1 1 220px;font-weight:600}',
    '#sharedPrintBar [hidden]{display:none !important}',
    '#sharedPrintBar #spPending{min-height:64px;padding:8px 22px;font-size:1.3rem;background:#b26a00;border-color:#7a4a00;color:#fff}',
    '#sharedPrintBar .sp-btn{min-height:44px;padding:6px 14px;border-radius:10px;border:2px solid #0a0e2e;background:#fff;color:#0a0e2e;font-weight:700;cursor:pointer}',
    '#spQueuePanel{position:fixed;inset:auto 12px 12px 12px;max-height:60vh;overflow:auto;z-index:9998;background:#fff;border:2px solid #0a0e2e;border-radius:14px;padding:12px;box-shadow:0 10px 40px rgba(0,0,0,.25)}',
    '#spPrefsPanel{position:fixed;inset:auto 12px 12px 12px;max-height:80vh;overflow:auto;z-index:9998;background:#fff;border:2px solid #0a0e2e;border-radius:14px;padding:14px;box-shadow:0 10px 40px rgba(0,0,0,.25);font-size:1rem}',
    '#spPrefsPanel label{display:flex;gap:10px;align-items:center;min-height:44px}#spPrefsPanel input[type=checkbox],#spPrefsPanel input[type=radio]{width:24px;height:24px}#spPrefsPanel input[type=number]{width:90px;min-height:40px;font-size:1rem}',
    '#spQueuePanel table{width:100%;border-collapse:collapse;font-size:0.95rem}#spQueuePanel td,#spQueuePanel th{padding:6px;overflow-wrap:anywhere;border-bottom:1px solid #eee;text-align:left}',
    /* Registro touch: lo esencial, grande y a un dedo */
    'body.touch-mode{font-size:18px}',
    'body.touch-mode input[type=text],body.touch-mode input[type=search]{min-height:56px;font-size:1.25rem !important}',
    'body.touch-mode button,body.touch-mode .golden-btn,body.touch-mode .small-btn{min-height:52px;font-size:1.05rem !important;padding-left:18px !important;padding-right:18px !important}',
    'body.touch-mode #clearFiltersBtn,body.touch-mode .golden-sidebar-toggle{display:none !important}',
    'body.touch-mode #searchCedula,body.touch-mode #searchNombre,body.touch-mode #searchEntidad{min-height:60px;font-size:1.3rem !important;width:100%;box-sizing:border-box}',
    '.sp-kbd-wrap{position:relative;display:block}.sp-kbd-wrap>input{padding-right:64px !important}',
    '.sp-kbd{position:absolute;right:6px;top:50%;transform:translateY(-50%);min-width:48px;min-height:48px;border-radius:10px;border:2px solid #0a0e2e;background:#fff;font-size:1rem;font-weight:700;line-height:1;cursor:pointer;padding:0}',
    '.sp-kbd[aria-pressed=true]{background:#0a0e2e;color:#fff}',
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
    'body.touch-mode .golden-table tbody td[data-card-hidden]{display:none}',
    'body.touch-mode .golden-table tbody td[data-field=cardx]{order:6;flex-basis:100%;white-space:normal;overflow-wrap:anywhere;font-size:0.95rem}',
    'body.touch-mode .golden-table tbody td.action-cell{order:10;flex-basis:100%;display:flex;gap:10px;margin-top:8px}',
    'body.touch-mode .golden-table tbody td.action-cell .btn-table-action{flex:1 1 0;min-width:0;min-height:56px;font-size:1.05rem !important;margin:0;border-radius:12px;padding-left:8px !important;padding-right:8px !important;overflow-wrap:normal;word-break:keep-all;white-space:normal;line-height:1.15}',
    'body.touch-mode .golden-table tbody td.action-cell .btn-accredit-row{flex-grow:1.7}',                                    /* «✅ Acreditar» con más espacio: nunca se parte una palabra */
    "body.touch-mode .golden-table tbody td.action-cell .btn-table-action[title='Imprimir escarapela']{flex:0 0 64px;font-size:1.4rem !important}",
    'body.touch-mode .golden-table tbody tr td[colspan]{flex-basis:100%;text-align:center}',
  ].join('\n');
  document.head.appendChild(style);

  function mount() {
    const host = document.getElementById('gwRegCfgBar');                       // Plan 7: dentro del panel del engranaje de Registro (cerrado por defecto)
    if (host) { host.appendChild(bar); return; }
    const anchor = document.querySelector('.golden-container .tabs');        // encima de las pestañas: se ve en todas (Registro, Escáner, Directorio)
    if (anchor) anchor.parentNode.insertBefore(bar, anchor); else (document.querySelector('main') || document.body).prepend(bar);
  }

  function render() {
    const text = bar.querySelector('.sp-text');
    let kind = 'ok';
    let msg;
    if (!SHARED) {                                    // sin impresión compartida: USB directo si hay impresora; si no, la ventana de impresión del navegador (sin mencionar la compartida)
      if (usb.busy) { kind = 'warn'; msg = `${QLUsb.BUSY_MSG} Se vuelve a intentar sola cada pocos segundos.`; }
      else if (usb.ok) msg = `Impresora conectada (${usb.name || 'Brother'}).`;
      else if (usb.denied) { kind = 'warn'; msg = 'Este computador no puede abrir la impresora directamente (Windows usa su propio controlador): se imprime con la ventana de Chrome. Para compartir la impresora usa un celular o tablet Android.'; }
      else { kind = 'warn'; msg = 'Sin impresora: se usa la ventana de impresión del navegador.'; }
    } else if (!online) { kind = 'bad'; msg = 'Sin conexión con el servidor: la impresión compartida no funciona hasta que vuelva la red.'; }
    else if (route.mode === 'shared') {
      if (route.printer_ready) msg = `Imprime en el equipo de ${route.printer_name}.`;
      else if (route.printer_mode === 'dialog' && route.printer_online) msg = `Imprime en el equipo de ${route.printer_name} con la ventana de Chrome: sale cuando ese equipo toque «Imprimir pendientes».`;
      else if (route.printer_mode === 'none' || route.printer_online === false) { kind = 'bad'; msg = `El equipo de ${route.printer_name} no tiene impresora ahora: tus escarapelas quedan en cola.`; }
      else msg = `Enviada al puesto ${route.printer_name}: se imprime cuando el puesto la confirme.`;
    } else if (printingPending) {
      msg = 'Imprimiendo las escarapelas de otros equipos…';
    } else if (usb.busy) {
      kind = 'warn';
      msg = `${QLUsb.BUSY_MSG} Se vuelve a intentar sola cada pocos segundos.`;
    } else if (usb.ok) {
      msg = `Impresora conectada (${usb.name}).` + (route.serving ? ` Imprime también para ${route.serving} equipo(s).` : '');
    } else if (dialogDeclared) {
      msg = 'Este equipo imprime con la ventana de Chrome.' + (route.serving ? ` Imprime también para ${route.serving} equipo(s).` : '');
      if (waitingCount()) { kind = 'warn'; msg = `Este equipo imprime con la ventana de Chrome; ${waitingCount()} escarapela(s) de otros equipos esperan: toca «Imprimir pendientes».`; }
    } else if (usb.denied) {
      kind = 'warn'; msg = 'Este computador no puede abrir la impresora directamente (Windows usa su propio controlador): se imprime con la ventana de Chrome.';
      if (route.serving) { kind = 'bad'; msg = `${route.serving} equipo(s) imprimen aquí y no tienes impresora: conéctala por USB.`; }
    } else {
      kind = route.serving ? 'bad' : 'warn';
      msg = route.serving ? `${route.serving} equipo(s) imprimen aquí y no tienes impresora: conéctala por USB.`
        : 'Sin impresora USB: se usará la impresión normal del navegador.';
    }
    if (pending) msg += ` · ${pending} por confirmar`;
    const shown = configShown();
    if (!shown && online) { const line = stationLine(); msg = line.msg; kind = line.kind; }      // menú ESCONDIDO para este puesto: solo UNA línea
    if (online && recoveredUntil > Date.now()) msg += ' · Reconectado.';
    text.textContent = msg;
    bar.className = kind;
    /* La visibilidad NO depende del rol: la decide el interruptor del PUESTO en Parámetros («Mostrar» por defecto). */
    bar.querySelector('#spConnect').hidden = !shown || usb.ok || usb.busy || usb.denied || (SHARED && route.mode === 'shared') || !(window.QLUsb && QLUsb.supported());
    bar.querySelector('#spQueue').hidden = !(SHARED && shown);
    bar.querySelector('#spPrefs').hidden = !shown;
    bar.querySelector('#spPending').hidden = !(SHARED && !usb.ok && waitingCount());            // la acción del puesto: se ve también con el menú escondido
    bar.querySelector('#spPending').textContent = `Imprimir pendientes (${waitingCount()})`;
  }
  function stationLine() {
    const names = route.serving_names && route.serving_names.length ? route.serving_names.join(', ') : '';
    if (!SHARED) return usb.ok ? { kind: 'ok', msg: `Impresora conectada (${usb.name || 'Brother'}).` } : { kind: 'warn', msg: 'Sin impresora: se usa la ventana de impresión del navegador.' };
    if (route.mode === 'shared') return route.printer_ready ? { kind: 'ok', msg: `Imprime en: ${route.printer_name} (lista)` } : { kind: 'ok', msg: `Enviada al puesto ${route.printer_name}: se imprime cuando el puesto la confirme.` };
    if (route.serving) return { kind: usb.ok || dialogDeclared ? 'ok' : 'warn', msg: `Comparte impresora con: ${names || route.serving + ' equipo(s)'} (${usb.ok ? 'lista' : dialogDeclared ? 'imprime con la ventana de Chrome' : 'sin impresora'})` + (waitingCount() && !usb.ok ? ` · ${waitingCount()} esperan: toca «Imprimir pendientes».` : '') };
    if (MOBILE && !usb.ok) return { kind: 'warn', msg: 'Sin impresora: se usa la ventana de impresión del navegador.' };
    return { kind: 'ok', msg: `Imprime en: este puesto (${usb.ok ? 'lista' : 'ventana de impresión del navegador'})` };
  }

  /* ------------------------------------------------------------------ impresora USB */
  let busyTimer = null;
  /* Windows con el controlador oficial de Brother: Chrome no puede abrir la impresora por USB («Access denied»). No se arregla por código: aviso claro UNA vez por sesión, sin reintentos
     en bucle, y el equipo NO se anuncia como dueño de la impresora (usb.ok queda en falso: ni latido ni cola lo toman por anfitrión). En Android no pasa. */
  const DENIED_MSG = 'En este computador la impresora no se puede abrir directamente (Windows usa su propio controlador). Para recibir trabajos de otros equipos, usa un celular o tablet Android conectado a la impresora, o toca «Imprimir pendientes» y confirma en el cuadro de Chrome.';
  const isDenied = (e) => !!e && (e.name === 'SecurityError' || /access denied/i.test(String(e.message || e)));
  let deniedShown = false;
  async function connectUsb(ask) {
    clearTimeout(busyTimer);
    if (!ask && usb.ok && window.QLUsb && QLUsb.info()) { render(); heartbeat(); return; }      // ya conectada: no se vuelve a abrir
    if (!ask && usb.denied) { render(); heartbeat(); return; }                                                // Windows no la deja abrir: no se reintenta en bucle (solo si la persona toca «Conectar»)
    if (!(window.QLUsb && QLUsb.supported())) { usb = { ok: false, name: '', lastError: 'USB no disponible en este navegador', busy: false }; render(); heartbeat(); return; }
    try {
      const d = await QLUsb.connect(ask);
      usb = { ok: !!d, name: d ? (d.productName || 'Brother') : '', lastError: '', busy: false };
    } catch (e) {
      const busy = !!(e && e.busy);                    // otra pestaña de este equipo tiene la impresora: aviso amable y reintento solo, sin desconectar el cable
      if (isDenied(e)) {
        usb = { ok: false, name: '', lastError: DENIED_MSG, busy: false, denied: true };
        let seen = false; try { seen = sessionStorage.getItem('gw_denied_notice') === '1'; } catch (er) { seen = deniedShown; }
        if (ask || (!seen && !deniedShown)) { deniedShown = true; try { sessionStorage.setItem('gw_denied_notice', '1'); } catch (er) { /* sin almacenamiento */ } toast('ℹ️ ' + DENIED_MSG, 'info'); }      // UNA vez por sesión, sin rojo
      } else {
        usb = { ok: false, name: '', lastError: e && e.message ? e.message : String(e), busy };
        if (busy) busyTimer = setTimeout(() => connectUsb(false), BUSY_RETRY_MS);
        else if (ask) toast('No se pudo conectar la impresora: ' + usb.lastError, 'error');
      }
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
  let hbTimer = null, sessionDead = false;
  window.addEventListener('gw:session-replaced', () => { sessionDead = true; clearTimeout(hbTimer); route = Object.assign({}, route, { poll: false }); });       // entró en otro dispositivo: se detienen latido y sondeo
  async function heartbeat() {
    clearTimeout(hbTimer);
    if (sessionDead || !SHARED) { render(); return; }                // sin impresión compartida no se llama a ninguna ruta compartida
    try {
      const res = await fetchT(`/api/events/${EID}/print-devices/heartbeat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store',
        body: JSON.stringify({ device_id: deviceId, platform, browser, printer_connected: usb.busy ? null : usb.ok, printer_name: usb.name || null, print_mode: usb.ok ? 'usb' : (dialogDeclared ? 'dialog' : 'none') }) });      // null: otra pestaña es la dueña, no se pisa su estado
      if (!online) recoveredUntil = Date.now() + 20000;                  // volvió la red: lo dice la barra y se reanudan sondeo y latido sin que nadie toque nada
      online = true;
      if (res.ok) { route = await res.json(); startPolling(); }
    } catch (e) { online = false; }
    render();
    hbTimer = setTimeout(heartbeat, route.serving && !usb.ok && dialogDeclared ? HOST_HEARTBEAT_MS : HEARTBEAT_MS);
  }

  /* ------------------------------------------------------------------ dibujar e imprimir por USB */
  const stage = document.createElement('div');
  stage.setAttribute('aria-hidden', 'true');
  stage.style.cssText = 'position:fixed; left:-10000px; top:0; background:#fff;';
  document.body.appendChild(stage);

  /* Valores de impresión: los del EVENTO (meta gw-print-settings, se editan en Parámetros) y, encima, lo que ESTE equipo sobrescribió en «⚙️ Impresión». */
  const eventPrefs = (() => { try { const m = document.querySelector('meta[name="gw-print-settings"]'); const v = m ? JSON.parse(m.getAttribute('content') || '{}') : {}; return v && typeof v === 'object' ? v : {}; } catch (e) { return {}; } })();
  function storage() { try { return window.localStorage; } catch (e) { return null; } }
  function applyStation(me) {
    isAdmin = !!(me && me.admin); isStation = !!(me && me.station);
    stationCfg = me && me.settings && typeof me.settings === 'object' ? me.settings : null;
  }
  async function loadStation() {
    const key = 'gw_station_me_' + EID;
    let me = null;
    try { const r = await fetchT(`/api/events/${EID}/print-station/me`, { cache: 'no-store' }, 5000); if (r.ok) me = await r.json(); } catch (e) { me = null; }
    const rs = storage();
    if (me) { try { if (rs) rs.setItem(key, JSON.stringify(me)); } catch (e) { /* sin almacenamiento */ } }
    else { try { me = JSON.parse((rs && rs.getItem(key)) || 'null'); } catch (e) { me = null; } }       // sin red al abrir: la última configuración conocida
    applyStation(me);
  }
  function resolved() { return QLUsb.resolvePrefs(storage(), eventPrefs); }
  function prefs() { return resolved().prefs; }
  let lastPrint = null;                       // con qué valores se imprimió lo último (indicador del panel y de la barra)
  const DPM = 300 / 25.4;                     // puntos por mm de la QL-800

  /* De la plantilla ya dibujada (canvas a 300 dpi) al trabajo para la cinta: la composición vive en static/js/label-compose.js (la MISMA que usa la ventana de impresión del navegador). */
  function composeJob(shot, tplW, tplH, p) {
    const composed = LabelCompose.composeBitmap(shot, tplW, tplH, p);
    const fit = p.tapeType === 'diecut' ? { bitmap: composed.bitmap, height: composed.height } : LabelCompose.usbFit(composed);      // el mismo largo máximo (96 mm) que la ventana de impresión del navegador
    if (!p.lengthMm && p.tapeType !== 'diecut') { const landscape = composed.layout.rotation === 90 || composed.layout.rotation === 270, t = LabelCompose.trimBlankEnds(fit, QLUsb.mmToDots(p.feedMm + (landscape ? 0 : LabelCompose.USB_LEAD_TRIM_MM)), QLUsb.mmToDots(p.feedMm)); fit.bitmap = t.bitmap; fit.height = t.height; }      // la impresora ya agrega ese avance: no se suma al blanco de la etiqueta
    if (p.lengthMm && fit.height < composed.height) {                // alto fijo manual: la etiqueta conserva su largo (el sobrante queda en blanco)
      const padded = new Uint8Array(composed.tapeDots * composed.height); padded.set(fit.bitmap); fit.bitmap = padded; fit.height = composed.height;
    }
    const out = Object.assign({}, composed, { bitmap: fit.bitmap, height: fit.height });
    const job = QLUsb.buildJob({ bitmap: out.bitmap, height: out.height, mediaWidthMm: p.tapeWidth, mirror: p.mirror, autoCut: p.cut, feedDots: QLUsb.mmToDots(p.feedMm),
      lengthMm: p.tapeType === 'diecut' ? p.lengthMm : undefined });
    return Object.assign({ job }, out);
  }

  const renderTemplate = (template, data, holderScale) => LabelCompose.renderShot(stage, template, data, EID, holderScale);

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
      if (!usb.ok || !QLUsb.info()) await connectUsb(false);
      if (!usb.ok) throw new Error('La impresora no está conectada.');
      await QLUsb.sendJob(await badgeBitmap(userId, given));
    });
    usbBusy = run.catch(() => {});
    return run;
  }

  async function logPrint(userId) {
    try { await (window.gwFetch || fetch)(`/api/users/${encodeURIComponent(userId)}/print-log?event_id=${EID}`, { method: 'POST' }, 'Impresión de escarapela'); } catch (e) { /* no bloquea */ }
  }

  /* ------------------------------------------------------------------ Y: atender a otros equipos */
  /* Reclamo (4797531): SOLO reclama por sondeo la ventana que puede imprimir sin que nadie confirme nada, la dueña de la impresora USB. El servidor entrega el trabajo solo a ese
     equipo (`device_id`) y, si no termina en 60 s, lo devuelve a la cola. Sin impresora USB, los trabajos esperan EN EL SERVIDOR hasta que alguien toque «Imprimir pendientes»: cada uno
     se reclama en ese momento y se imprime con la ventana de impresión de siempre (la escarapela con su plantilla), y se confirma. Nunca se pierde ni se reimprime solo. */
  let polling = false;
  async function claimNext(manual) {
    const res = await fetchT(`/api/events/${EID}/print-jobs-next?device_id=${encodeURIComponent(deviceId)}${manual ? '&manual=1' : ''}`, { method: 'POST', cache: 'no-store', headers: { 'X-Gw-Fetch': '1' } }, 8000);
    return res.ok ? (await res.json()).job : null;
  }
  async function runJob(job, viaWindow) {
    let ok = false;
    let error = '';
    try {
      if (viaWindow) (original.openNow || original.openPrintWindow)(job.user_id);       // sin USB: la ventana de impresión de siempre
      else await printUsb(job.user_id, prefsForJob(job));
      ok = true;
    } catch (e) { error = e && e.message ? e.message : String(e); }
    for (let i = 0; i < 3; i++) {             // la confirmación se reintenta: si se pierde, el trabajo vuelve a la cola o caduca (nunca se reimprime solo)
      try {
        const r = await fetch(`/api/events/${EID}/print-jobs/${job.id}/result`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ok, error }) });
        if (r.ok) break;
      } catch (e) { await sleep(1000); }
    }
    if (!ok) toast(`⚠️ No se pudo imprimir la escarapela que pidió ${job.requested_by || 'otro equipo'}: ${error}`, 'error');
  }
  async function startPolling() {
    if (!SHARED || sessionDead || polling || !route.poll || !usb.ok) return;
    polling = true;
    while (route.poll && usb.ok && !sessionDead) {
      let job = null;
      try { job = await claimNext(false); } catch (e) { online = false; render(); }
      if (job) { await runJob(job, false); continue; }               // hay trabajo: se pregunta de nuevo enseguida
      await sleep(POLL_MS);
    }
    polling = false;
  }
  /* «Imprimir pendientes» (29-oct-2026): ANTES cada escarapela abría su propia ventana de impresión (5 pendientes = 5 ventanas). Ahora se reclaman por TANDA (hasta 50, mismo arrendamiento) y,
     sin impresora USB, se abre UNA sola ventana con una hoja por escarapela. El resultado de cada trabajo se confirma DESPUÉS de que la ventana termina y la persona lo confirma; si cierra o
     cancela, los trabajos vuelven a la cola (nunca se pierden ni se reimprimen solos). Con impresora USB se imprime una tras otra sin ventana, como siempre. */
  async function claimBatch() {
    const res = await fetchT(`/api/events/${EID}/print-jobs-next?device_id=${encodeURIComponent(deviceId)}&manual=1&batch=50`, { method: 'POST', cache: 'no-store', headers: { 'X-Gw-Fetch': '1' } }, 10000);
    return res.ok ? ((await res.json()).jobs || []) : [];
  }
  async function postJson(url, body) {
    for (let i = 0; i < 3; i++) {
      try { const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); if (r.ok) return true; } catch (e) { await sleep(1000); }
    }
    return false;
  }
  /* Abre UNA ventana con todas las escarapelas y espera a que termine: 'done' (terminó el cuadro de impresión; trae qué hojas se armaron) o 'closed' (la cerraron antes). */
  function openBatchWindow(userIds) {
    return new Promise((resolve) => {
      const url = original.printBatchUrl ? original.printBatchUrl(userIds) : `/kiosk/${EID}/escarapela/imprimir/${encodeURIComponent(userIds[0])}?users=${userIds.map(encodeURIComponent).join(',')}`;
      const w = original.openPrintTab ? original.openPrintTab(url) : window.open(url, 'goldenweb_print', 'width=480,height=720');
      if (!w) { resolve({ state: 'blocked' }); return; }
      let finished = false;
      const end = (r) => { if (finished) return; finished = true; window.removeEventListener('message', onMsg); clearInterval(timer); resolve(r); };
      const onMsg = (ev) => { if (ev.origin === location.origin && ev.data && ev.data.gwPrint === 'done') end({ state: 'done', batch: ev.data.batch }); };
      window.addEventListener('message', onMsg);
      const timer = setInterval(() => { try { if (w.closed) end({ state: 'closed' }); } catch (e) { /* sigue */ } }, 700);
      setTimeout(() => end({ state: 'closed' }), 10 * 60 * 1000);          // respaldo: nunca queda esperando para siempre
    });
  }
  async function runBatchWindow(jobs) {
    const r = await openBatchWindow(jobs.map((j) => j.user_id));
    const ids = jobs.map((j) => j.id);
    if (r.state !== 'done') {                     // la cerraron (o el navegador la bloqueó) sin llegar a imprimir: todo vuelve a la cola
      await postJson(`/api/events/${EID}/print-jobs/release`, { ids });
      toast(r.state === 'blocked' ? '⚠️ El navegador bloqueó la ventana de impresión: las escarapelas siguen pendientes. Permite las ventanas emergentes y toca «Imprimir pendientes».'
        : 'Cerraste la ventana de impresión: las escarapelas siguen pendientes.', 'warning');
      return false;
    }
    const failed = new Set(((r.batch && r.batch.failed) || []).map(String));
    const printable = jobs.filter((j) => !failed.has(String(j.user_id)));
    const said = await window.showConfirm(`¿Salieron las ${printable.length} escarapela(s)?<br><br>Si se canceló o no salieron, elige «No» y siguen pendientes.`, { confirmLabel: 'Sí, salieron' });
    const results = jobs.map((j) => (failed.has(String(j.user_id)) ? { id: j.id, ok: false, error: 'No se pudo armar la escarapela.' } : { id: j.id, ok: !!said, error: said ? '' : 'No salió.' }));
    if (said) await postJson(`/api/events/${EID}/print-jobs/result-batch`, { results });
    else {                                        // no salieron: vuelven a la cola; las que no se pudieron armar quedan como fallidas (visibles en la Cola de quien las pidió)
      await postJson(`/api/events/${EID}/print-jobs/release`, { ids: printable.map((j) => j.id) });
      const bad = results.filter((x) => !x.ok && failed.size && failed.has(String((jobs.find((j) => j.id === x.id) || {}).user_id)));
      if (bad.length) await postJson(`/api/events/${EID}/print-jobs/result-batch`, { results: bad });
    }
    if (failed.size) toast(`⚠️ No se pudieron armar ${failed.size} escarapela(s): quedan fallidas en la Cola de quien las pidió.`, 'error');
    return !!said;
  }
  async function printPending() {                  // un toque de la persona: reclama por tanda e imprime lo que espera en el servidor
    if (printingPending) return;
    printingPending = true;
    render();
    try {
      for (let round = 0; round < 10; round++) {   // tandas de 50 (si hay más, una segunda tanda)
        let jobs = [];
        try { jobs = await claimBatch(); } catch (e) { online = false; break; }
        if (!jobs.length) break;
        let ok = true;
        if (usb.ok) { for (const job of jobs) await runJob(job, false); }                   // impresora USB: una tras otra, sin ventanas
        else ok = await runBatchWindow(jobs);
        route.waiting = Math.max(0, waitingCount() - jobs.length); render();
        if (!ok || jobs.length < 50) break;                                                  // cancelado: no insistir con la siguiente tanda
      }
    } finally { printingPending = false; heartbeat(); render(); }
  }

  /* ------------------------------------------------------------------ X: mandar a otro equipo y seguir el estado */
  async function sendToPrinter(userId, reprint, onSent) {       // `onSent` se llama en cuanto el servidor aceptó el trabajo (la impresión AUTOMÁTICA confirma ahí su candado, sin esperar el seguimiento)
    const requestId = uuid();
    let job = null;
    for (let i = 0; i < 2 && !job; i++) {           // el mismo request_id: si la primera respuesta se perdió, el servidor no duplica
      try {
        const res = await fetch(`/api/events/${EID}/print-jobs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: userId, request_id: requestId, reprint: !!reprint, prefs: prefs() }) });      // con los parámetros YA resueltos de este equipo
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          if (res.status === 403 && window.GWReprint && String(body.detail || '').startsWith('No se puede reimprimir')) { window.GWReprint.open(userId); return false; }       // Fase 1B: la puerta del servidor
          toast(`⚠️ No se pudo enviar la escarapela a imprimir: ${body.detail || res.status}`, 'error'); return false;
        }
        job = body;
      } catch (e) { await sleep(800); }
    }
    if (!job) { toast('⚠️ Sin conexión: la escarapela NO se envió a imprimir. Reintente con «Imprimir escarapela».', 'error'); return false; }
    if (job.duplicate) { toast('ℹ️ Esta escarapela ya se mandó a imprimir hace un momento: no se repite.', 'info'); }
    if (job.warning) toast('⚠️ ' + job.warning, 'warning');
    pending += 1; render();
    try {
      if (onSent) onSent();
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
      let approved = false;
      if (window.GWReprint) {                                       // Fase 1B: reimprimir desde la Cola también pide permiso si el evento lo exige (solo para escarapelas ya impresas)
        const g = await window.GWReprint.check(btn.dataset.reprint, null, { explicit: true });
        if (!g.ok) return;
        approved = g.approved;
      }
      if (!approved && !(await window.showConfirm(`¿Reimprimir la escarapela de ${window.escapeHtml(btn.dataset.reprint)}?`, { confirmLabel: 'Sí, reimprimir' }))) return;
      btn.disabled = true;
      await printFor(btn.dataset.reprint, false, true);
      panel.remove();
    });
    const body = panel.querySelector('[data-body]');
    try {
      const res = await fetch(`/api/events/${EID}/print-jobs`, { cache: 'no-store' });
      const data = res.ok ? await res.json() : { jobs: [] };
      let station = [];                                       // lo que espera EN ESTE PUESTO (pendientes y reclamados, con su estado)
      try { const sr = await fetch(`/api/events/${EID}/print-jobs?scope=station`, { cache: 'no-store' }); if (sr.ok) station = (await sr.json()).jobs; } catch (e) { /* sin red: se muestra lo otro */ }
      const stationBox = document.createElement('div');
      if (station.length) {
        const st = document.createElement('table');
        st.innerHTML = '<tr><th>En este puesto</th><th>Estado</th><th>Pidió</th></tr>';
        station.forEach((j) => { const tr = document.createElement('tr'); [j.user_id, j.status === 'sent' ? 'Reclamado (imprimiéndose)' : 'Pendiente', j.requested_by].forEach((t) => { const td = document.createElement('td'); td.textContent = t || ''; tr.appendChild(td); }); st.appendChild(tr); });
        stationBox.appendChild(st);
      }
      if (!data.jobs.length) { if (station.length) body.replaceChildren(stationBox); else body.textContent = 'No hay escarapelas pendientes.'; return; }
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
      body.replaceChildren(...(station.length ? [stationBox, table] : [table]));
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

  /* PR3 (causa B): la impresión AUTOMÁTICA toma el candado de 30 s de forma provisional (`claimTicket`) y lo CONFIRMA solo cuando algo salió (trabajo aceptado por el servidor, impresión USB hecha o
     ventana abierta); si la comprobación «¿registrado?» falla, el envío no sale o el navegador bloquea la ventana, lo SUELTA y un reintento automático de la misma persona no queda bloqueado. */
  async function printFor(userId, auto, confirmed) {
    if ((!SHARED || offline()) && !usb.ok) return auto ? original.maybeAutoPrint(userId, offline() ? { auto: !!window.EVENT_AUTO_PRINT } : undefined) : original.openPrintWindow(userId);       // compartida apagada (o sin red: no hay servidor que reparta) y sin impresora: la ventana de impresión de siempre
    let ticket = null;
    if (auto) {                                    // una impresión automática por persona (entre pestañas del mismo equipo, 30 s)
      if (original.claimTicket) { ticket = await original.claimTicket(userId); if (!ticket) return; }
      else if (original.claim && !(await original.claim(userId))) return;
    }
    let ok = false;
    try { ok = await dispatch(userId, auto, confirmed, ticket); }
    finally { if (ticket) { if (ok) ticket.commit(); else ticket.release(); } }
    return ok;
  }
  async function dispatch(userId, auto, confirmed, ticket) {         // true = salió (o quedó en manos del servidor); false = no salió
    if (!auto && original.beginManual && !original.beginManual(userId)) return false;       // doble clic / doble toque en «Imprimir»: una sola
    if (SHARED && !offline() && !(await registeredOrSay(userId))) return;            // «solo a quien está Registrado» lo comprueba la ruta compartida; sin ella, la regla de siempre
    let explicit = !!confirmed;                    // reimpresión EXPLÍCITA: desde la Cola o tras confirmar «¿imprimir de nuevo?»
    if (SHARED && !offline() && route.mode === 'shared') {
      if (!auto && !confirmed) {                    // el botón manual conserva el aviso de reimpresión de siempre
        try {
          const r = await fetch(`/api/users/${encodeURIComponent(userId)}/print-count?event_id=${EID}`);
          const c = r.ok ? await r.json() : { times_printed: 0 };
          if (c.times_printed > 0) explicit = true;
          let approved = false;
          if (c.times_printed > 0 && window.GWReprint) {            // Fase 1B: con la reimpresión deshabilitada pide permiso; el servidor gasta el permiso al crear el trabajo
            const g = await window.GWReprint.check(userId, c);
            if (!g.ok) return false;
            approved = g.approved;
          }
          if (c.times_printed > 0 && !approved && !(await window.showConfirm(`⚠️ Ya se ha impreso esta escarapela (${c.times_printed} ${c.times_printed === 1 ? 'vez' : 'veces'}).<br><br>¿Deseas imprimir de nuevo?`,
            { variant: 'warning', confirmLabel: 'Sí, imprimir de nuevo' }))) return false;
        } catch (e) { /* si falla la consulta, no bloquea */ }
      }
      if (original.dropPrimed) original.dropPrimed();            // la ruta compartida no abre ventana aquí
      let accepted = false;                                       // el servidor aceptó el trabajo (el seguimiento posterior puede terminar de varias formas)
      await sendToPrinter(userId, !auto && explicit, () => { accepted = true; if (ticket) ticket.commit(); });
      return accepted;
    }
    if (usb.ok) {
      try {
        if (auto && window.GWReprint && !(await window.GWReprint.auto(userId))) return false;       // Fase 1B: la autoimpresión por USB tampoco reimprime sola con la reimpresión deshabilitada
        if (!auto && !confirmed && original.openPrintWindow) { /* el aviso de reimpresión de siempre */
          const r = await fetch(`/api/users/${encodeURIComponent(userId)}/print-count?event_id=${EID}`).catch(() => null);
          const c = r && r.ok ? await r.json() : { times_printed: 0 };
          let approved = false;
          if (c.times_printed > 0 && window.GWReprint) {            // Fase 1B: reimpresión deshabilitada → pedir permiso
            const g = await window.GWReprint.check(userId, c);
            if (!g.ok) return false;
            approved = g.approved;
          }
          if (c.times_printed > 0 && !approved && !(await window.showConfirm(`⚠️ Ya se ha impreso esta escarapela (${c.times_printed} ${c.times_printed === 1 ? 'vez' : 'veces'}).<br><br>¿Deseas imprimir de nuevo?`,
            { variant: 'warning', confirmLabel: 'Sí, imprimir de nuevo' }))) return false;
          if (c.times_printed > 0 && window.GWReprint && !(await window.GWReprint.use(userId, c.reprint_locked))) return false;      // gasta el permiso (una sola reimpresión)
        }
        if (original.dropPrimed) original.dropPrimed();          // USB no abre ventana
        await printUsb(userId);
        await logPrint(userId);
        toast('🖨️ Escarapela impresa' + (lastPrint ? ` (${lastPrint.text})` : '.'), 'success');
        return true;
      } catch (e) {
        toast(`⚠️ No se pudo imprimir por USB (${e && e.message ? e.message : e}). Se abre la impresión normal.`, 'warning');
      }
    }
    if (auto) {
      if (!original.printNow) return !!(await original.maybeAutoPrint(userId, { auto: true }));
      const w = await original.printNow(userId);
      if (w === null && original.dropPrimed) original.dropPrimed();
      return w !== null;                           // null = el navegador bloqueó la ventana: no se gasta el candado
    }
    await (original.openNow || original.openPrintWindow)(userId);
    return true;
  }

  window.BadgePrint = Object.assign({}, original, {
    maybeAutoPrint(userId, opts) {
      const auto = original.resolveAuto ? original.resolveAuto(opts) : (opts && typeof opts.auto === 'boolean' ? opts.auto : !!window.EVENT_AUTO_PRINT);
      if (!auto) { if (original.cancelPrimed) original.cancelPrimed(); return Promise.resolve(false); }
      if (original.holdPrimed) original.holdPrimed();            // esta llamada se queda con la ventana preparada (la consume printNow)
      return printFor(userId, true);
    },
    primeWindow() { return (usb.ok || (SHARED && route.mode === 'shared') || !original.primeWindow) ? null : original.primeWindow(); },       // con USB o ruta compartida no se abre ventana
    openPrintWindow(userId) { return printFor(userId, false); },
  });

  /* ------------------------------------------------------------------ Registro touch */
  const READER_IDS = ['searchCedula', 'regScanCedulaInput', 'bioCedula'];
  let touch = !!(window.GWTouchDetect && GWTouchDetect.fromWindow(window));        // Plan 7: automático (celular o tableta); ya no hay interruptor manual
  let keyboard = false;
  const readerOnly = () => !!(stationCfg && stationCfg.readerOnly);        // opción del PUESTO (Parámetros): solo lector de códigos, sin teclado en pantalla
  function readerField() { return READER_IDS.map((id) => document.getElementById(id)).find((el) => el && el.offsetParent !== null) || null; }
  function kbdButton(el) {                                                       // ícono ⌨️ PEGADO al campo (solo con «Solo lector»): abre o cierra el teclado en pantalla
    let wrap = el.parentNode && el.parentNode.classList && el.parentNode.classList.contains('sp-kbd-wrap') ? el.parentNode : null;
    if (!wrap) {
      wrap = document.createElement('span'); wrap.className = 'sp-kbd-wrap';
      el.parentNode.insertBefore(wrap, el); wrap.appendChild(el);
      const b = document.createElement('button'); b.type = 'button'; b.className = 'sp-kbd'; b.textContent = 'Abc'; b.setAttribute('aria-label', 'Abrir el teclado');
      b.addEventListener('click', () => { keyboard = !keyboard; applyTouch(); el.blur(); setTimeout(() => el.focus(), 50); });
      wrap.appendChild(b);
    }
    return wrap.querySelector('.sp-kbd');
  }
  function applyTouch() {
    document.body.classList.toggle('touch-mode', touch);
    bar.querySelector('#spKeyboard').hidden = true;                            // el botón lejano de la barra ya no se usa: el ícono va pegado al campo
    const lector = touch && readerOnly();
    READER_IDS.forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (el.dataset.origInputmode === undefined) el.dataset.origInputmode = el.getAttribute('inputmode') || '';
      if (lector && !keyboard) el.setAttribute('inputmode', 'none');            // solo lector: el lector escribe como teclado, sin abrir el teclado en pantalla
      else el.setAttribute('inputmode', el.dataset.origInputmode || 'numeric');  // por defecto: el teclado NUMÉRICO al tocar la cédula
      if (lector) { const b = kbdButton(el); b.setAttribute('aria-pressed', keyboard ? 'true' : 'false'); b.hidden = false; b.setAttribute('aria-label', keyboard ? 'Ocultar el teclado' : 'Abrir el teclado'); }
      else { const w = el.parentNode; if (w && w.classList && w.classList.contains('sp-kbd-wrap')) w.querySelector('.sp-kbd').hidden = true; }
    });
  }
  if (window.matchMedia && window.GWTouchDetect) ['(pointer: coarse)', '(hover: none)'].forEach((q) => {           // p. ej. al acoplar o quitar un mouse en una tableta
    const mq = window.matchMedia(q);
    const onChange = () => { const next = GWTouchDetect.fromWindow(window); if (next !== touch) { touch = next; keyboard = false; applyTouch(); } };
    if (mq.addEventListener) mq.addEventListener('change', onChange); else if (mq.addListener) mq.addListener(onChange);
  });
  bar.querySelector('#spKeyboard').addEventListener('click', () => { keyboard = !keyboard; applyTouch(); const f = readerField(); if (f) { f.blur(); setTimeout(() => f.focus(), 50); } });
  document.addEventListener('focusout', () => {                                   // solo lector: el campo del lector recupera el foco (salvo que se esté usando otro campo o un diálogo)
    if (!touch || !readerOnly()) return;
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
  const SEARCH_IDS = ['searchCedula', 'searchNombre', 'searchEntidad', 'manualIdField'];      // B3: el escaneo de «Registrar nuevo» va en el campo de cédula/ID
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
      if (!usb.ok || !QLUsb.info()) await connectUsb(false);
      if (!usb.ok) throw new Error(usb.busy ? QLUsb.BUSY_MSG : 'La impresora no está conectada a este equipo.');
      await QLUsb.sendJob(testJob());
    });
    usbBusy = run.catch(() => {});
    return run.then(() => toast('🖨️ Etiqueta de prueba enviada.', 'success'), (e) => toast('⚠️ ' + (e && e.message ? e.message : e), 'error'));
  }

  bar.querySelector('#spConnect').addEventListener('click', () => connectUsb(true));
  bar.querySelector('#spPending').addEventListener('click', () => printPending());
  bar.querySelector('#spPrefs').addEventListener('click', showPrefs);
  bar.querySelector('#spQueue').addEventListener('click', showQueue);
  async function start() {
    await loadStation();                                  // «solo lector» y Mostrar/Esconder de este puesto (servidor)
    QLUsb.dropLegacyPrefs(storage());                    // «Espejo» con el significado viejo no se hereda
    mount();
    wireEnter();
    applyTouch();
    render();
    keepAwake();
    connectUsb(false);                                    // reconoce la impresora ya autorizada (sin pedir permiso) y manda la primera señal
  }
  /* Autorrecuperación: tras una caída de red o una suspensión, se reconecta, se reanudan latido y sondeo y la barra lo dice. */
  window.addEventListener('online', () => { recoveredUntil = Date.now() + 20000; online = true; heartbeat(); connectUsb(false); render(); });
  window.addEventListener('offline', () => { online = false; render(); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  window.GoldenSharedPrint = { printFor, testJob, cleanCedula, prefsForJob, printPending, connectForTest: (ask) => connectUsb(!!ask), disconnectForTest: () => { usb = { ok: false, name: '', lastError: '', busy: false }; }, applyStationForTest: (me) => { applyStation(me); applyTouch(); render(); },
    barState: () => ({ text: bar.querySelector('.sp-text').textContent, kind: bar.className, pendingHidden: bar.querySelector('#spPending').hidden }),
    declareDialogForTest: (on) => { dialogDeclared = !!on; render(); },
    stationState: () => ({ isAdmin, isStation, cfg: stationCfg, shown: configShown(), line: stationLine().msg, bar: { prefs: bar.querySelector('#spPrefs').hidden, queue: bar.querySelector('#spQueue').hidden, connect: bar.querySelector('#spConnect').hidden, pending: bar.querySelector('#spPending').hidden } }),
    state: () => ({ route, usb, online, pending, deviceId, touch, pendingJobs: waitingCount(), shared: SHARED }) };
})();
