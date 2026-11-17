/* Etiquetas QR del almacén (Pieza 1): ventana de impresión PROPIA para el rollo de 62 mm de la Brother QL-800. Recibe los ids por la dirección (?u=unidades&p=productos), pide los datos a
   /api/almacen/labels y dibuja una etiqueta por página. El QR lleva SOLO el código (letras mayúsculas y números). No usa la impresión compartida de escarapelas ni cambia sus parámetros. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (t) => window.escapeHtml(String(t == null ? '' : t));
  const params = new URLSearchParams(location.search);
  const ids = (k) => (params.get(k) || '').split(',').map((x) => Number(x)).filter((n) => Number.isInteger(n) && n > 0);
  let labels = [];

  function qrSvg(code) {
    const qr = qrcode(0, 'M');
    qr.addData(code);
    qr.make();
    return qr.createSvgTag({ scalable: true });
  }

  /* La página del rollo mide SIEMPRE 62 mm de ancho; el alto lo elige quien imprime (29 mm = etiqueta troquelada). */
  function applySize() {
    const h = Number($('lblHeight').value) || 29;
    let st = $('lblPageStyle');
    if (!st) { st = document.createElement('style'); st.id = 'lblPageStyle'; document.head.appendChild(st); }
    st.textContent = `@page { size: 62mm ${h}mm; margin: 0; } .gw-almlbl__label { width: 62mm; height: ${h}mm; } .gw-almlbl__qr { width: ${h - 5}mm; height: ${h - 5}mm; }`;
  }

  function render() {
    $('lblSheet').innerHTML = labels.map((l) => `<section class="gw-almlbl__label"><div class="gw-almlbl__qr">${qrSvg(l.code)}</div>
      <div class="gw-almlbl__text"><p class="gw-almlbl__title">${esc(l.title)}</p><p class="gw-almlbl__code">${esc(l.code)}</p>${l.subtitle ? `<p class="gw-almlbl__sub">${esc(l.subtitle)}</p>` : ''}</div></section>`).join('');
  }

  async function init() {
    const body = { unit_ids: ids('u'), product_ids: ids('p') };
    try {
      const r = await fetch('/api/almacen/labels', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'No se pudieron preparar las etiquetas');
      labels = d.labels || [];
      applySize();
      render();
      $('lblStatus').textContent = labels.length === 1 ? '1 etiqueta lista. En el cuadro de impresión elige la Brother QL-800 y el rollo de 62 mm.' : `${labels.length} etiquetas listas. En el cuadro de impresión elige la Brother QL-800 y el rollo de 62 mm.`;
      $('lblPrint').disabled = !labels.length;
    } catch (e) { $('lblStatus').textContent = e.message; }
  }

  $('lblHeight').addEventListener('change', applySize);
  $('lblPrint').addEventListener('click', () => window.print());
  $('lblClose').addEventListener('click', () => window.close());
  init();
})();
