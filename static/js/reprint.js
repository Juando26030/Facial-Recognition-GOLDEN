/* Reimpresión con permisos, lado del digitador (Fase 1B, docs/1B_reimpresion_permisos.md).
   Con la reimpresión DESHABILITADA en el evento, reimprimir a quien ya se imprimió muestra «No se puede reimprimir» y, debajo, «¿Es una emergencia autorizada? Solicitar permiso».
   La solicitud llega al coordinador del evento (pantalla y, de respaldo, correo). Aquí se muestra cómo va: esperando / aprobada («Reimprimir ahora») / negada / vencida, con el sondeo de siempre
   (GW.poll: se pausa si la pantalla está sin uso; sin WebSockets). Requiere conexión.
   La puerta real es la del SERVIDOR (print-jobs y reprint-requests/use): esto solo guía. Se prueba con Node (tests/js/reprint_check.js).
   API:  GWReprint.check(userId, countData?, {explicit}) -> Promise<{ ok, approved }>   ok=false: no seguir (ya se mostró el cuadro);  approved=true: el permiso ya cubre la confirmación de «¿imprimir de nuevo?»
         GWReprint.use(userId, locked?)                   -> Promise<boolean>            gasta el permiso en el servidor ANTES de imprimir en el propio equipo (la impresión compartida lo gasta el servidor) */
