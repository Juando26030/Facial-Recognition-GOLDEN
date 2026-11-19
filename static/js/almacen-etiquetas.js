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

  const FIELDS = { height_mm: 'tplHeight', qr_pos: 'tplQrPos', qr_mm: 'tplQrMm', align: 'tplAlign', title_mm: 'tplTitleMm', code_mm: 'tplCodeMm', sub_mm: 'tplSubMm', extra_text: 'tplExtra', copies: 'tplCopies' };
  const CHECKS = { show_title: 'tplShowTitle', show_code: 'tplShowCode', show_sub: 'tplShowSub' };
  let tpl = null, defaults = null;

  function readForm() {
    const t = {};
    Object.keys(FIELDS).forEach((k) => { t[k] = $(FIELDS[k]).value; });
    Object.keys(CHECKS).forEach((k) => { t[k] = $(CHECKS[k]).checked; });
    return t;
  }
  function fillForm(t) {
    Object.keys(FIELDS).forEach((k) => { $(FIELDS[k]).value = t[k]; });
    Object.keys(CHECKS).forEach((k) => { $(CHECKS[k]).checked = !!t[k]; });
  }
  const num = (v, lo, hi, d) => { const n = Number(v); return Number.isFinite(n) ? Math.max(lo, Math.min(hi, n)) : d; };

  /* La página del rollo mide SIEMPRE 62 mm de ancho; el alto lo elige la plantilla (29 mm = etiqueta troquelada). */
  function applySize(t) {
    const h = num(t.height_mm, 15, 100, 29);
    let st = $('lblPageStyle');
    if (!st) { st = document.createElement('style'); st.id = 'lblPageStyle'; document.head.appendChild(st); }
    st.textContent = `@page { size: 62mm ${h}mm; margin: 0; } .gw-almlbl__label { width: 62mm; height: ${h}mm; }`;
  }

  function render() {
    if (!tpl) return;
    const t = tpl, h = num(t.height_mm, 15, 100, 29);
    applySize(t);
    const vertical = t.qr_pos === 'top';
    const auto = vertical ? Math.max(8, Math.min(h * 0.55, 40)) : h - 5;
    const q = num(t.qr_mm, 0, 60, 0) || auto;
    const qrMm = Math.min(q, vertical ? h - 4 : h - 2, 58);
    const one = (l) => {
      const hasQr = t.qr_pos !== 'none';
      const qr = hasQr ? `<div class="gw-almlbl__qr" data-qr="${qrMm}">${qrSvg(l.code)}</div>` : '';
      const text = `<div class="gw-almlbl__text">${t.show_title ? `<p class="gw-almlbl__title" data-fs="${num(t.title_mm, 2, 9, 3.8)}">${esc(l.title)}</p>` : ''}${t.show_code ? `<p class="gw-almlbl__code" data-fs="${num(t.code_mm, 2, 9, 3.6)}">${esc(l.code)}</p>` : ''}${t.show_sub && l.subtitle ? `<p class="gw-almlbl__sub" data-fs="${num(t.sub_mm, 1.5, 7, 2.8)}">${esc(l.subtitle)}</p>` : ''}${t.extra_text ? `<p class="gw-almlbl__sub" data-fs="${num(t.sub_mm, 1.5, 7, 2.8)}">${esc(t.extra_text)}</p>` : ''}</div>`;
      const cls = 'gw-almlbl__label' + (vertical ? ' gw-almlbl__label--top' : '') + (t.align === 'center' ? ' gw-almlbl__label--center' : '');
      return `<section class="${cls}">${t.qr_pos === 'right' ? text + qr : qr + text}</section>`;
    };
    const copies = Math.round(num(t.copies, 1, 10, 1));
    $('lblSheet').innerHTML = labels.map((l) => one(l).repeat(copies)).join('');
    $('lblSheet').querySelectorAll('[data-qr]').forEach((e) => { e.style.width = e.style.height = e.dataset.qr + 'mm'; });          // por JS: la política CSP no admite style="" en el HTML
    $('lblSheet').querySelectorAll('[data-fs]').forEach((e) => { e.style.fontSize = e.dataset.fs + 'mm'; });
  }

  async function saveTemplate() {
    try {
      const r = await fetch('/api/almacen/label-template', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ template: readForm() }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'No se pudo guardar la plantilla');
      tpl = d.template; fillForm(tpl); render();
      showToast('Plantilla guardada para todos', 'success');
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function init() {
    const body = { unit_ids: ids('u'), product_ids: ids('p') };
    const design = !body.unit_ids.length && !body.product_ids.length;          // sin elementos elegidos: solo se diseña la plantilla, con una etiqueta de ejemplo
    try {
      if (design) {
        const r = await fetch('/api/almacen/label-template');
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'No se pudo leer la plantilla');
        defaults = d.defaults;
        labels = [{ code: 'GW1A2B3C', title: 'Portátil Lenovo #1', subtitle: 'Por modelo' }];
        tpl = d.template; fillForm(tpl); render();
        $('lblStatus').textContent = 'Modo diseño: así se verá cada etiqueta (ejemplo). Ajusta, guarda la plantilla y luego imprime desde «Objetos y QR» o «Etiqueta QR» de cada elemento.';
        return;
      }
      const r = await fetch('/api/almacen/labels', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'No se pudieron preparar las etiquetas');
      labels = d.labels || [];
      tpl = d.template; fillForm(tpl);
      render();
      $('lblStatus').textContent = labels.length === 1 ? '1 etiqueta lista. En el cuadro de impresión elige la Brother QL-800 y el rollo de 62 mm.' : `${labels.length} etiquetas listas. En el cuadro de impresión elige la Brother QL-800 y el rollo de 62 mm.`;
      $('lblPrint').disabled = !labels.length;
    } catch (e) { $('lblStatus').textContent = e.message; }
  }

  $('lblEditor').addEventListener('input', () => { tpl = readForm(); render(); });          // vista previa en vivo
  $('tplSave').addEventListener('click', saveTemplate);
  $('tplReset').addEventListener('click', async () => {
    if (!defaults) { try { const r = await fetch('/api/almacen/label-template'); defaults = (await r.json()).defaults; } catch (e) { return; } }
    tpl = Object.assign({}, defaults); fillForm(tpl); render();
    showToast('Formato de fábrica en pantalla: pulsa «Guardar plantilla» para dejarlo para todos', 'info');
  });
  $('lblPrint').addEventListener('click', () => window.print());
  $('lblClose').addEventListener('click', () => window.close());
  init();
})();
