/* Pantalla de la bandeja de salida (B8 R1, static/js/outbox.js): botón «Bandeja (N)», franja de AVISO permanente cuando hay personas sin enviar (amarilla desde el día 3, roja desde el 6 o al caducar),
   lista con el resultado de cada alta (enviada / revisar / ya estaba registrada / error / caducada) y acciones: Reintentar (error), Enviar de todos modos (caducada), Descartar (SIEMPRE con confirmación).
   Envía sola al volver la red (cambio de contingencia a normal) y cada 20 s mientras haya pendientes y haya conexión. Todo texto de personas entra con textContent (nunca como HTML). */
(function (root) {
  const SYNC_EVERY_MS = 20000;

  function mount(opts) {
    const outbox = opts.outbox, doc = opts.document || root.document, toast = opts.toast || root.showToast || (() => {}), confirm = opts.confirm || root.showConfirm;
    const online = opts.online || (() => { const gc = root.GoldenContingency && root.GoldenContingency.instance; return !(gc && gc.active && gc.active()); });
    const ui = { syncing: false, timer: null };
    const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const el = (tag, cls, text) => { const e = doc.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };      // Plan 8: solo clases (registro.css), nada de colores en el código

    const banner = el('div', 'gw-alert gw-alert--warn gw-outbox__banner'); banner.style.display = 'none';
    banner.setAttribute('role', 'status'); banner.setAttribute('tabindex', '0'); banner.setAttribute('aria-live', 'polite'); banner.setAttribute('data-golden-banner', 'outbox');
    const btn = el('button', 'gw-btn gw-btn--secondary gw-outbox__btn'); btn.style.display = 'none';
    btn.type = 'button';
    const modal = el('div', 'gw-outbox__modal'); modal.style.display = 'none'; modal.setAttribute('role', 'dialog'); modal.setAttribute('aria-modal', 'true'); modal.setAttribute('aria-label', 'Bandeja de salida');
    const panel = el('div', 'gw-card gw-outbox__panel');
    modal.appendChild(panel);
    doc.body.appendChild(banner); doc.body.appendChild(btn); doc.body.appendChild(modal);

    const LEVEL_CLASS = { ok: 'gw-alert gw-alert--info gw-outbox__banner', warn: 'gw-alert gw-alert--warn gw-outbox__banner', urgent: 'gw-alert gw-alert--err gw-outbox__banner', expired: 'gw-alert gw-alert--err gw-outbox__banner' };
    async function refresh() {
      const st = await outbox.stats();
      const attention = st.unsent + st.expired;
      btn.style.display = (st.total || st.pruned) ? 'inline-flex' : 'none';
      btn.textContent = attention ? `Bandeja (${attention})` : 'Bandeja';
      banner.style.display = st.banner ? 'flex' : 'none';
      if (st.banner) { banner.className = LEVEL_CLASS[st.level] || LEVEL_CLASS.warn; banner.textContent = st.banner + ' — toca para abrir la bandeja'; }
      if (modal.style.display !== 'none') await renderPanel(st);
      return st;
    }

    async function renderPanel(st) {
      const items = await outbox.list();
      panel.replaceChildren();
      const head = el('div', 'gw-row gw-row--between');
      head.appendChild(el('h3', 'gw-outbox__title', 'Bandeja de salida'));
      const close = el('button', 'gw-btn gw-btn--secondary gw-btn--sm', 'Cerrar'); close.type = 'button'; close.addEventListener('click', () => { modal.style.display = 'none'; });
      head.appendChild(close); panel.appendChild(head);
      panel.appendChild(el('p', 'gw-hint', 'Altas hechas sin conexión en ESTE dispositivo. Se guardan cifradas, se envían solas al volver la red y se borran del dispositivo al confirmarse. Lo que no se envía en 7 días caduca y NO se borra solo: tú decides.'));
      if (st.banner) panel.appendChild(el('p', 'gw-alert gw-alert--err', st.banner));
      const send = el('button', 'gw-btn gw-btn--secondary', 'Enviar ahora'); send.type = 'button';
      send.addEventListener('click', () => ui.sync(true)); panel.appendChild(send);
      if (!items.length) { panel.appendChild(el('p', 'gw-muted', 'No hay nada en la bandeja.')); return; }
      const table = el('table', 'gw-table gw-table-cards gw-outbox__table'); const COLS = ['Persona', 'Estado', 'Detalle', 'Edad / caduca', ''];
      const th = (t) => el('th', '', t);
      const hr = el('tr'); ['Persona', 'Estado', 'Detalle', 'Edad / caduca', ''].forEach((t) => hr.appendChild(th(t))); table.appendChild(hr);
      for (const it of items) {
        const tr = el('tr'); const td = (t, css) => { const c = el('td', css || '', t); if (COLS[tr.children.length]) c.setAttribute('data-label', COLS[tr.children.length]); tr.appendChild(c); return c; };
        td(it.label || '(sin nombre)', 'gw-outbox__name');
        td(root.GoldenOutbox.statusLabel(it.status), { ok: 'gw-outbox__ok', error: 'gw-outbox__bad', caducada: 'gw-outbox__bad', revision: 'gw-outbox__warn', duplicado: 'gw-outbox__warn' }[it.status] || '');
        td(it.status === 'revision' ? `Ya existía como «${it.detail}»: sus datos NO se cambiaron; se registró para este evento. Revisa si es la misma persona.` : (it.status === 'duplicado' ? `Ya estaba registrada (${it.detail}).` : (it.detail || '')), '');
        td(it.status === 'ok' ? '' : `hace ${Math.floor(it.days_old)} d · ${it.days_left > 0 ? 'caduca en ' + Math.max(0, Math.ceil(it.days_left)) + ' d' : 'caducada'}`, it.level === 'urgent' || it.level === 'expired' ? 'gw-outbox__bad' : (it.level === 'warn' ? 'gw-outbox__warn' : ''));
        const act = td('', 'gw-rowact');
        const action = (label, fn) => { const b = el('button', 'gw-btn gw-btn--secondary gw-btn--sm', label); b.type = 'button'; b.addEventListener('click', fn); act.appendChild(b); };
        if (it.status === 'error') action('Reintentar', async () => { await outbox.retry(it.op_id); ui.sync(true); });
        if (it.status === 'caducada') action('Enviar de todos modos', async () => { await outbox.sync({ force: true }); await refresh(); });
        if (it.status !== 'pendiente') action(it.status === 'ok' ? 'Quitar' : 'Descartar', async () => {
          const go = it.status === 'ok' ? true : (confirm ? await confirm(`¿Descartar a <strong>${esc(it.label)}</strong>? Se <b>borra de este dispositivo</b> y no se enviará. Esta acción no se puede deshacer.`) : true);
          if (go) { await outbox.discard(it.op_id); await refresh(); }
        });
        table.appendChild(tr);
      }
      panel.appendChild(table);
    }

    ui.open = async () => { modal.style.display = 'block'; await refresh(); await outbox.dismissPruned(); };      // abrir la bandeja = ver el aviso de lo eliminado a los 7 días
    btn.addEventListener('click', ui.open); banner.addEventListener('click', ui.open);
    modal.addEventListener('click', (e) => { if (e.target === modal) modal.style.display = 'none'; });

    ui.sync = async (manual) => {
      if (ui.syncing) return null;
      ui.syncing = true;
      try {
        const s = await outbox.sync();
        if (s.ok) { toast(`${s.ok} persona(s) nueva(s) enviada(s) al servidor`, 'success'); if (root.directorySearch) root.directorySearch.reload(); }
        if (s.warnings && s.warnings.length) toast(`Enviado con avisos: ${s.warnings.slice(0, 2).join(' · ')}${s.warnings.length > 2 ? ` (+${s.warnings.length - 2})` : ''}`, 'error');
        if (s.revision) toast(`${s.revision} alta(s) requieren revisión: la cédula ya existía (abre la bandeja)`, 'error');
        if (s.error) toast(`${s.error} alta(s) con error (abre la bandeja)`, 'error');
        if (manual && s.stopped) toast(s.stopped === 'sesion' ? 'Tu sesión venció: inicia sesión para enviar la bandeja' : 'Sin conexión con el servidor: se enviará solo al volver la red', 'error');
        return s;
      } finally { ui.syncing = false; await refresh(); }
    };
    const tick = async () => { if (online() && (await outbox.countUnsent())) ui.sync(false); };
    ui.timer = root.setInterval ? root.setInterval(tick, SYNC_EVERY_MS) : null;
    outbox.onChange(() => { refresh(); });
    ui.refresh = refresh; ui.tick = tick;
    refresh();
    return ui;
  }
  const api = { mount, SYNC_EVERY_MS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.GoldenOutboxUI = api;
})(typeof window !== 'undefined' ? window : globalThis);
