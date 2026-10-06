/* Pantalla de la bandeja de salida (B8 R1, static/js/outbox.js): botón «📤 Bandeja (N)», franja de AVISO permanente cuando hay personas sin enviar (amarilla desde el día 3, roja desde el 6 o al caducar),
   lista con el resultado de cada alta (enviada / revisar / ya estaba registrada / error / caducada) y acciones: Reintentar (error), Enviar de todos modos (caducada), Descartar (SIEMPRE con confirmación).
   Envía sola al volver la red (cambio de contingencia a normal) y cada 20 s mientras haya pendientes y haya conexión. Todo texto de personas entra con textContent (nunca como HTML). */
(function (root) {
  const SYNC_EVERY_MS = 20000;

  function mount(opts) {
    const outbox = opts.outbox, doc = opts.document || root.document, toast = opts.toast || root.showToast || (() => {}), confirm = opts.confirm || root.showConfirm;
    const online = opts.online || (() => { const gc = root.GoldenContingency && root.GoldenContingency.instance; return !(gc && gc.active && gc.active()); });
    const ui = { syncing: false, timer: null };
    const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const el = (tag, css, text) => { const e = doc.createElement(tag); if (css) e.style.cssText = css; if (text != null) e.textContent = text; return e; };

    const banner = el('div', 'display:none; position:fixed; left:0; right:0; bottom:0; z-index:9998; padding:8px 14px; font-weight:700; font-size:0.9rem; text-align:center; cursor:pointer;');
    banner.setAttribute('role', 'status'); banner.setAttribute('aria-live', 'polite'); banner.setAttribute('data-golden-banner', 'outbox');
    const btn = el('button', 'display:none; position:fixed; right:14px; bottom:48px; z-index:9999; padding:10px 14px; border-radius:24px; border:0; background:#1a237e; color:#fff; font-weight:700; box-shadow:0 4px 14px rgba(0,0,0,.3);');
    btn.type = 'button';
    const modal = el('div', 'display:none; position:fixed; inset:0; z-index:10000; background:rgba(0,0,0,.45); overflow:auto;');
    const panel = el('div', 'background:#fff; max-width:760px; margin:5vh auto; border-radius:16px; padding:18px 20px;');
    modal.appendChild(panel);
    doc.body.appendChild(banner); doc.body.appendChild(btn); doc.body.appendChild(modal);

    const COLORS = { ok: ['#fff', '#fff'], warn: ['#fff3cd', '#664d03'], urgent: ['#f8d7da', '#842029'], expired: ['#f8d7da', '#842029'] };
    async function refresh() {
      const st = await outbox.stats();
      const attention = st.unsent + st.expired;
      btn.style.display = (st.total || st.pruned) ? 'block' : 'none';
      btn.textContent = attention ? `📤 Bandeja (${attention})` : '📤 Bandeja';
      banner.style.display = st.banner ? 'block' : 'none';
      if (st.banner) { const c = COLORS[st.level] || COLORS.warn; banner.style.background = st.level === 'ok' ? '#e3f2fd' : c[0]; banner.style.color = st.level === 'ok' ? '#0d47a1' : c[1]; banner.textContent = '📤 ' + st.banner + ' — toca para abrir la bandeja'; }
      if (modal.style.display !== 'none') await renderPanel(st);
      return st;
    }

    async function renderPanel(st) {
      const items = await outbox.list();
      panel.replaceChildren();
      const head = el('div', 'display:flex; justify-content:space-between; align-items:center; gap:8px;');
      head.appendChild(el('h3', 'margin:0;', 'Bandeja de salida'));
      const close = el('button', 'border:0; background:#eee; border-radius:8px; padding:6px 12px;', 'Cerrar'); close.type = 'button'; close.addEventListener('click', () => { modal.style.display = 'none'; });
      head.appendChild(close); panel.appendChild(head);
      panel.appendChild(el('p', 'font-size:0.85rem; color:#555;', 'Altas hechas sin conexión en ESTE dispositivo. Se guardan cifradas, se envían solas al volver la red y se borran del dispositivo al confirmarse. Lo que no se envía en 7 días caduca y NO se borra solo: tú decides.'));
      if (st.banner) panel.appendChild(el('p', 'font-weight:700; color:#842029;', st.banner));
      const send = el('button', 'padding:8px 14px; border-radius:10px; border:0; background:#1a237e; color:#fff; font-weight:700; margin-bottom:10px;', 'Enviar ahora'); send.type = 'button';
      send.addEventListener('click', () => ui.sync(true)); panel.appendChild(send);
      if (!items.length) { panel.appendChild(el('p', 'color:#777;', 'No hay nada en la bandeja.')); return; }
      const table = el('table', 'width:100%; border-collapse:collapse; font-size:0.88rem;');
      const th = (t) => el('th', 'text-align:left; border-bottom:2px solid #ddd; padding:4px 6px;', t);
      const hr = el('tr'); ['Persona', 'Estado', 'Detalle', 'Edad / caduca', ''].forEach((t) => hr.appendChild(th(t))); table.appendChild(hr);
      for (const it of items) {
        const tr = el('tr'); const td = (t, css) => { const c = el('td', 'border-bottom:1px solid #eee; padding:6px; vertical-align:top;' + (css || ''), t); tr.appendChild(c); return c; };
        td(it.label || '(sin nombre)', 'font-weight:600;');
        td(root.GoldenOutbox.statusLabel(it.status), { ok: 'color:#1b5e20;', error: 'color:#842029;', caducada: 'color:#842029; font-weight:700;', revision: 'color:#664d03;', duplicado: 'color:#664d03;' }[it.status] || '');
        td(it.status === 'revision' ? `Ya existía como «${it.detail}»: sus datos NO se cambiaron; se registró para este evento. Revisa si es la misma persona.` : (it.status === 'duplicado' ? `Ya estaba registrada (${it.detail}).` : (it.detail || '')), 'font-size:0.8rem;');
        td(it.status === 'ok' ? '' : `hace ${Math.floor(it.days_old)} d · ${it.days_left > 0 ? 'caduca en ' + Math.max(0, Math.ceil(it.days_left)) + ' d' : 'caducada'}`, it.level === 'urgent' || it.level === 'expired' ? 'color:#842029; font-weight:700;' : (it.level === 'warn' ? 'color:#664d03; font-weight:700;' : ''));
        const act = td('', 'white-space:nowrap;');
        const action = (label, fn) => { const b = el('button', 'margin:2px; padding:4px 8px; border-radius:8px; border:1px solid #ccc; background:#fff;', label); b.type = 'button'; b.addEventListener('click', fn); act.appendChild(b); };
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