(function (root) {
  'use strict';

  const OFFLINE = 'Para pedir permiso necesitas conexión.';
  const POLL_MS = 4000;
  const USED_MEMO_MS = 15000;             // un permiso gastado cubre las dos llamadas de UNA misma impresión (despachador + ventana), no una segunda reimpresión
  const used = new Map();

  const doc = () => root.document;
  const eid = () => root.EVENT_ID;
  const online = () => !(root.navigator && root.navigator.onLine === false);
  const toast = (m, t) => { if (typeof root.showToast === 'function') root.showToast(m, t || 'info'); };
  const api = (path) => `/api/events/${eid()}/reprint-requests${path || ''}`;

  async function json(res) { try { return await res.json(); } catch (e) { return {}; } }

  function icon(name) {
    const NS = 'http://www.w3.org/2000/svg';
    const svg = doc().createElementNS(NS, 'svg'); svg.setAttribute('class', 'gw-icon'); svg.setAttribute('aria-hidden', 'true');
    const use = doc().createElementNS(NS, 'use'); use.setAttribute('href', `/static/img/icons.svg#i-${name}`); svg.appendChild(use);
    return svg;
  }
  function el(tag, cls, text) { const e = doc().createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
  function alertBox(kind, title, body) {         // .gw-alert (guía visual): info | ok | warn | err
    const box = el('div', 'gw-alert' + (kind === 'info' ? '' : ` gw-alert--${kind}`)); box.setAttribute('role', kind === 'err' ? 'alert' : 'status');
    box.appendChild(icon(kind === 'ok' ? 'check' : kind === 'err' ? 'error' : kind === 'warn' ? 'alert' : 'info'));
    const wrap = el('div'); wrap.appendChild(el('div', 'gw-alert__title', title)); if (body) wrap.appendChild(el('div', 'gw-alert__body', body)); box.appendChild(wrap);
    return box;
  }
  function hhmm(iso) { try { return new Date(iso).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' }); } catch (e) { return ''; } }

  /* El cuadro. Devuelve una promesa: 'approved' (pulsó «Reimprimir ahora») o 'closed'. */
  function openDialog(userId, initial, opts) {
    return new Promise((resolve) => {
      let state = initial || { status: 'none' };
      let timer = null;
      let busy = false;
      const back = el('div', 'gw-modal-backdrop'); back.setAttribute('data-open', 'true');
      const modal = el('div', 'gw-modal'); modal.setAttribute('role', 'dialog'); modal.setAttribute('aria-modal', 'true'); modal.setAttribute('aria-labelledby', 'gwReprintTitle');
      const head = el('div', 'gw-modal__head'); const title = el('h2', 'gw-modal__title', 'No se puede reimprimir'); title.id = 'gwReprintTitle';
      const x = el('button', 'gw-btn gw-btn--ghost gw-btn--sm'); x.type = 'button'; x.setAttribute('aria-label', 'Cerrar'); x.setAttribute('data-act', 'close'); x.appendChild(icon('close'));
      head.appendChild(title); head.appendChild(x);
      const body = el('div', 'gw-modal__body gw-stack'); const foot = el('div', 'gw-modal__foot');
      modal.appendChild(head); modal.appendChild(body); modal.appendChild(foot); back.appendChild(modal);

      function button(label, act, primary) { const b = el('button', 'gw-btn ' + (primary ? 'gw-btn--primary' : 'gw-btn--secondary'), label); b.type = 'button'; b.setAttribute('data-act', act); return b; }
      function stop() { if (timer) { root.clearInterval(timer); timer = null; } }
      function finish(result) { stop(); if (back.parentNode) back.parentNode.removeChild(back); resolve(result); }

      function paint() {
        body.replaceChildren(); foot.replaceChildren();
        const s = state.status;
        if (s === 'pending') {
          body.appendChild(alertBox('info', 'Esperando respuesta del coordinador', 'Ya le avisamos en su pantalla y, si no responde pronto, por correo. Puedes cerrar este cuadro: te avisamos aquí cuando responda.'));
          foot.appendChild(button('Cerrar', 'close', false));
        } else if (s === 'approved') {
          body.appendChild(alertBox('ok', 'Permiso aprobado', `Vale para una sola reimpresión${state.expires_at ? ' y vence a las ' + hhmm(state.expires_at) : ''}.`));
          foot.appendChild(button('Cerrar', 'close', false)); foot.appendChild(button('Reimprimir ahora', 'go', true));
        } else if (s === 'denied') {
          body.appendChild(alertBox('err', 'El coordinador negó el permiso', 'No se reimprime esta escarapela.'));
          foot.appendChild(button('Cerrar', 'close', false));
        } else if (s === 'expired' || s === 'used') {
          body.appendChild(alertBox('warn', s === 'used' ? 'El permiso ya se usó' : 'El permiso venció', 'Si sigue siendo una emergencia, puedes pedirlo de nuevo.'));
          foot.appendChild(button('Cerrar', 'close', false)); foot.appendChild(button('Solicitar permiso', 'ask', true));
        } else {
          body.appendChild(alertBox('warn', 'La reimpresión está deshabilitada en este evento', 'A esta persona ya se le imprimió su escarapela.'));
          const q = el('p'); q.appendChild(el('strong', null, '¿Es una emergencia autorizada?')); body.appendChild(q);
          if (opts && opts.offline) body.appendChild(alertBox('err', OFFLINE));
          foot.appendChild(button('Cancelar', 'close', false)); foot.appendChild(button('Solicitar permiso', 'ask', true));
        }
      }

      async function ask() {
        if (busy) return;
        if (!online()) { toast(OFFLINE, 'error'); if (opts) opts.offline = true; paint(); return; }
        busy = true;
        try {
          const res = await root.fetch(api(), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: userId }) });
          const d = await json(res);
          if (!res.ok) { toast(d.detail || 'No se pudo pedir el permiso.', 'error'); return; }
          state = d; paint(); startPolling();
        } catch (e) { toast(OFFLINE, 'error'); if (opts) opts.offline = true; paint(); }
        finally { busy = false; }
      }
      async function refresh() {
        try {
          const res = await root.fetch(`${api('/mine')}?user_id=${encodeURIComponent(userId)}`, { cache: 'no-store', headers: { 'X-Gw-Passive': '1' } });
          if (!res.ok) return;
          const d = await res.json(); const r = d.request;
          const next = r || { status: d.permit ? 'approved' : 'none' };
          if (next.status !== state.status) { state = next; paint(); }
          if (state.status !== 'pending') stop();
        } catch (e) { /* sin red: se reintenta en el siguiente sondeo */ }
      }
      function startPolling() {
        stop();
        if (state.status !== 'pending') return;
        timer = (root.GW && typeof root.GW.poll === 'function') ? root.GW.poll(refresh, POLL_MS) : root.setInterval(refresh, POLL_MS);
      }

      back.addEventListener('click', (e) => {
        const node = e.target && e.target.closest ? e.target.closest('[data-act]') : null;
        const name = node ? node.getAttribute('data-act') : '';
        if (name === 'close') finish('closed');
        else if (name === 'ask') ask();
        else if (name === 'go') finish('approved');
      });
      doc().body.appendChild(back); paint(); startPolling();
      const first = foot.querySelector('.gw-btn--primary') || foot.querySelector('button'); if (first && first.focus) first.focus();
    });
  }

  async function check(userId, countData, opts) {
    const pass = { ok: true, approved: false };
    let d = countData;
    if (!d && (opts && opts.explicit)) {
      try { const r = await root.fetch(`/api/users/${encodeURIComponent(userId)}/print-count?event_id=${eid()}`, { cache: 'no-store' }); d = r.ok ? await r.json() : null; } catch (e) { d = null; }
      if (!d) {                                                   // sin red o error: si el evento tiene la reimpresión deshabilitada y es una reimpresión explícita, no se puede saber si hay permiso
        if (!root.EVENT_REPRINT_DISABLED) return pass;
        const r = await openDialog(userId, { status: 'none' }, { offline: true });
        return { ok: r === 'approved', approved: r === 'approved' };
      }
    }
    if (!d || !d.reprint_locked || !(d.times_printed > 0)) return pass;      // habilitada, o no es una reimpresión: como siempre
    if (d.permit) return { ok: true, approved: true };
    const r = d.request && d.request.status === 'approved' ? 'approved' : await openDialog(userId, d.request || { status: 'none' }, {});
    return { ok: r === 'approved', approved: r === 'approved' };
  }

  async function use(userId, locked) {
    if (!locked && !root.EVENT_REPRINT_DISABLED) return true;       // habilitada: nada que gastar (el servidor lo vuelve a comprobar en la impresión compartida)
    const key = `${eid()}:${userId}`;
    if (used.has(key) && Date.now() - used.get(key) < USED_MEMO_MS) return true;
    try {
      const res = await root.fetch(api('/use'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: userId }) });
      if (res.ok) { used.set(key, Date.now()); return true; }
      const d = await json(res);
      toast(d.detail || 'No se puede reimprimir sin permiso.', 'error');
      return false;
    } catch (e) { toast(OFFLINE, 'error'); return false; }
  }

  root.GWReprint = { check, use, open: (userId) => openDialog(userId, { status: 'none' }, {}) };
  if (typeof module === 'object' && module.exports) module.exports = root.GWReprint;
})(typeof window !== 'undefined' ? window : globalThis);
