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

  const icon = (name, cls) => `<svg class="gw-icon ${cls || ''}" aria-hidden="true"><use href="${esc(root.dataset.icons || '')}#i-${name}"/></svg>`;
  function verdict(kind, title, text) {          // kind: 'ok' | 'err'
    return `<div class="gw-verdict gw-verdict--${kind}" role="${kind === 'err' ? 'alert' : 'status'}">${icon(kind === 'ok' ? 'check-lg' : 'error', 'gw-verdict__icon')}<div class="gw-verdict__body"><p class="gw-verdict__title">${esc(title)}</p><p class="gw-verdict__text">${esc(text)}</p></div></div>`;
  }

  async function scan(text) {
    const out = $('almScanResult');
    const code = String(text || '').trim();
    if (!code) return;
    try {
      if (!tracking) { try { tracking = (await j('/api/almacen/meta')).tracking; } catch (e) { tracking = []; } }
      const d = await j('/api/almacen/scan?code=' + encodeURIComponent(code));
      if (d.kind === 'unit') {
        const u = d.unit;
        out.innerHTML = verdict('ok', u.title, `Código ${u.code} · ${u.serial ? 'Serial ' + u.serial + ' · ' : ''}${u.status_label}${u.event_name ? ' · ' + u.event_name : ''}`);
      } else {
        const p = d.product;
        out.innerHTML = verdict('ok', p.name, `Código ${d.code} · ${trackingLabel(p.tracking)}`);
      }
    } catch (e) {
      out.innerHTML = verdict('err', 'No encontrado', e.message);
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

  /* La barra de guardado única es de toda la pantalla (inventario.html); los bloques de Almacén se registran por clave: almacen-checklist (almacen-moves.js) y almacen-seriales (almacen-catalog.js). */
})();
