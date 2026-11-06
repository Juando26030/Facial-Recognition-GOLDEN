/* Control de áreas (Fase 1.5). Lee window.EVENT_ID / FACIAL / AUTOREG / CAN_REPORT / ENABLED (los pone la plantilla). Sin manejadores en línea: todo por delegación. */
(function () {
  'use strict';
  let direction = 'auto', users = [];
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
    const areas = await getJson(`/api/events/${window.EVENT_ID}/areas`);
    const current = keep || areaId();
    $('areaSelect').innerHTML = areas.length
      ? areas.map(a => `<option value="${a.id}">${esc(a.name)} (${a.inside} adentro${a.allow_reentry ? '' : ' · sin reingresos'})</option>`).join('')
      : '<option value="">Crea zonas en Parámetros del evento</option>';
    if (current) $('areaSelect').value = current;
    await loadPresence();
  }

  function showState(text, isError) {
    const st = $('presState');
    st.textContent = text;
    st.hidden = false;
    st.classList.toggle('gw-state--error', !!isError);
    $('presWrap').hidden = true;
  }

  async function loadPresence() {
    $('presState').hidden = true;
    if (!areaId()) {
      $('presBody').innerHTML = ''; $('insideCount').textContent = '0';
      showState('Aún no hay zonas. Créalas en Parámetros del evento para empezar.', false);
      return;
    }
    $('presLoading').hidden = false;
    let rows;
    try { rows = await getJson(`/api/events/${window.EVENT_ID}/areas/${areaId()}/presence`); }
    catch (e) { $('presLoading').hidden = true; showState('No se pudo cargar quién está en la zona. Cambia de zona o recarga la página.', true); return; }
    $('presLoading').hidden = true;
    $('insideCount').textContent = rows.filter(r => r.direction === 'in').length;
    if (!rows.length) { showState('Sin movimientos todavía. Escanea la primera cédula o QR para empezar.', false); $('presBody').innerHTML = ''; return; }
    $('presWrap').hidden = false;
    $('presBody').innerHTML = rows.map(r => `<tr class="${esc(r.direction)}"><td data-label="Cédula">${esc(r.id)}</td><td data-label="Persona">${esc(r.name)}</td><td data-label="Estado">${r.direction === 'in'
      ? `<span class="gw-badge gw-badge--ok">${icon('check')} Entró</span>` : '<span class="gw-badge">Salió</span>'}</td><td data-label="Hora">${new Date(r.time + 'Z').toLocaleTimeString()}</td></tr>`).join('');
  }

  // Aviso del último resultado (mismo lugar siempre). cls: ok | warn | err
  function show(cls, html) {
    const b = $('banner');
    b.className = 'gw-alert gw-ai__banner gw-alert--' + cls;
    b.setAttribute('role', cls === 'err' ? 'alert' : 'status');
    b.innerHTML = `${icon(cls === 'ok' ? 'check' : (cls === 'err' ? 'error' : 'alert'))}<div>${html}</div>`;
    b.hidden = false;
  }

  async function handle(result, retry) {
    const who = result.data ? `${esc(result.data.first_name)} ${esc(result.data.last_name)}` : '';
    if (result.result === 'OK') {
      show('ok', `${result.direction === 'in' ? 'ENTRÓ' : 'SALIÓ'}: <strong>${who}</strong> — ${esc(result.area)} · ${new Date(result.time + 'Z').toLocaleTimeString()}`);
      await loadAreas(areaId());
    } else if (result.result === 'FOUND_PENDING') {
      show('warn', `Encontrado(a): <strong>${who}</strong>. Se registrará <strong>${result.direction === 'in' ? 'ENTRADA' : 'SALIDA'}</strong> a ${esc(result.area)}. <button type="button" id="confirmBtn" class="gw-btn gw-btn--secondary gw-btn--sm">Acreditar</button>`);
      $('confirmBtn').addEventListener('click', (e) => busy(e.currentTarget, () => retry(true, result.direction)));
    } else if (result.result === 'ALREADY_ENTERED') {
      show('err', `ALERTA: ${esc(result.details)}`);
    } else if (result.result === 'NOT_INSIDE') {
      show('warn', esc(result.details));
    } else {
      show('warn', esc(result.details || 'No se encontró a la persona'));
    }
  }

  async function register(cedula, confirm, forcedDirection, method) {
    if (!areaId()) { showToast('Primero elige una zona', 'error'); return; }
    method = method || 'cedula';
    try {
      const res = await fetch(`/api/events/${window.EVENT_ID}/areas/${areaId()}/movement`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cedula, direction: forcedDirection || direction, confirm: !!confirm, method }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { show('warn', esc(data.detail || 'No se pudo registrar')); return; }
      await handle(data, (c, d) => register(cedula, c, d, method));
    } catch (e) { show('err', 'No se pudo registrar: sin conexión con el servidor. Inténtalo de nuevo.'); }
  }

  function scanValue(raw) {
    const qr = QrCode.parse(raw);
    if (qr && qr.isQr) return register(qr.cedula, false, undefined, 'qr');   // QR propio: en vez de entregar la cédula
    const parsed = GoldenDirectory.parseOldCedulaBarcode(raw);               // cédula vieja (CSV del lector) o ID suelto
    return register(parsed ? parsed.cedula : raw);
  }

  document.addEventListener('click', (e) => {
    const dirBtn = e.target.closest('.dir-btn[data-dir]');
    if (dirBtn) {
      direction = dirBtn.dataset.dir;
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
    const raw = e.target.value.trim(); e.target.value = '';
    if (!raw) return;
    scanValue(raw);
  });

  // Cámara del dispositivo: escanea varias personas seguidas (cada una entra/sale según la dirección elegida).
  if ($('scanQrBtn')) $('scanQrBtn').addEventListener('click', () => QrScanner.open({
    title: 'Escanear QR — Control de Áreas',
    onCode: (text) => { const qr = QrCode.parse(text); if (qr) register(qr.cedula, false, undefined, 'qr'); },
  }));

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
        if (!res.ok) { show('warn', esc(data.detail || 'No se pudo registrar')); return; }
        await handle(data, send);
      } catch (e) { show('err', 'No se pudo registrar: sin conexión con el servidor. Inténtalo de nuevo.'); }
    };
    await send(false);
  } }));

  init();
})();
