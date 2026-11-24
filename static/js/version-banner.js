/* Franja de versión (Fase 6): solo en servidores locales (PRODUCTION_URL definida). Si el servidor no tiene la versión de producción, muestra un aviso fijo arriba y el botón «Actualizar ahora».
   En la nube el servidor responde {configured:false} y no se pinta nada. Una consulta al abrir la página (el servidor guarda la comparación 5 min). Texto escapado.
   Actualizar: confirmación con showConfirm; si hay un turno en marcha el servidor responde 409 «shift_active» y se pide una SEGUNDA confirmación más fuerte. Después se muestra el avance
   (respaldo, descarga, migraciones, reinicio); mientras el servidor reinicia las consultas fallan y se siguen intentando. Al terminar, se recarga la página. */
(function () {
  'use strict';
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const STEP_TEXT = {
    pending: 'Petición enviada…', backup: 'Guardando una copia de la base de datos…', download: 'Descargando la versión nueva…', apply: 'Instalando la versión nueva…',
    migrate: 'Actualizando la base de datos…', restart: 'Reiniciando el servidor…',
  };
  const BUSY = Object.keys(STEP_TEXT);
  let bar = null;
  // La franja va en el encabezado, justo al lado del logo (fija con él); si la página no tiene ese encabezado, queda arriba del todo.
  function place(el) {
    const logo = document.querySelector('.golden-header-container .golden-logo');
    if (logo && logo.parentNode) logo.parentNode.insertBefore(el, logo.nextSibling);
    else document.body.insertBefore(el, document.body.firstChild);
  }

  function paintProgress(text, cls) {
    if (!bar) return;
    bar.className = 'gw-versionbar gw-versionbar--' + (cls || 'warn');
    bar.title = text;
    bar.innerHTML = '<span class="gw-versionbar__txt"><strong>Actualización:</strong> ' + esc(text) + '</span>';
  }

  function poll(fails) {
    fetch('/api/ops/update-status', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : Promise.reject(new Error('estado')))).then((s) => {
      if (BUSY.includes(s.state)) { paintProgress(STEP_TEXT[s.state] + ' No apagues el equipo.'); setTimeout(() => poll(0), 3000); return; }
      if (s.state === 'ok') { paintProgress('Listo: el servidor ya tiene la versión de producción.', 'warn'); if (window.showToast) window.showToast('Servidor actualizado', 'success'); setTimeout(() => location.reload(), 1500); return; }
      if (s.state === 'rolledback' || s.state === 'error') { paintProgress((s.message || 'No se pudo actualizar.') + ' Se dejó la versión anterior funcionando.', 'err'); return; }
      paintProgress('Sin actividad de actualización.');
    }).catch(() => {                                         // el servidor se está reiniciando: es normal por unos minutos
      if (fails > 100) { paintProgress('El servidor no responde. Espera unos minutos y recarga la página.', 'err'); return; }
      paintProgress('Reiniciando el servidor… esta página volverá sola.');
      setTimeout(() => poll(fails + 1), 4000);
    });
  }

  async function start(button) {
    const ask = window.showConfirm || (() => Promise.resolve(false));          // regla del repo: nunca confirm() del navegador; sin toast.js no se actualiza (F5-9 A-13)
    const ok = await ask('Se va a actualizar este servidor a la versión de producción. Primero se guarda una copia de la base de datos y el sistema se detiene unos minutos (no apagues el equipo). ¿Continuar?', { variant: 'warning', confirmLabel: 'Sí, actualizar ahora' });
    if (!ok) return;
    button.disabled = true;
    const post = (confirmShift) => fetch('/api/ops/update', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm_shift: !!confirmShift }) });
    let res = await post(false);
    let data = await res.json().catch(() => ({}));
    const detail = data && data.detail && typeof data.detail === 'object' ? data.detail : null;
    if (res.status === 409 && detail && detail.code === 'shift_active') {
      const sure = await ask(esc(detail.message) + '<br><br><strong>Si actualizas ahora, quien esté registrando perderá la conexión unos minutos.</strong> ¿Actualizar de todos modos?', { variant: 'danger', confirmLabel: 'Sí, actualizar aunque haya turno' });
      if (!sure) { button.disabled = false; return; }
      res = await post(true);
      data = await res.json().catch(() => ({}));
    }
    if (!res.ok) {
      const msg = (data && data.detail && (data.detail.message || data.detail)) || 'No se pudo iniciar la actualización';
      if (window.showToast) window.showToast(typeof msg === 'string' ? msg : 'No se pudo iniciar la actualización', 'error');
      button.disabled = false;
      return;
    }
    paintProgress(STEP_TEXT.pending);
    poll(0);
  }

  /* Vista de prueba de los estados (solo se ve, no cambia nada): añade a la dirección ?gwver=aldia | sincomprobar | desactualizada  (p. ej. https://localhost:8443/eventos?gwver=desactualizada). */
  const PREVIEW = { aldia: 'igual', sincomprobar: 'desconocida', desactualizada: 'desactualizada' };
  const pv = PREVIEW[new URLSearchParams(location.search).get('gwver')];
  fetch('/api/ops/version-check').then((r) => (r.ok ? r.json() : null)).then((d0) => {
    const d = pv && d0 && d0.configured ? Object.assign({}, d0, { status: pv, message: 'Vista de prueba: esto es solo para ver cómo se muestra el aviso.' }) : d0;
    if (!d || !d.configured) return;
    if (d.status === 'igual' || d.status === 'desconocida') {          // siempre se ve en qué estado está: al día o sin poder comprobar
      const info = document.createElement('div');
      const ok = d.status === 'igual';
      info.className = 'gw-versionbar gw-versionbar--' + (ok ? 'ok' : 'warn');
      info.setAttribute('role', 'status');
      const c7 = d.local && d.local.commit && d.local.commit !== 'desconocida' ? String(d.local.commit).slice(0, 7) : '';
      info.title = ok ? 'Este servidor tiene la misma versión que producción' + (c7 ? ' (' + c7 + ')' : '') + '.' : (d.message || '');
      info.innerHTML = '<span class="gw-versionbar__txt">' + (ok ? '<strong>Al día</strong>' + (c7 ? '<span class="gw-vb-extra"> · ' + esc(c7) + '</span>' : '') : '<strong>Sin comprobar</strong>') + '</span>';
      place(info);
      return;
    }
    bar = document.createElement('div');
    bar.className = 'gw-versionbar gw-versionbar--' + (d.status === 'desactualizada' || d.status === 'distinta_version' ? 'err' : 'warn');          // sin comprobar = naranja; no está al día = rojo
    bar.setAttribute('role', 'alert');
    bar.title = (d.status === 'adelantada' ? 'Versión adelantada. ' : 'Versión desactualizada. ') + (d.message || '');
    bar.innerHTML = `<span class="gw-versionbar__txt"><strong>${d.status === 'adelantada' ? 'Adelantada' : 'Desactualizada'}</strong></span>`;
    if (d.status === 'desactualizada' || d.status === 'distinta_version') {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'gw-btn gw-btn--primary gw-btn--sm'; b.innerHTML = '<span class="gw-vb-long">Actualizar ahora</span><span class="gw-vb-short">Actualizar</span>';
      if (pv) { b.title = 'Vista de prueba: no actualiza'; b.addEventListener('click', () => { if (window.showToast) window.showToast('Vista de prueba: no se actualiza nada', 'info'); }); } else b.addEventListener('click', () => start(b));
      bar.appendChild(b);
    }
    place(bar);
    fetch('/api/ops/update-status', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).then((s) => { if (s && s.enabled && BUSY.includes(s.state)) poll(0); }).catch(() => {});      // si ya hay una en curso, sigue su avance
  }).catch(() => {});

  /* «Conectar: 192.168.1.20:8443» (azul, junto a la versión): la dirección que otros equipos de la MISMA red escriben en el navegador para usar este servidor local. Clic = copia el enlace.
     Solo en servidores locales; el instalador ya abre el puerto en el cortafuegos para la red local (install.ps1). */
  fetch('/api/ops/local-address').then((r) => (r.ok ? r.json() : null)).then((a) => {
    if (!a || !a.configured) return;
    if (!a.addresses || !a.addresses.length) {                 // sin red local (cable sin DHCP, sin Wi‑Fi…): se avisa en vez de callar
      const none = document.createElement('div');
      none.className = 'gw-versionbar gw-versionbar--info gw-versionbar--err';
      none.title = 'Este equipo no tiene dirección en la red local, así que otros equipos no pueden conectarse. Revisa el cable o el Wi‑Fi (el router debe darle una dirección). Puerto ' + a.port + '.';
      none.innerHTML = '<span class="gw-versionbar__txt"><strong>Sin red local</strong></span>';
      const l0 = Array.from(document.querySelectorAll('.golden-header-container .gw-versionbar')).pop();
      if (l0 && l0.parentNode) l0.parentNode.insertBefore(none, l0.nextSibling); else place(none);
      return;
    }
    const url = (ip) => 'https://' + ip + ':' + a.port;
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'gw-versionbar gw-versionbar--info';
    chip.title = 'Desde otro computador o celular de ESTA misma red, abre ' + a.addresses.map(url).join('  o  ') + ' en el navegador Para que no salga «No seguro», cada equipo instala una vez el certificado desde ' + url(a.addresses[0]) + '/certificado. Clic para copiar el enlace.';
    /* 24-nov-2026: por dónde va cada dirección (cable / Wi‑Fi) y TODAS si hay varias. Si solo hay Wi‑Fi, aviso: ese Wi‑Fi suele ser el de la casa o del lugar, no el router del evento
       (caso real: el cable no estaba puesto y se recomendó la red de la casa; los demás equipos, en el router, no entraban). */
    const KIND = { cable: 'cable', wifi: 'Wi‑Fi', otro: '' };
    const det = Array.isArray(a.details) && a.details.length ? a.details : a.addresses.map((ip) => ({ ip, kind: 'otro' }));
    const tag = (d) => (KIND[d.kind] ? ' (' + KIND[d.kind] + ')' : '');
    if (det.length > 1) chip.title = 'Direcciones de este servidor: ' + det.map((d) => url(d.ip) + tag(d)).join(' · ') + '. Usa la de la red a la que están conectados los demás equipos (la primera es la recomendada: el cable al router del evento). ' + chip.title;
    chip.innerHTML = '<span class="gw-versionbar__txt"><strong class="gw-vb-lbl">Conectar' + esc(tag(det[0])) + ': </strong>' + esc(a.addresses[0] + ':' + a.port) + (det.length > 1 ? ' <span class="gw-vb-more">+' + (det.length - 1) + '</span>' : '') + '</span>';
    chip.addEventListener('click', () => {
      const text = url(a.addresses[0]);
      const done = () => { if (window.showToast) window.showToast('Enlace copiado: ' + text, 'success'); };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, () => { if (window.showToast) window.showToast(text, 'info'); });
      else if (window.showToast) window.showToast(text, 'info');
    });
    const last = Array.from(document.querySelectorAll('.golden-header-container .gw-versionbar')).pop();
    if (last && last.parentNode) last.parentNode.insertBefore(chip, last.nextSibling); else place(chip);
    if (det.length && !det.some((d) => d.kind === 'cable') && det[0].kind === 'wifi') {          // solo Wi‑Fi: probablemente NO es la red del router del evento
      const warn = document.createElement('div');
      warn.className = 'gw-versionbar gw-versionbar--info gw-versionbar--err';
      warn.title = 'Este servidor solo está conectado por Wi‑Fi. Si los computadores y celulares del evento se conectan al router del evento, conecta el cable del router a este servidor: la dirección de «Conectar» cambiará sola a la del cable. El Wi‑Fi puede seguir encendido para tener internet.';
      warn.innerHTML = '<span class="gw-versionbar__txt"><strong>Sin cable al router</strong></span>';
      chip.parentNode ? chip.parentNode.insertBefore(warn, chip.nextSibling) : place(warn);
    }
    const cert = document.createElement('a');          // instrucciones para quitar el aviso «No seguro» en los demás equipos (instalar la autoridad del servidor una vez)
    cert.className = 'gw-versionbar gw-versionbar--info';
    cert.href = '/certificado';
    cert.target = '_blank';
    cert.rel = 'noopener';
    cert.title = 'Cómo quitar el aviso «No seguro» en los computadores y celulares que se conectan a este servidor (se instala el certificado una sola vez).';
    cert.innerHTML = '<span class="gw-versionbar__txt">Certificado</span>';
    chip.parentNode ? chip.parentNode.insertBefore(cert, chip.nextSibling) : place(cert);
  }).catch(() => {});

  /* ID del servidor (morado claro, a la derecha de «Al día» y de la IP): es la llave de producto con la que se instaló; la ven los administradores en Configuración › Servidor local. Clic = copia. */
  fetch('/api/ops/server-id').then((r) => (r.ok ? r.json() : null)).then((s) => {
    if (!s || !s.configured || !s.id) return;
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'gw-versionbar gw-versionbar--id';
    chip.title = 'ID de este servidor (su llave de producto). Clic para copiarlo.';
    chip.innerHTML = '<span class="gw-versionbar__txt"><strong class="gw-vb-lbl">ID: </strong>' + esc(s.id) + '</span>';
    chip.addEventListener('click', () => {
      const done = () => { if (window.showToast) window.showToast('ID copiado: ' + s.id, 'success'); };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(s.id).then(done, () => { if (window.showToast) window.showToast(s.id, 'info'); });
      else if (window.showToast) window.showToast(s.id, 'info');
    });
    // va al final de las etiquetas del encabezado, pero esperando a que la de la IP (que llega por otra consulta) ya esté puesta
    setTimeout(() => {
      const last = Array.from(document.querySelectorAll('.golden-header-container .gw-versionbar')).pop();
      if (last && last.parentNode) last.parentNode.insertBefore(chip, last.nextSibling); else place(chip);
    }, 900);
  }).catch(() => {});
})();
