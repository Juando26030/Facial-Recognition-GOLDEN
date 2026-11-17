/* Almacén (Inventario → pestaña «Almacén»): modo escáner. El lector USB escribe el código y pulsa Enter; se muestra qué es (equipo con serial o elemento por modelo/cantidad).
   Las salidas y entradas por evento están en almacen-moves.js; crear tipos, objetos, fotos y etiquetas está en almacen-catalog.js (pestaña «Administrar catálogo»).
   API: /api/almacen/scan. Todo se escapa; sin manejadores en línea. */
(function () {
  'use strict';
  const root = document.getElementById('invPanelAlm');
  if (!root) return;
  const tab = document.getElementById('invTabAlm');
  const $ = (id) => document.getElementById(id);
  const esc = (t) => window.escapeHtml(String(t == null ? '' : t));
  let tracking = null;          // etiquetas de «cómo se controla», de /api/almacen/meta

  async function j(url) { const r = await fetch(url); const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Error'); return d; }
  const trackingLabel = (k) => ((tracking || []).find((t) => t.key === k) || {}).label || k;

  async function scan(text) {
    const out = $('almScanResult');
    const code = String(text || '').trim();
    if (!code) return;
    try {
      if (!tracking) { try { tracking = (await j('/api/almacen/meta')).tracking; } catch (e) { tracking = []; } }
      const d = await j('/api/almacen/scan?code=' + encodeURIComponent(code));
      if (d.kind === 'unit') {
        const u = d.unit;
        out.innerHTML = `<div class="gw-state" role="status"><p class="gw-state__title"><span class="gw-badge gw-badge--ok">Encontrado</span> ${esc(u.title)}</p>
          <p class="gw-hint">Código ${esc(u.code)} · ${u.serial ? 'Serial ' + esc(u.serial) + ' · ' : ''}${esc(u.status_label)}${u.event_name ? ' · ' + esc(u.event_name) : ''}</p></div>`;
      } else {
        const p = d.product;
        out.innerHTML = `<div class="gw-state" role="status"><p class="gw-state__title"><span class="gw-badge gw-badge--ok">Encontrado</span> ${esc(p.name)}</p>
          <p class="gw-hint">Código ${esc(d.code)} · ${esc(trackingLabel(p.tracking))}</p></div>`;
      }
    } catch (e) {
      out.innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title"><span class="gw-badge gw-badge--err">No encontrado</span> ${esc(e.message)}</p></div>`;
    }
  }

  $('almScan').addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const v = e.target.value;
    e.target.value = '';
    scan(v);
  });
  if (tab) tab.addEventListener('gw:tabshow', () => { const s = $('almScan'); if (s) s.focus(); });
})();
