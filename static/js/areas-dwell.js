/* Control de áreas → estadística de permanencia (Fase 10). Resumen por porcentaje, primeras personas que cumplen, descargas y, con el premio activo, habilitar certificados.
   API: /api/events/<id>/areas-dwell/* (app/routers/areas_dwell.py). Delegación de eventos, texto escapado, showToast / showConfirm / GW.busy. */
(function () {
  'use strict';
  const panel = document.getElementById('dwellPanel');
  if (!panel) return;
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const api = '/api/events/' + panel.getAttribute('data-event') + '/areas-dwell';
  const busy = (btn, fn) => (window.GW && window.GW.busy ? window.GW.busy(btn, fn) : fn());
  const fmt = (n) => { if (!n) return '—'; const h = Math.floor(n / 60), m = n % 60; return h ? `${h} h${m ? ' ' + String(m).padStart(2, '0') + ' min' : ''}` : `${m} min`; };
  async function call(url, opts) {
    const r = await fetch(url, opts);
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'No se pudo completar la acción');
    return d;
  }
  let pct = 0;
  const qs = (extra) => { const p = new URLSearchParams(Object.assign({}, pct ? { pct: String(pct) } : {}, extra || {})); const a = $('adwArea').value; if (a) p.set('area_id', a); return p.toString(); };

  async function calc(btn) {
    pct = parseInt($('adwPct').value, 10) || 0;
    const out = $('adwResult');
    out.innerHTML = '<p class="gw-hint" role="status">Calculando…</p>';
    try {
      const d = await busy(btn, () => call(api + '?' + qs({ only: 'cumple', limit: '20' })));
      const s = d.summary, sel = $('adwArea');
      if (sel.options.length <= 1) d.areas.forEach((a) => { const o = document.createElement('option'); o.value = a.id; o.textContent = a.name; sel.appendChild(o); });
      if (!s.reference_minutes) { out.innerHTML = '<p class="gw-hint" role="alert">Falta el tiempo de referencia: defínelo en Parámetros del evento.</p>'; return; }
      pct = s.threshold_pct;
      const steps = Object.keys(s.steps).map((k) => `${esc(k)} % o más: <strong>${s.steps[k]}</strong>`).join(' · ');
      out.innerHTML = `<p><strong>${s.qualifying}</strong> de ${s.people} personas con movimientos llegan al <strong>${esc(s.threshold_pct)} %</strong> de ${esc(fmt(s.reference_minutes))}.` +
        (s.with_open_entry ? ` <span class="gw-hint">${s.with_open_entry} quedó sin salida (se cuenta hasta el fin del evento o hasta ahora).</span>` : '') + `</p><p class="gw-hint">${steps}</p>` +
        (d.rows.length ? `<div class="gw-table-wrap"><table class="gw-table"><caption class="gw-sr-only">Personas que cumplen</caption><thead><tr><th scope="col">Cédula</th><th scope="col">Persona</th><th scope="col">Tiempo</th><th scope="col">%</th></tr></thead><tbody>${d.rows.map((r) => `<tr><td>${esc(r.id)}</td><td>${esc(r.name)}${r.open ? ' <span class="gw-badge">Quedó sin salida</span>' : ''}</td><td>${esc(r.label)}</td><td>${r.percent == null ? '' : esc(r.percent)}</td></tr>`).join('')}</tbody></table></div>${d.truncated ? '<p class="gw-hint">Se muestran las primeras 20; la lista completa está en la descarga.</p>' : ''}` : '');
      $('adwActions').hidden = false;
      $('adwXlsx').href = api + '/export?' + qs({ fmt: 'xlsx', only: 'cumple' });
      $('adwCsv').href = api + '/export?' + qs({ fmt: 'csv', only: 'cumple' });
      $('adwAll').href = api + '/export?' + qs({ fmt: 'xlsx', only: 'todos' });
    } catch (err) { out.innerHTML = `<p class="gw-hint" role="alert">${esc(err.message)}</p>`; }
  }

  panel.addEventListener('click', async (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    if (btn.id === 'adwCalc') { calc(btn); return; }
    if (btn.id === 'adwCerts') {
      if (!(await showConfirm(`Se marcará «Certificado: Sí» a todas las personas que lleguen al ${pct || 'porcentaje mínimo del evento'} %. ¿Continuar?`, { confirmLabel: 'Habilitar certificados' }))) return;
      try {
        const d = await busy(btn, () => call(api + '/apply-certificates', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(pct ? { pct } : {}) }));
        showToast(`Certificado habilitado a ${d.granted} persona${d.granted === 1 ? '' : 's'} (${d.qualifying} cumplen el ${d.threshold_pct} %).`, 'success');
      } catch (err) { showToast(err.message, 'error'); }
    }
  });
})();
