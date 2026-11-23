/* Adjuntar base de datos › Base de dependientes (0161, app/dependents.py). Sube el archivo UNA vez, pide la vista previa (no escribe nada), la muestra
   (static/js/roster-preview.js) y solo con «Sí, cargar» guarda. También muestra cuántos dependientes hay y permite borrar la base (escribiendo BORRAR). */
(function () {
  'use strict';
  const form = document.getElementById('depForm');
  if (!form) return;
  const $ = (id) => document.getElementById(id);
  const EVENT_ID = form.dataset.event;
  const base = `/api/events/${EVENT_ID}/dependents`;
  const esc = (v) => (window.escapeHtml ? window.escapeHtml(String(v == null ? '' : v)) : String(v == null ? '' : v));

  async function refresh() {
    const info = $('depInfo');
    if (!info) return;
    try {
      const r = await fetch(`${base}/summary`, { cache: 'no-store' });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'No se pudo consultar');
      info.textContent = d.rows ? `Hoy hay ${d.dependents} dependientes de ${d.holders} titulares (${d.rows} filas cargadas).` : 'Este evento todavía no tiene base de dependientes.';
      $('depWipe').hidden = !d.rows;
    } catch (e) { info.textContent = ''; }
  }

  async function post(url, fd) {
    const r = await fetch(url, { method: 'POST', body: fd });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'No se pudo procesar el archivo');
    return d;
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const file = $('depFileInput').files[0];
    if (!file) { showToast('Elige el archivo de dependientes', 'error'); return; }
    const btn = $('depSubmit');
    const mode = (form.querySelector('input[name="depMode"]:checked') || {}).value || 'replace';
    if (window.setButtonLoading) setButtonLoading(btn, true, 'Revisando el archivo...');
    $('depResult').innerHTML = '';
    try {
      const fd = new FormData();
      fd.append('roster_file', file);
      fd.append('mode', mode);
      await DirectUpload.replaceFiles(fd, { roster_file: ['roster_upload', 'bulk_roster'] }, { body: { event_id: String(EVENT_ID) } });
      const preview = await post(`${base}/preview`, fd);
      const ok = await RosterPreview.confirmDependents(preview);
      if (!ok) { showToast('No se cargó nada', 'info'); return; }
      if (window.setButtonLoading) setButtonLoading(btn, true, 'Cargando dependientes...');
      const out = await post(`${base}/load`, fd);
      showToast(out.message, 'success');
      $('depResult').innerHTML = `<div class="gw-alert gw-alert--ok"><div>${esc(out.message)}${out.inventory ? ` Inventario: ${out.inventory.created ? out.inventory.created + ' producto(s) nuevos creados desde la base.' : 'sin productos nuevos.'}` : ''}</div></div>`;
      form.reset();
      refresh();
    } catch (err) {
      showToast(err && err.message && err.message !== 'network' ? err.message : 'Error de red', 'error');
    } finally {
      if (window.setButtonLoading) setButtonLoading(btn, false);
    }
  });

  if ($('depWipe')) $('depWipe').addEventListener('click', async () => {
    const typed = await showPrompt('Se borrará la base de dependientes de este evento (lo ya entregado se conserva). No se puede deshacer. Para confirmar escribe BORRAR.', { title: 'Borrar la base de dependientes', confirmLabel: 'Borrar', placeholder: 'BORRAR' });
    if (typed == null) return;
    if (String(typed).trim().toUpperCase() !== 'BORRAR') { showToast('No se borró nada: hay que escribir BORRAR.', 'error'); return; }
    try {
      const r = await fetch(base, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: 'BORRAR' }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || 'No se pudo borrar');
      showToast(d.message, 'success');
    } catch (err) { showToast(err.message, 'error'); }
    refresh();
  });

  refresh();
})();
