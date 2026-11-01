/* Nombres de los elementos de un formulario en las LISTAS del diseñador (P11b): dos textos tipo «Texto informativo» o «Imagen» ya no se confunden.
     ElementNames.build(design, { typeLabel(tipo), plain(html) }) -> { <id>: { short, full, internal } }
   - `internal_name` (el «Nombre interno» del panel de cada elemento, texto plano de hasta 60 caracteres), si existe, es el nombre en TODAS las listas y en el lienzo.
   - Si no, un nombre automático: «Hoja 2 · Texto informativo 3 — «Ciudad: Bogotá. Lugar evento…»» (hoja si hay varias, número por tipo en el orden del formulario y el comienzo del contenido).
   - `short` = el nombre sin hoja ni vista previa (para encabezados de columnas). La identidad de un elemento es SIEMPRE su id: renombrar o reordenar no cambia a qué elemento apunta nada. */
(function () {
  const clip = (t, n) => { const s = String(t == null ? '' : t).replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s; };
  const norm = (x) => String(x == null ? '' : x).normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
  const STATIC = ['heading', 'paragraph', 'image'];

  function build(design, o) {
    o = o || {};
    const typeLabel = o.typeLabel || ((t) => t), plain = o.plain || ((x) => String(x == null ? '' : x).replace(/<[^>]*>/g, ' '));
    const sheets = (design.sheets || []).length > 1 ? design.sheets : null;
    const sheetNo = {}; if (sheets) sheets.forEach((s, i) => { sheetNo[s.id] = i + 1; });
    const order = [], sheetOf = {};
    (design.rows || []).forEach((r) => (r.items || []).forEach((id) => { if (design.fields[id] && !(id in sheetOf)) { order.push(id); sheetOf[id] = r.sheet; } }));
    Object.keys(design.fields).forEach((id) => { if (!(id in sheetOf)) { order.push(id); sheetOf[id] = sheets ? sheets[sheets.length - 1].id : undefined; } });
    const perType = {}, ord = {}, labelTotal = {}, labelSeen = {};
    order.forEach((id) => { const f = design.fields[id]; perType[f.type] = (perType[f.type] || 0) + 1; ord[id] = perType[f.type]; if (!STATIC.includes(f.type) && f.label) { const k = norm(f.label); labelTotal[k] = (labelTotal[k] || 0) + 1; } });
    const out = {};
    order.forEach((id) => {
      const f = design.fields[id], internal = clip(f.internal_name, 60);
      let short, preview = '';
      if (STATIC.includes(f.type)) {
        short = `${typeLabel(f.type)} ${ord[id]}`;
        preview = f.type === 'image' ? clip(f.alt || (f.src ? String(f.src).split('/').pop() : '') || '(sin imagen)', 40) : clip(plain(f.content || ''), 40) || '(vacío)';
      } else {
        const label = clip(f.label, 80) || `${typeLabel(f.type)} ${ord[id]}`, k = norm(f.label);
        short = labelTotal[k] > 1 ? `${label} (${(labelSeen[k] = (labelSeen[k] || 0) + 1)})` : label;
      }
      const prefix = sheets && sheetNo[sheetOf[id]] ? `Hoja ${sheetNo[sheetOf[id]]} · ` : '';
      out[id] = internal ? { short: internal, full: internal, internal: true } : { short, full: `${prefix}${short}${STATIC.includes(f.type) ? ` — «${preview}»` : ''}`, internal: false };
    });
    return out;
  }

  const api = { build, clip };
  if (typeof window !== 'undefined') window.ElementNames = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
