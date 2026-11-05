/* Reimpresión con permisos, lado del coordinador (Fase 1B, docs/1B_reimpresion_permisos.md).
   Cada pantalla del personal con menú lateral (coordinador o más) consulta, con el sondeo de siempre (GW.poll: se pausa cuando la pantalla está sin uso 60 s y retoma al volver),
   si hay solicitudes de reimpresión pendientes PARA ESTA PERSONA (y solo si tiene algún evento propio con la reimpresión deshabilitada; si no, deja de consultar. 30 s sin pendientes, 10 s con alguna) (las de los eventos que coordina; admin+ también las de eventos sin coordinador). Sin WebSockets.
   Cuando hay una, muestra una tarjeta con quién pide, a quién reimprimir, la hora y los botones Aprobar / Negar. Consultar marca la solicitud como «vista en pantalla»: así el respaldo por correo sabe que
   esta sesión está activa. El sondeo va con X-Gw-Passive: no renueva la sesión por inactividad. Se prueba con Node (tests/js/reprint_check.js). */
(function (root) {
  'use strict';
  if (root.GW_REPRINT_INBOX === false) return;

  const POLL_MS = 10000;                // cadencia del reloj (GW.poll); cuánto se consulta de verdad lo dice el servidor (`poll_ms`: 30 s sin pendientes, 10 s con alguna)
  const doc = () => root.document;
  const toast = (m, t) => { if (typeof root.showToast === 'function') root.showToast(m, t || 'info'); };
  let card = null;          // el cuadro abierto { back, id }
  let queue = [];
  let busy = false;
  let timer = null;
  let dead = false;
  let gapMs = 0;            // espera mínima entre consultas, según el servidor
  let last = 0;

  function el(tag, cls, text) { const e = doc().createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
  function icon(name) {
    const NS = 'http://www.w3.org/2000/svg';
    const svg = doc().createElementNS(NS, 'svg'); svg.setAttribute('class', 'gw-icon'); svg.setAttribute('aria-hidden', 'true');
    const use = doc().createElementNS(NS, 'use'); use.setAttribute('href', '/static/img/icons.svg#i-' + name); svg.appendChild(use);
    return svg;
  }
  function row(label, value) { const d = el('div'); d.appendChild(el('div', 'gw-alert__body', label)); d.appendChild(el('strong', null, value)); return d; }

  function close() { if (card && card.back.parentNode) card.back.parentNode.removeChild(card.back); card = null; }

  function show(r, more) {
    close();
    const back = el('div', 'gw-modal-backdrop'); back.setAttribute('data-open', 'true');
    const modal = el('div', 'gw-modal'); modal.setAttribute('role', 'alertdialog'); modal.setAttribute('aria-modal', 'true'); modal.setAttribute('aria-labelledby', 'gwReprintInboxTitle');
    const head = el('div', 'gw-modal__head'); const t = el('h2', 'gw-modal__title', 'Permiso para reimprimir'); t.id = 'gwReprintInboxTitle'; head.appendChild(icon('printer')); head.appendChild(t);
    const body = el('div', 'gw-modal__body gw-stack');
    body.appendChild(row('Evento', r.event_name)); body.appendChild(row('Lo pide', r.requested_by)); body.appendChild(row('Escarapela de', r.person)); body.appendChild(row('Hora del pedido', r.requested_hhmm));
    body.appendChild(el('p', null, 'Si apruebas, se podrá reimprimir una sola vez y el permiso vence pronto.'));
    if (more > 0) body.appendChild(el('p', 'gw-alert__body', `Hay ${more} solicitud${more === 1 ? '' : 'es'} más esperando.`));
    const foot = el('div', 'gw-modal__foot');
    const no = el('button', 'gw-btn gw-btn--secondary', 'Negar'); no.type = 'button'; no.setAttribute('data-decision', 'deny');
    const ok = el('button', 'gw-btn gw-btn--primary', 'Aprobar'); ok.type = 'button'; ok.setAttribute('data-decision', 'approve');
    foot.appendChild(no); foot.appendChild(ok);
    modal.appendChild(head); modal.appendChild(body); modal.appendChild(foot); back.appendChild(modal);
    back.addEventListener('click', (e) => {
      const b = e.target && e.target.closest ? e.target.closest('[data-decision]') : null;
      if (b) decide(r.id, b.getAttribute('data-decision'));
    });
    doc().body.appendChild(back);
    card = { back, id: r.id };
    ok.focus();
  }

  async function decide(id, choice) {
    if (busy) return;
    busy = true;
    try {
      const res = await root.fetch(`/api/reprint-requests/${id}/decision`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision: choice }) });
      if (res.ok) toast(choice === 'approve' ? 'Permiso aprobado: vale una sola reimpresión.' : 'Permiso negado.', choice === 'approve' ? 'success' : 'info');
      else { const d = await res.json().catch(() => ({})); toast(d.detail || 'No se pudo responder.', 'error'); }
    } catch (e) { toast('Sin conexión: no se pudo responder. Intenta de nuevo.', 'error'); return; }
    finally { busy = false; }
    queue = queue.filter((q) => q.id !== id); close();
    if (queue.length) show(queue[0], queue.length - 1); else poll();
  }

  async function poll() {
    if (dead || busy || (doc().visibilityState && doc().visibilityState !== 'visible')) return;          // pestaña oculta: no consulta (con GW.idle, GW.poll tampoco corre)
    if (Date.now() - last < gapMs - 500) return;
    last = Date.now();
    try {
      const res = await root.fetch('/api/reprint-requests/inbox', { cache: 'no-store', headers: { 'X-Gw-Passive': '1' } });
      if (res.status === 401 || res.status === 403) { dead = true; if (timer) root.clearInterval(timer); return; }       // sin sesión o sin permiso: se deja de preguntar
      if (!res.ok) return;
      const d = await res.json();
      if (d.watch === false) { dead = true; if (timer) root.clearInterval(timer); return; }            // no tiene eventos con la reimpresión deshabilitada: esta pantalla no vuelve a consultar
      gapMs = Number(d.poll_ms) || 30000;
      queue = d.requests || [];
      if (!queue.length) { close(); return; }
      if (!card || !queue.some((q) => q.id === card.id)) show(queue[0], queue.length - 1);
    } catch (e) { /* sin red: se reintenta en el siguiente sondeo */ }
  }

  root.GWReprintInbox = { poll, decide, _queue: () => queue };
  timer = (root.GW && typeof root.GW.poll === 'function') ? root.GW.poll(poll, POLL_MS) : root.setInterval(poll, POLL_MS);
  root.addEventListener('gw:session-expired', () => { dead = true; });
  root.addEventListener('gw:session-replaced', () => { dead = true; });
  if (typeof module === 'object' && module.exports) module.exports = root.GWReprintInbox;
})(typeof window !== 'undefined' ? window : globalThis);
