/* Expositores del evento (Fase 8, personal coordinador+): alta, enlaces, pausa, cambio de enlace y borrado. */
(function () {
  'use strict';
  const EV = window.EVENT_ID || document.querySelector('[data-event-id]').dataset.eventId, api = '/api/events/' + EV + '/exhibitors';
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const toast = (m, t) => { if (window.showToast) showToast(m, t); };
  let rows = [];

  async function call(url, method, body) {
    const r = await fetch(url, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || 'No se pudo completar la acción');
    return d;
  }

  function paint() {
    $('exBody').innerHTML = rows.map((x) => '<tr><td><strong>' + esc(x.name) + '</strong><br><small>' + esc(x.contact_name) + '</small></td><td>' + x.leads + '</td>' +
      '<td>' + (x.active ? 'Activo' : 'Pausado') + '</td><td><div class="gw-row-actions">' +
      '<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-act="copy" data-id="' + x.id + '">Copiar enlace privado</button> ' +
      '<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-act="qr" data-id="' + x.id + '" title="Generar QR del enlace privado">Generar QR</button> ' +
      '<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-act="toggle" data-id="' + x.id + '">' + (x.active ? 'Pausar' : 'Activar') + '</button> ' +
      '<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-act="rotate" data-id="' + x.id + '">Cambiar enlaces</button> ' +
      '<button type="button" class="gw-btn gw-btn--danger gw-btn--sm" data-act="delete" data-id="' + x.id + '">Borrar</button></div></td></tr>').join('') ||
      '<tr><td colspan="4">Aún no hay expositores.</td></tr>';
  }

  async function load() {
    try { rows = await call(api, 'GET'); paint(); } catch (e) { toast(e.message, 'error'); }
  }

  $('exForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await call(api, 'POST', { name: $('exName').value, contact_name: $('exContact').value, title: $('exTitle').value, phone: $('exPhone').value, email: $('exEmail').value });
      e.target.reset(); toast('Expositor agregado', 'success'); load();
    } catch (err) { toast(err.message, 'error'); }
  });

  $('exBody').addEventListener('click', async (e) => {
    const b = e.target.closest('button[data-act]');
    if (!b) return;
    const x = rows.find((r) => String(r.id) === b.dataset.id);
    if (!x) return;
    try {
      if (b.dataset.act === 'copy') {
        const url = location.origin + x.private_path;
        try { await navigator.clipboard.writeText(url); toast('Enlace copiado. Entrégaselo SOLO a ese expositor.', 'success'); } catch (err) { if (window.showPrompt) showPrompt('Enlace privado (cópialo)', { defaultValue: url }); else toast(url, 'info'); }
      } else if (b.dataset.act === 'qr') {
        if (window.GWLinkQr) GWLinkQr.open(location.origin + x.private_path, { title: x.name });
      } else if (b.dataset.act === 'toggle') {
        await call(api + '/' + x.id, 'PATCH', { active: !x.active }); load();
      } else if (b.dataset.act === 'rotate') {
        if (!(await showConfirm('Los enlaces actuales de «' + x.name + '» dejarán de funcionar y deberás entregar los nuevos. ¿Continuar?'))) return;
        await call(api + '/' + x.id + '/rotate', 'POST'); toast('Enlaces cambiados', 'success'); load();
      } else if (b.dataset.act === 'delete') {
        if (!(await showConfirm('Se borra «' + x.name + '» y su lista de contactos. No se puede deshacer. ¿Continuar?'))) return;
        await call(api + '/' + x.id, 'DELETE'); load();
      }
    } catch (err) { toast(err.message, 'error'); }
  });
  load();
})();
