/* Bloqueo de la configuración del digitador (0161, app/config_lock.py). Lee el bloque JSON #gwConfigLock que pone la plantilla:
   {event_id, has_password, registro, areas, inventory} (true = esa pantalla está bloqueada para quien la usa).
   GWConfigLock.isLocked(scope) · GWConfigLock.unlock(scope) → Promise<boolean> (pide la contraseña) · GWConfigLock.relock(scope) · GWConfigLock.onChange(fn).
   El desbloqueo dura hasta que se vuelve a bloquear o se recarga la página. Solo es una ayuda contra errores: el servidor valida todo igual. */
(function () {
  'use strict';
  let state = {};
  try { const el = document.getElementById('gwConfigLock'); state = el ? JSON.parse(el.textContent || '{}') : {}; } catch (e) { state = {}; }
  const open = {};
  const listeners = [];
  const LABEL = { registro: 'la configuración del registro', areas: 'la zona y el movimiento', inventory: 'lo que se entrega' };
  const notify = (scope) => listeners.forEach((fn) => { try { fn(scope, isLocked(scope)); } catch (e) { /* una pantalla rota no frena a las demás */ } });
  function isLocked(scope) { return !!state[scope] && !open[scope]; }

  function askPassword(scope) {
    return new Promise((resolve) => {
      if (typeof window.openGwDialog !== 'function') { resolve(null); return; }
      let d;
      const done = (v) => { d.close(); resolve(v); };
      d = window.openGwDialog({
        title: 'Configuración bloqueada',
        bodyHtml: '<p class="gw-modal__text">Un coordinador dejó fija ' + LABEL[scope] + ' en esta pantalla para que no se cambie por error. Para cambiarla escribe la contraseña de desbloqueo del evento.</p>' +
                  '<div class="gw-field"><label class="gw-label" for="gwLockPw">Contraseña de desbloqueo</label><input id="gwLockPw" class="gw-input" type="password" autocomplete="off"></div>',
        buttons: [{ id: 'gwLockCancel', cls: 'gw-btn--secondary', label: 'Cancelar' }, { id: 'gwLockOk', cls: 'gw-btn--primary', label: 'Desbloquear' }],
        onEscape: () => done(null),
      });
      const input = d.dlg.querySelector('#gwLockPw');
      const ok = () => done(input.value || null);
      d.dlg.querySelector('#gwLockCancel').addEventListener('click', () => done(null));
      d.dlg.querySelector('#gwLockOk').addEventListener('click', ok);
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); ok(); } });
      input.focus();
    });
  }

  async function unlock(scope) {
    if (!isLocked(scope)) return true;
    if (!state.has_password) {
      if (window.showToast) showToast('Esta configuración está bloqueada y el evento no tiene contraseña de desbloqueo. Pide a un coordinador que la desbloquee en Parámetros del evento.', 'error');
      return false;
    }
    const pw = await askPassword(scope);
    if (!pw) return false;
    let res, data = {};
    try {
      res = await fetch(`/api/events/${state.event_id}/config-lock/unlock`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scope, password: pw }) });
      data = await res.json().catch(() => ({}));
    } catch (e) { if (window.showToast) showToast('Sin conexión: no se pudo comprobar la contraseña.', 'error'); return false; }
    if (!res.ok) { if (window.showToast) showToast(data.detail || 'No se pudo desbloquear', 'error'); return false; }
    open[scope] = true;
    if (window.showToast) showToast('Configuración desbloqueada. Cuando termines, pulsa «Bloquear de nuevo».', 'success');
    notify(scope);
    return true;
  }
  function relock(scope) { if (state[scope]) { delete open[scope]; notify(scope); } }

  /* Aviso estándar dentro de una pantalla: «Configuración fija: … [Desbloquear]» / «Desbloqueada [Bloquear de nuevo]». `box` = el contenedor donde va. */
  function banner(box, scope, describe) {
    if (!box || !state[scope]) return;
    box._gwDescribe = describe;
    if (box._gwPaint) { box._gwPaint(); return; }          // ya estaba puesto: solo se repinta con lo elegido ahora
    const paint = () => {
      const locked = isLocked(scope);
      box.hidden = false;
      box.className = 'gw-alert ' + (locked ? 'gw-alert--info' : 'gw-alert--warn') + ' gw-lockbar';
      const what = box._gwDescribe ? box._gwDescribe() : '';
      box.innerHTML = '';
      const text = document.createElement('div');
      text.innerHTML = locked
        ? '<b>Configuración fija.</b> Un coordinador la dejó así para que no se cambie por error' + (what ? ': ' + window.escapeHtml(what) : '') + '.'
        : '<b>Configuración desbloqueada.</b> Puedes cambiarla; al terminar vuelve a bloquearla.';
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'gw-btn gw-btn--secondary gw-btn--sm';
      btn.textContent = locked ? 'Desbloquear' : 'Bloquear de nuevo';
      btn.addEventListener('click', () => { if (isLocked(scope)) unlock(scope); else relock(scope); });
      box.append(text, btn);
    };
    box._gwPaint = paint;
    listeners.push((s) => { if (s === scope) paint(); });
    paint();
  }

  window.GWConfigLock = { isLocked, unlock, relock, banner, state, onChange: (fn) => listeners.push(fn) };
})();
