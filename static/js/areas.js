/* Control de áreas (Fase 1.5). Lee window.EVENT_ID / FACIAL / AUTOREG / CAN_REPORT / ENABLED (los pone la plantilla). Sin manejadores en línea: todo por delegación. */
(function () {
  'use strict';
  let direction = 'auto', users = [], scanner = null;
  const FOUND = ['OK', 'FOUND_PENDING', 'ALREADY_ENTERED', 'NOT_INSIDE', 'LIMIT'];          // resultados en los que la persona sí se encontró
  const $ = (id) => document.getElementById(id);
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  const areaId = () => $('areaSelect').value;
  /* 0161: la zona y el movimiento elegidos se recuerdan en esta tableta; con «Bloquear configuración» (Parámetros) el digitador no los puede cambiar sin la contraseña. */
  const SEL_KEY = 'gw-areas-sel:' + window.EVENT_ID;
  const LOCK = window.GWConfigLock || { isLocked: () => false, banner: () => {}, onChange: () => {} };
  const locked = () => LOCK.isLocked('areas');
  function saveSel() { try { localStorage.setItem(SEL_KEY, JSON.stringify({ zone: areaId(), dir: direction })); } catch (e) { /* sin almacenamiento: no se recuerda */ } }
  function readSel() { try { return JSON.parse(localStorage.getItem(SEL_KEY) || '{}') || {}; } catch (e) { return {}; } }
  function paintLock() {
    const on = locked();
    document.querySelectorAll('.zone-btn, .dir-btn, #areaSelect').forEach(el => { el.disabled = on; el.classList.toggle('gw-locked-ctl', on); });
  }
  function setDirection(dir) {
    const btn = document.querySelector(`.dir-btn[data-dir="${dir}"]`);
    if (!btn) return;
    direction = dir;
    $('registerLabel').textContent = direction === 'in' ? 'Registrar entrada' : (direction === 'out' ? 'Registrar salida' : 'Registrar');
    paintHero();
    document.querySelectorAll('.dir-btn[data-dir]').forEach(b => { b.classList.toggle('active', b === btn); b.setAttribute('aria-pressed', b === btn ? 'true' : 'false'); });
  }
  const busy = (btn, work) => (window.GW && window.GW.busy ? window.GW.busy(btn, work) : Promise.resolve(work()));
  const sprite = () => { const u = document.querySelector('.gw-icon use'); return u ? u.getAttribute('href').split('#')[0] : ''; };
  const icon = (name) => `<svg class="gw-icon" aria-hidden="true"><use href="${sprite()}#i-${name}"/></svg>`;

  /* Sin red (docs/28, static/js/offline-data.js): las lecturas salen de la última copia cifrada del dispositivo y cada entrada/salida se guarda y se envía al volver la conexión. */
  const OFF = window.GWOff || null;
  let allAreas = [];
  async function getJson(url) {
    if (OFF) return OFF.json(url);
    const res = await fetch(url);
    if (!res.ok) throw new Error('http ' + res.status);
    return res.json();
  }
  const presUrl = (id) => `/api/events/${window.EVENT_ID}/areas/${id}/presence`;
  const areasUrl = () => `/api/events/${window.EVENT_ID}/areas`;
  /* Con red y en reposo: deja guardado quién está en CADA zona, para poder aplicar «sin reingresos» si después se cae la red. */
  async function warmPresence() {
    if (!OFF || OFF.off()) return;
    for (const a of allAreas.filter(x => !x.is_group).slice(0, 40)) { if (String(a.id) === String(areaId())) continue; try { await OFF.json(presUrl(a.id)); } catch (e) { return; } }
  }
  async function registerOffline(cedula, confirm, forcedDirection, method) {
    const low = String(cedula || '').trim().toLowerCase();
    const byCode = low ? users.find(x => x.code && String(x.code).toLowerCase() === low) : null;
    const u = window.EVENT_CODE_ONLY === true ? byCode : (window.EVENT_CODE_FIRST === true ? (byCode || users.find(x => x.id === cedula)) : (users.find(x => x.id === cedula) || byCode));          // 0166/0168
    if (!u) { show('err', 'No encontrado', 'Esa persona no está en la copia de este dispositivo'); return false; }
    const byId = {}; allAreas.forEach(a => { byId[a.id] = a; });
    const area = byId[areaId()];
    if (!area) { show('warn', 'No se pudo registrar', 'La zona no está en la copia de este dispositivo'); return false; }
    const parent = area.parent_id ? byId[area.parent_id] : null;
    const siblings = parent ? allAreas.filter(a => a.parent_id === parent.id) : [area];
    const presence = {}, rowsBy = {};
    for (const a of siblings) { const rows = (await OFF.get(presUrl(a.id))) || []; rowsBy[a.id] = rows; presence[a.id] = {}; rows.forEach(r => { presence[a.id][String(r.id)] = r.direction; }); }
    const r = OFF.areaDecide({ area, parent, siblings, presence, user: u, direction: forcedDirection || direction, confirm: !!confirm, autoRegister: !!window.AUTOREG, autoScan: false });
    if (r.result === 'OK') {
      const who = `${u.first_name || ''} ${u.last_name || ''}`.trim();
      const res = await OFF.send(`/api/events/${window.EVENT_ID}/areas/${area.id}/movement`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cedula: u.id, direction: r.direction, confirm: true, method, client_time: r.time }) }, `${r.direction === 'in' ? 'Entrada' : 'Salida'} a ${r.area}: ${who}`, null, ['OK']);
      if (!res.queued) { const data = await res.json().catch(() => ({})); if (!res.ok) { show('warn', 'No se pudo registrar', esc(data.detail || 'No se pudo registrar')); return false; } await handle(data, (c, d) => register(cedula, c, d, method)); return FOUND.includes(data.result); }
      await OFF.put(presUrl(area.id), [{ id: u.id, name: who, direction: r.direction, time: r.time }].concat(rowsBy[area.id].filter(x => String(x.id) !== String(u.id))));
      const delta = r.direction === 'in' ? 1 : -1;
      allAreas = allAreas.map(a => (a.id === area.id ? Object.assign({}, a, { inside: Math.max(0, (a.inside || 0) + delta) }) : a));
      await OFF.put(areasUrl(), allAreas);
      r.details = 'Sin conexión: queda guardado en este dispositivo y se envía solo al volver la red';
    }
    await handle(r, (c, d) => registerOffline(cedula, c, d, method));
    return FOUND.includes(r.result);
  }

  async function init() {
    if (!window.ENABLED) return;
    $('autoregLabel').textContent = window.AUTOREG ? 'ON' : 'OFF';
    if (window.FACIAL) $('faceBtn').hidden = false;
    if (window.CAN_REPORT) $('reportBtn').hidden = false;
    const sel = readSel();
    if (sel.dir) setDirection(sel.dir);
    try {
      users = OFF ? await OFF.users() : await getJson(`/api/users?event_id=${window.EVENT_ID}`);
      await loadAreas(sel.zone);
      warmPresence();
    } catch (e) {
      showState('No se pudo cargar la información. Revisa la conexión y recarga la página.', true);
    }
    $('scanInput').focus();
  }

  async function loadAreas(keep) {
    const all = await getJson(areasUrl());
    allAreas = all;
    // Subcategorías: solo se elige una zona «hoja» (suelta o subcategoría); la principal con subcategorías no recibe movimientos y se muestra como «Salón A › Entrada A».
    const byId = {}; all.forEach(a => { byId[a.id] = a; });
    const areas = all.filter(a => !a.is_group).map(a => (a.parent_id && byId[a.parent_id] ? Object.assign({}, a, { name: byId[a.parent_id].name + ' › ' + a.name }) : a));
    const current = keep || areaId();
    $('areaSelect').innerHTML = areas.length
      ? areas.map(a => `<option value="${a.id}">${esc(a.name)} (${a.inside} adentro${a.allow_reentry ? '' : ' · sin reingresos'})</option>`).join('')
      : '<option value="">Crea zonas en Parámetros del evento</option>';
    if (current && areas.some(a => String(a.id) === String(current))) $('areaSelect').value = current;
    renderZones(areas);
    paintLock();
    LOCK.banner($('lockBar'), 'areas', () => { const o = $('areaSelect').selectedOptions[0]; const d = { auto: 'automático', in: 'entrada', out: 'salida' }[direction]; return (o ? 'zona ' + o.textContent.replace(/ \(.*$/, '') : 'sin zona') + ' · movimiento ' + d; });
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
    try { rows = await getJson(presUrl(areaId())); }
    catch (e) { $('presLoading').hidden = true; showState('No se pudo cargar quién está en la zona. Cambia de zona o recarga la página.', true); return; }
    $('presLoading').hidden = true;
    setCounts(rows);
    if (!rows.length) { showState('Sin movimientos todavía. Escanea la primera cédula o QR para empezar.', false); $('presBody').innerHTML = ''; return; }
    $('presWrap').hidden = false;
    $('presBody').innerHTML = rows.map(r => `<article class="gw-person ${r.direction === 'in' ? 'gw-person--ok' : 'gw-person--info'} ${esc(r.direction)}"><div class="gw-person__photo" aria-hidden="true">${esc((String(r.name || '?').trim()[0] || '?').toUpperCase())}</div><div class="gw-person__body"><h3 class="gw-person__name">${esc(r.name)}</h3><p class="gw-person__meta">${esc(r.id)} · ${new Date(r.time + 'Z').toLocaleTimeString()}</p></div><div class="gw-person__status">${r.direction === 'in'
      ? `<span class="gw-badge gw-badge--ok">${icon('check')} Entró</span>` : '<span class="gw-badge">Salió</span>'}</div></article>`).join('');
  }

  let counts = null;
  function setCounts(rows) {
    const inside = rows.filter(r => r.direction === 'in').length;
    $('insideCount').textContent = inside;
    $('outCount').textContent = rows.length - inside;
    $('totalCount').textContent = rows.length;
    counts = { inside, out: rows.length - inside, total: rows.length };
    paintHero();
  }
  /* 25-nov-2026 (Juan David): arriba, en grande, la zona elegida y sus cifras (adentro · salieron · con movimientos) y el movimiento. */
  function paintHero() {
    const hero = $('areaHero'); if (!hero) return;
    const o = $('areaSelect') && $('areaSelect').selectedOptions && $('areaSelect').selectedOptions[0];
    const zone = o && o.value ? o.textContent.replace(/ \(.*$/, '') : '';
    hero.classList.toggle('gw-hero--empty', !zone);
    const dir = { auto: 'Automático (entrada o salida)', in: 'Entrada', out: 'Salida' }[direction];
    hero.innerHTML = '<p class="gw-hero__kicker">Estás registrando en</p>' + (zone
      ? `<div class="gw-hero__row"><span class="gw-hero__title">${esc(zone)}</span><span class="gw-hero__stats">${counts ? `<b>${counts.inside}</b> adentro · <b>${counts.out}</b> salieron · <b>${counts.total}</b> con movimientos · ` : ''}Movimiento: <b>${esc(dir)}</b></span></div>`
      : '<div class="gw-hero__row"><span class="gw-hero__title">Elige la zona abajo</span></div>');
  }
  /* 25-nov-2026: tarjeta de la persona encontrada (static/js/person-card.js): campos «Mostrar en el registro», estado en Registro (rojo si no) y «Acreditar» al lado cuando falta confirmar. */
  function showPerson(data, actionHtml) {
    const b = $('personBanner'); if (!b) return;
    if (!data || !window.GWPersonCard) { b.hidden = true; b.innerHTML = ''; return; }
    const full = users.find(x => String(x.id) === String(data.id)) || data;
    const card = GWPersonCard.render(full, { action: actionHtml || '' });
    b.className = card.cls + ' gw-ai__person'; b.innerHTML = card.html; b.hidden = false;
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
    showPerson(result.data, result.result === 'FOUND_PENDING' ? `<button type="button" id="confirmBtn" class="gw-btn gw-btn--primary gw-btn--xl">${icon('check-lg')} Acreditar ${result.direction === 'in' ? 'entrada' : 'salida'}</button>` : '');
    if (result.result === 'OK') {
      show('ok', result.direction === 'in' ? 'Entró' : 'Salió', `<strong>${who}</strong> — ${esc(result.area)} · ${new Date(result.time + 'Z').toLocaleTimeString()}${result.details ? ' · ' + esc(result.details) : ''}`);
      await loadAreas(areaId());
    } else if (result.result === 'FOUND_PENDING') {
      show('warn', 'Falta confirmar', `<strong>${who}</strong>. Se registrará <strong>${result.direction === 'in' ? 'ENTRADA' : 'SALIDA'}</strong> a ${esc(result.area)}: pulsa «Acreditar» junto a la persona.`);
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
    if (OFF && OFF.off()) return registerOffline(cedula, confirm, forcedDirection, method);
    try {
      const res = await fetch(`/api/events/${window.EVENT_ID}/areas/${areaId()}/movement`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cedula, direction: forcedDirection || direction, confirm: !!confirm, method }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { show('warn', 'No se pudo registrar', esc(data.detail || 'No se pudo registrar')); return false; }
      await handle(data, (c, d) => register(cedula, c, d, method));
      return FOUND.includes(data.result);          // true = la persona se encontró (la cámara se cierra sola); false = el aviso queda y la cámara sigue abierta
    } catch (e) { if (OFF) return registerOffline(cedula, confirm, forcedDirection, method); show('err', 'Sin conexión', 'No se pudo registrar: sin conexión con el servidor. Inténtalo de nuevo.'); return false; }
  }

  document.addEventListener('click', (e) => {
    const zoneBtn = e.target.closest('.zone-btn[data-zone]');
    if (zoneBtn) {
      if (locked()) return;
      $('areaSelect').value = zoneBtn.dataset.zone;
      saveSel(); paintHero();
      document.querySelectorAll('.zone-btn').forEach(b => b.setAttribute('aria-pressed', b === zoneBtn ? 'true' : 'false'));
      loadPresence();
      return;
    }
    const dirBtn = e.target.closest('.dir-btn[data-dir]');
    if (dirBtn) {
      if (locked()) return;
      setDirection(dirBtn.dataset.dir);
      saveSel();
      return;
    }
    if (e.target.closest('#registerBtn')) {
      if (!$('scanInput').value.trim()) { showToast('Escribe o escanea una cédula o un nombre', 'error'); $('scanInput').focus(); return; }
      busy($('registerBtn'), () => finder.submit());
    }
  });

  $('areaSelect').addEventListener('change', () => { saveSel(); paintHero(); loadPresence(); });
  LOCK.onChange((scope) => { if (scope === 'areas') paintLock(); });

  // Buscador único (static/js/person-finder.js): cédula, nombre o empresa con coincidencias en vivo; QR propio, vCard (de Golden o ajena), dinámico y lector de mano. Elegir de la lista o Enter con un solo resultado exacto registra.
  const finder = PersonFinder.attach({
    input: $('scanInput'), box: $('suggest'), users: () => users, purpose: 'area',
    onPick: (u, via) => register(u.id, false, undefined, via === 'qr' ? 'qr' : 'cedula'),
    onRaw: (cedula, via) => register(cedula, false, undefined, via === 'qr' ? 'qr' : 'cedula'),
    onMessage: (text) => show('warn', 'Búsqueda', esc(text)),
    onTyping: (t) => { const b = $('personBanner'); if (String(t || '').trim() && b && !b.hidden) { b.hidden = true; b.innerHTML = ''; } },          // 26-nov-2026: al escribir otra búsqueda se quita la tarjeta anterior
  });

  // Cámara del dispositivo: el MISMO escáner del Registro (selector «Cédula vieja · Cédula nueva · QR» en la misma ventana) y escanea varias personas seguidas (cada una entra/sale según la dirección elegida).
  // Si la cámara lee el código y encuentra a la persona (con o sin autoescaneo) se cierra sola; si no la encuentra o falla, queda abierta y el aviso sale en la pantalla.
  if (window.QrScanner && QrScanner.warm && $('scanQrBtn')) QrScanner.warm();          // deja listo el lector de cédula en reposo (abrir la cámara no traba)
  if ($('scanQrBtn')) $('scanQrBtn').addEventListener('click', () => { scanner = QrScanner.open({
    title: 'Escanear cédula o QR — Control de Áreas',
    formats: ['qr_code', 'pdf417'],
    modes: ['old', 'new', 'qr'],                       // cédula vieja (código de barras) · cédula nueva (3 líneas) · QR
    onCedula: (d) => { register(d.cedula, false, undefined, 'cedula').then((found) => { if (found && scanner) scanner.close(); }); },
    onCode: (text, format) => { QrCode.resolveDynamic(text, window.EVENT_ID, 'area').then((raw) => {
        const r = QrCode.classify(raw, format, window.GoldenDirectory && GoldenDirectory.parseOldCedulaBarcode);
        return r ? register(r.cedula, false, undefined, r.kind === 'qr' ? 'qr' : 'cedula') : (show('warn', 'No se reconoció el código', 'Acerca la cámara al QR o al reverso de la cédula'), false); })
      .then((found) => { if (found && scanner) scanner.close(); })
      .catch((err) => show('warn', 'Código no válido', esc(err.message || 'No se pudo validar el código'))); },
  }); });

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
