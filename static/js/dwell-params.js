/* Parámetros → Permanencia, premio por estadía y escaneo automático (Fase 10). Se guarda con el «Guardar cambios» general (GWParams, clave «dwell»: cuenta en «cambios pendientes»); «Calcular» y las descargas son acciones aparte.
   API: /api/events/<id>/areas-dwell/* (app/routers/areas_dwell.py). Delegación de eventos, texto escapado, mensajes con showToast / showConfirm. Funciones puras en GWDwell (se prueban con Node). */
(function (root) {
  'use strict';
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const toMinutes = (h, m) => { const a = parseInt(h, 10) || 0, b = parseInt(m, 10) || 0; const n = a * 60 + b; return n > 0 ? n : null; };
  const splitMinutes = (n) => (n ? { h: Math.floor(n / 60), m: n % 60 } : { h: '', m: '' });
  const fmtMinutes = (n) => { if (!n) return '—'; const h = Math.floor(n / 60), m = n % 60; return h ? `${h} h${m ? ' ' + String(m).padStart(2, '0') + ' min' : ''}` : `${m} min`; };
  root.GWDwell = { toMinutes, splitMinutes, fmtMinutes };

  const doc = root.document;
  const box = doc && doc.getElementById('dwellBox');
  if (!box) return;
  const eventId = box.getAttribute('data-event');
  const $ = (id) => doc.getElementById(id);
  const api = '/api/events/' + eventId + '/areas-dwell';
  let cfg = null;

  function fill(c) {
    cfg = c;
    $('dwellEnabled').checked = !!c.dwell_enabled;
    $('dwellPrize').checked = !!c.prize_enabled;
    const t = splitMinutes(c.reference_minutes);
    $('dwellRefH').value = t.h; $('dwellRefM').value = t.m;
    $('dwellPct').value = c.threshold_pct || 80;
    $('dwellEval').value = c.threshold_pct || 80;
    $('areasAutoscan').checked = !!c.areas_autoscan;
    $('inventoryAutoscan').checked = !!c.inventory_autoscan;
    $('dwellConfig').hidden = !c.dwell_enabled;
    $('dwellStats').hidden = !c.dwell_enabled;
    summary();
    $('dwellRefHint').textContent = c.event_minutes
      ? `Si lo dejas vacío se usa la duración del evento: ${fmtMinutes(c.event_minutes)} (según sus fechas y horas).`
      : 'El evento no tiene fecha y hora de fin completas: escribe aquí el tiempo de referencia.';
  }
  function summary() {
    const el = $('dwellSummary');
    if (!el) return;
    const on = $('dwellEnabled').checked, prize = $('dwellPrize').checked, pct = $('dwellPct').value || 80;
    el.textContent = !on ? 'Hoy no se mide la permanencia: nada depende del tiempo en las zonas.'
      : !prize ? 'Hoy el tiempo en zonas es solo informativo: se ve en reportes y estadísticas, pero certificados e inventario se dan a todos igual.'
      : `Hoy el ${pct} % de permanencia es un requisito: solo quien lo cumple puede recibir el certificado que habilites y los ítems de inventario marcados «Solo a quien cumple la estadía».`;
  }
  box.addEventListener('input', summary);
  box.addEventListener('change', summary);
  async function call(url, opts) {
    const r = await fetch(url, Object.assign({ credentials: 'same-origin' }, opts || {}));
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'No se pudo completar la acción');
    return d;
  }
  const qs = (pct, extra) => { const p = new URLSearchParams(Object.assign({ pct: String(pct) }, extra || {})); const a = $('dwellArea').value; if (a) p.set('area_id', a); return p.toString(); };

  fetch(api + '/config', { credentials: 'same-origin' }).then((r) => (r.ok ? r.json() : null)).then((d) => { if (d) fill(d); });

  box.addEventListener('change', (e) => { if (e.target.id === 'dwellEnabled') $('dwellConfig').hidden = !e.target.checked; });
  GWParams.register({ key: 'dwell', label: 'Permanencia y escaneo automático', order: 67, save: async () => {
    const body = { dwell_enabled: $('dwellEnabled').checked, prize_enabled: $('dwellEnabled').checked && $('dwellPrize').checked,
      reference_minutes: toMinutes($('dwellRefH').value, $('dwellRefM').value), threshold_pct: $('dwellPct').value || 80,
      areas_autoscan: $('areasAutoscan').checked, inventory_autoscan: $('inventoryAutoscan').checked };
    fill(await call(api + '/config', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }));          // call() lanza Error(mensaje) si falla: el guardado general lo reporta
  } });

  box.addEventListener('click', async (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    if (btn.id === 'dwellCalc') {
      calc(btn);
    } else if (btn.id === 'dwellCerts') {
      const pct = parseInt($('dwellEval').value, 10) || (cfg && cfg.threshold_pct) || 80;
      if (!(await showConfirm(`Se marcará «Certificado: Sí» a todas las personas que lleguen al ${pct} % de la referencia. ¿Continuar?`, { confirmLabel: 'Habilitar certificados' }))) return;
      try {
        const d = await call(api + '/apply-certificates', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pct }) });
        showToast(`Certificado habilitado a ${d.granted} persona${d.granted === 1 ? '' : 's'} (${d.qualifying} cumplen el ${d.threshold_pct} %).` + (d.certificates_enabled ? '' : ' Recuerda activar los certificados del evento.'), 'success');
      } catch (err) { showToast(err.message, 'error'); }
    }
  });

  async function calc(btn) {
    const pct = parseInt($('dwellEval').value, 10) || (cfg && cfg.threshold_pct) || 80;
    const out = $('dwellResult');
    out.innerHTML = '<p class="gw-hint" role="status">Calculando…</p>';
    try {
      const d = await (root.GW && root.GW.busy ? root.GW.busy(btn, () => call(api + '?' + qs(pct, { only: 'cumple', limit: '15' }))) : call(api + '?' + qs(pct, { only: 'cumple', limit: '15' })));
      const s = d.summary;
      const sel = $('dwellArea');
      if (sel.options.length <= 1) d.areas.forEach((a) => { const o = doc.createElement('option'); o.value = a.id; o.textContent = a.name; sel.appendChild(o); });
      if (!s.reference_minutes) { out.innerHTML = '<p class="gw-hint" role="alert">Falta el tiempo de referencia: guárdalo arriba para calcular porcentajes.</p>'; return; }
      const steps = Object.keys(s.steps).map((k) => `${esc(k)} % o más: <strong>${s.steps[k]}</strong>`).join(' · ');
      out.innerHTML = `<p><strong>${s.qualifying}</strong> de ${s.people} personas con movimientos llegan al <strong>${pct} %</strong> de ${esc(fmtMinutes(s.reference_minutes))}.` +
        (s.with_open_entry ? ` <span class="gw-hint">${s.with_open_entry} quedó con una entrada sin salida (se cuenta hasta el fin del evento o hasta ahora).</span>` : '') + `</p><p class="gw-hint">${steps}</p>` +
        (d.rows.length ? `<div class="gw-table-wrap"><table class="gw-table"><caption class="gw-sr-only">Primeras personas que cumplen</caption><thead><tr><th scope="col">Cédula</th><th scope="col">Persona</th><th scope="col">Tiempo</th><th scope="col">%</th></tr></thead><tbody>${d.rows.map((r) => `<tr><td>${esc(r.id)}</td><td>${esc(r.name)}</td><td>${esc(r.label)}</td><td>${r.percent == null ? '' : esc(r.percent)}</td></tr>`).join('')}</tbody></table></div>${d.truncated ? '<p class="gw-hint">Se muestran las primeras 15; la lista completa está en la descarga.</p>' : ''}` : '');
      $('dwellActions').hidden = false;
      $('dwellXlsx').href = api + '/export?' + qs(pct, { fmt: 'xlsx', only: 'cumple' });
      $('dwellCsv').href = api + '/export?' + qs(pct, { fmt: 'csv', only: 'cumple' });
      $('dwellXlsxAll').href = api + '/export?' + qs(pct, { fmt: 'xlsx', only: 'todos' });
    } catch (err) { out.innerHTML = `<p class="gw-hint" role="alert">${esc(err.message)}</p>`; }
  }
})(typeof window !== 'undefined' ? window : globalThis);
