/* Control de áreas (Fase 1.5). Lee window.EVENT_ID / FACIAL / AUTOREG / CAN_REPORT / ENABLED (los pone la plantilla). Sin manejadores en línea: todo por delegación. */
(function () {
  'use strict';
  let direction = 'auto', users = [], scanner = null;
  const FOUND = ['OK', 'FOUND_PENDING', 'ALREADY_ENTERED', 'NOT_INSIDE', 'LIMIT'];          // resultados en los que la persona sí se encontró
  const $ = (id) => document.getElementById(id);
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  const areaId = () => $('areaSelect').value;
  const busy = (btn, work) => (window.GW && window.GW.busy ? window.GW.busy(btn, work) : Promise.resolve(work()));
  const sprite = () => { const u = document.querySelector('.gw-icon use'); return u ? u.getAttribute('href').split('#')[0] : ''; };
  const icon = (name) => `<svg class="gw-icon" aria-hidden="true"><use href="${sprite()}#i-${name}"/></svg>`;

  async function getJson(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error('http ' + res.status);
    return res.json();
  }

  async function init() {
    if (!window.ENABLED) return;
    $('autoregLabel').textContent = window.AUTOREG ? 'ON' : 'OFF';
    if (window.FACIAL) $('faceBtn').hidden = false;
    if (window.CAN_REPORT) $('reportBtn').hidden = false;
    try {
      users = await getJson(`/api/users?event_id=${window.EVENT_ID}`);
      await loadAreas();
    } catch (e) {
      showState('No se pudo cargar la información. Revisa la conexión y recarga la página.', true);
    }
    $('scanInput').focus();
  }

  async function loadAreas(keep) {
    const all = await getJson(`/api/events/${window.EVENT_ID}/areas`);
    // Subcategorías: solo se elige una zona «hoja» (suelta o subcategoría); la principal con subcategorías no recibe movimientos y se muestra como «Salón A › Entrada A».
    const byId = {}; all.forEach(a => { byId[a.id] = a; });
    const areas = all.filter(a => !a.is_group).map(a => (a.parent_id && byId[a.parent_id] ? Object.assign({}, a, { name: byId[a.parent_id].name + ' › ' + a.name }) : a));
    const current = keep || areaId();
    $('areaSelect').innerHTML = areas.length
      ? areas.map(a => `<option value="${a.id}">${esc(a.name)} (${a.inside} adentro${a.allow_reentry ? '' : ' · sin reingresos'})</option>`).join('')
      : '<option value="">Crea zonas en Parámetros del evento</option>';
    if (current) $('areaSelect').value = current;
    renderZones(areas);
    await loadPresence();
  }

  // Zonas como botones grandes (hasta 6); el <select> sigue siendo la fuente de verdad y queda a la vista si hay más.
  function renderZones(areas) {
    const seg = $('zoneSeg');
    const few = areas.length > 0 && areas.length <= 6;
    seg.hidden = !few;
    $('areaSelect').hidden = few;
    if (!few) { seg.innerHTML = ''; return; }
    seg.innerHTML = areas.map(a => `<button type="button" class="gw-segment__opt zone-btn" data-zone="${a.id}" aria-pressed="${String(a.id) === String(areaId())}">${esc(a.name)} · ${a.inside} adentro</button>`).join('');
  }

  function showState(text, isError) {
    const st = $('presState');
    st.innerHTML = `<span class="gw-state__icon">${icon(isError ? 'error' : 'inbox')}</span><p class="gw-state__title">${esc(text)}</p>`;
    st.hidden = false;
    st.classList.toggle('gw-state--error', !!isError);
    $('presWrap').hidden = true;
  }

  async function loadPresence() {
    $('presState').hidden = true;
    if (!areaId()) {
      $('presBody').innerHTML = ''; setCounts([]);
      showState('Aún no hay zonas. Créalas en Parámetros del evento para empezar.', false);
      return;
    }
    $('presLoading').hidden = false;
    let rows;
    try { rows = await getJson(`/api/events/${window.EVENT_ID}/areas/${areaId()}/presence`); }
    catch (e) { $('presLoading').hidden = true; showState('No se pudo cargar quién está en la zona. Cambia de zona o recarga la página.', true); return; }
    $('presLoading').hidden = true;
    setCounts(rows);
    if (!rows.length) { showState('Sin movimientos todavía. Escanea la primera cédula o QR para empezar.', false); $('presBody').innerHTML = ''; return; }
    $('presWrap').hidden = false;
    $('presBody').innerHTML = rows.map(r => `<article class="gw-person ${r.direction === 'in' ? 'gw-person--ok' : 'gw-person--info'} ${esc(r.direction)}"><div class="gw-person__photo" aria-hidden="true">${esc((String(r.name || '?').trim()[0] || '?').toUpperCase())}</div><div class="gw-person__body"><h3 class="gw-person__name">${esc(r.name)}</h3><p class="gw-person__meta">${esc(r.id)} · ${new Date(r.time + 'Z').toLocaleTimeString()}</p></div><div class="gw-person__status">${r.direction === 'in'
      ? `<span class="gw-badge gw-badge--ok">${icon('check')} Entró</span>` : '<span class="gw-badge">Salió</span>'}</div></article>`).join('');
  }

  function setCounts(rows) {
    const inside = rows.filter(r => r.direction === 'in').length;
    $('insideCount').textContent = inside;
    $('outCount').textContent = rows.length - inside;
    $('totalCount').textContent = rows.length;
  }

  // Veredicto del último resultado (mismo lugar siempre). cls: ok | warn | err
  function show(cls, title, html) {
    const b = $('banner');
    b.className = 'gw-verdict gw-verdict--' + cls;
    b.setAttribute('role', cls === 'err' ? 'alert' : 'status');
    b.innerHTML = `<svg class="gw-icon gw-verdict__icon" aria-hidden="true"><use href="${sprite()}#i-${cls === 'ok' ? 'check-lg' : (cls === 'err' ? 'error' : 'alert')}"/></svg><div class="gw-verdict__body"><p class="gw-verdict__title">${esc(title)}</p><p class="gw-verdict__text">${html}</p></div>`;
    b.hidden = false;
  }

  async function handle(result, retry) {
    const who = result.data ? `${esc(result.data.first_name)} ${esc(result.data.last_name)}` : '';
    if (result.result === 'OK') {
      show('ok', result.direction === 'in' ? 'Entró' : 'Salió', `<strong>${who}</strong> — ${esc(result.area)} · ${new Date(result.time + 'Z').toLocaleTimeString()}`);
      await loadAreas(areaId());
    } else if (result.result === 'FOUND_PENDING') {
      show('warn', 'Falta confirmar', `<strong>${who}</strong>. Se registrará <strong>${result.direction === 'in' ? 'ENTRADA' : 'SALIDA'}</strong> a ${esc(result.area)}. <button type="button" id="confirmBtn" class="gw-btn gw-btn--primary gw-btn--xl">Acreditar</button>`);
      $('confirmBtn').addEventListener('click', (e) => busy(e.currentTarget, () => retry(true, result.direction)));
    } else if (result.result === 'ALREADY_ENTERED') {
      show('err', 'Ya está adentro', esc(result.details));
    } else if (result.result === 'LIMIT') {
      show('err', 'Llegó al máximo', esc(result.details));
    } else if (result.result === 'NOT_INSIDE') {
      show('warn', 'No está adentro', esc(result.details));
    } else {
      show('err', 'No encontrado', esc(result.details || 'No se encontró a la persona'));
    }
  }

  async function register(cedula, confirm, forcedDirection, method) {
    if (!areaId()) { showToast('Primero elige una zona', 'error'); return false; }
    method = method || 'cedula';
    try {
      const res = await fetch(`/api/events/${window.EVENT_ID}/areas/${areaId()}/movement`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cedula, direction: forcedDirection || direction, confirm: !!confirm, method }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { show('warn', 'No se pudo registrar', esc(data.detail || 'No se pudo registrar')); return false; }
      await handle(data, (c, d) => register(cedula, c, d, method));
      return FOUND.includes(data.result);          // true = la persona se encontró (la cámara se cierra sola); false = el aviso queda y la cámara sigue abierta
    } catch (e) { show('err', 'Sin conexión', 'No se pudo registrar: sin conexión con el servidor. Inténtalo de nuevo.'); return false; }
  }

  async function scanValue(rawText) {
    let raw = rawText;
    try { raw = await QrCode.resolveDynamic(rawText, window.EVENT_ID, 'area'); } catch (err) { show('warn', 'Código no válido', esc(err.message || 'No se pudo validar el código')); return; }          // QR dinámico de la credencial digital
    const qr = QrCode.parse(raw);
    if (qr && qr.isQr) return register(qr.cedula, false, undefined, 'qr');   // QR propio: en vez de entregar la cédula
    const parsed = GoldenDirectory.parseOldCedulaBarcode(raw);               // cédula vieja (CSV del lector) o ID suelto
    return register(parsed ? parsed.cedula : raw);
  }

  document.addEventListener('click', (e) => {
    const zoneBtn = e.target.closest('.zone-btn[data-zone]');
    if (zoneBtn) {
      $('areaSelect').value = zoneBtn.dataset.zone;
      document.querySelectorAll('.zone-btn').forEach(b => b.setAttribute('aria-pressed', b === zoneBtn ? 'true' : 'false'));
      loadPresence();
      return;
    }
    const dirBtn = e.target.closest('.dir-btn[data-dir]');
    if (dirBtn) {
      direction = dirBtn.dataset.dir;
      $('registerLabel').textContent = direction === 'in' ? 'Registrar entrada' : (direction === 'out' ? 'Registrar salida' : 'Registrar');
      document.querySelectorAll('.dir-btn[data-dir]').forEach(b => { b.classList.toggle('active', b === dirBtn); b.setAttribute('aria-pressed', b === dirBtn ? 'true' : 'false'); });
      return;
    }
    const sug = e.target.closest('#suggest button[data-id]');
    if (sug) { register(sug.dataset.id); $('suggest').innerHTML = ''; $('nameSearch').value = ''; return; }
    if (e.target.closest('#registerBtn')) {
      const raw = $('scanInput').value.trim();
      if (!raw) { showToast('Escribe o escanea una cédula', 'error'); $('scanInput').focus(); return; }
      $('scanInput').value = '';
      busy($('registerBtn'), () => scanValue(raw));
    }
  });

  $('areaSelect').addEventListener('change', loadPresence);

  $('scanInput').addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    let raw = e.target.value.trim(); e.target.value = '';
    if (!raw) return;
    raw = QrCode.collect(raw);                                                // QR en vCard con lector de mano: llega en varias líneas (Fase 10, C)
    if (raw === null) return;
    scanValue(raw);
  });

  // Cámara del dispositivo: escanea varias personas seguidas (cada una entra/sale según la dirección elegida).
  if ($('scanQrBtn')) $('scanQrBtn').addEventListener('click', () => { scanner = QrScanner.open({
    title: 'Escanear QR — Control de Áreas',
    // Si la cámara lee el QR y encuentra a la persona (con o sin autoescaneo) se cierra sola; si no la encuentra o falla, queda abierta y el aviso sale en la pantalla.
    onCode: (text) => { QrCode.resolveDynamic(text, window.EVENT_ID, 'area').then((raw) => { const qr = QrCode.parse(raw); return qr ? register(qr.cedula, false, undefined, 'qr') : false; })
      .then((found) => { if (found && scanner) scanner.close(); })
      .catch((err) => show('warn', 'Código no válido', esc(err.message || 'No se pudo validar el código'))); },
  }); });

  $('nameSearch').addEventListener('input', (e) => {
    const q = e.target.value.trim();
    const found = q ? users.filter(u => GoldenDirectory.matchesWordPrefix(`${u.first_name} ${u.last_name}`, q)).slice(0, 6) : [];
    $('suggest').innerHTML = found.map(u => `<button type="button" data-id="${esc(u.id)}">${esc(u.first_name)} ${esc(u.last_name)} · ${esc(u.id)}</button>`).join('');
  });

  $('faceBtn').addEventListener('click', () => CameraCapture.open({ title: 'Reconocimiento facial', onCapture: async (blob) => {
    const send = async (confirm, forcedDirection) => {
      try {
        const fd = new FormData(); fd.append('file', blob, 'face.jpg'); fd.append('direction', forcedDirection || direction); fd.append('confirm', confirm ? 'true' : 'false');
        const res = await fetch(`/api/events/${window.EVENT_ID}/areas/${areaId()}/movement-face`, { method: 'POST', body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { show('warn', 'No se pudo registrar', esc(data.detail || 'No se pudo registrar')); return; }
        await handle(data, send);
      } catch (e) { show('err', 'Sin conexión', 'No se pudo registrar: sin conexión con el servidor. Inténtalo de nuevo.'); }
    };
    await send(false);
  } }));

  init();
})();
