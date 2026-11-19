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

  fetch('/api/ops/version-check').then((r) => (r.ok ? r.json() : null)).then((d) => {
    if (!d || !d.configured) return;
    if (d.status === 'igual' || d.status === 'desconocida') {          // siempre se ve en qué estado está: al día o sin poder comprobar
      const info = document.createElement('div');
      const ok = d.status === 'igual';
      info.className = 'gw-versionbar gw-versionbar--' + (ok ? 'ok' : 'warn');
      info.setAttribute('role', 'status');
      const c7 = d.local && d.local.commit && d.local.commit !== 'desconocida' ? String(d.local.commit).slice(0, 7) : '';
      info.title = ok ? 'Este servidor tiene la misma versión que producción' + (c7 ? ' (' + c7 + ')' : '') + '.' : (d.message || '');
      info.innerHTML = '<span class="gw-versionbar__txt">' + (ok ? '<strong>Al día</strong>' + (c7 ? ' · ' + esc(c7) : '') : '<strong>Versión sin comprobar</strong>') + '</span>';
      place(info);
      return;
    }
    bar = document.createElement('div');
    bar.className = 'gw-versionbar gw-versionbar--' + (d.status === 'desactualizada' ? 'err' : 'warn');
    bar.setAttribute('role', 'alert');
    bar.title = d.message || '';
    bar.innerHTML = `<span class="gw-versionbar__txt"><strong>${d.status === 'adelantada' ? 'Versión adelantada' : 'Versión desactualizada'}</strong></span>`;
    if (d.status === 'desactualizada' || d.status === 'distinta_version') {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'gw-btn gw-btn--primary gw-btn--sm'; b.textContent = 'Actualizar ahora';
      b.addEventListener('click', () => start(b));
      bar.appendChild(b);
    }
    place(bar);
    fetch('/api/ops/update-status', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).then((s) => { if (s && s.enabled && BUSY.includes(s.state)) poll(0); }).catch(() => {});      // si ya hay una en curso, sigue su avance
  }).catch(() => {});
})();
