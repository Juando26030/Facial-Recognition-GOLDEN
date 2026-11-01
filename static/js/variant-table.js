/* Tabla de variantes (P11): lógica pura, sin DOM, para convertir una hoja de cálculo en variantes de P9 y al revés. Se prueba en Node (tests/js/variant_table_check.js).
   Una TABLA es: variables (los campos que deciden: sus combinaciones son las filas), columnas (cada una apunta a un elemento y una propiedad, con un tipo) y filas con sus celdas.

     spec = { variables: [{ field, label?, options? }],                                   // 1 a 3 campos con opciones
              columns:   [{ id, name, field, prop, type: 'text'|'image'|'date'|'number'|'options', options? }],     // 1 a 15
              rows:      [{ keys: ['Bogotá', 'Empleado'], cells: { <id de columna>: 'texto' } }],
              images?:   { 'bogota.jpg': 'cliente/archivo.jpg' } }                         // archivos ya subidos, por nombre

   Los valores de fecha y número se guardan como TEXTO de presentación (dd/mm/aaaa; 1.234,56): no se vuelven datos consultables.  */
(function () {
  const MAX_ROWS = 200, MAX_COLS = 15, MAX_VARS = 3, MAX_PER_FORM = 3000, MAX_TEXT = 8000;
  const IMG = /\.(png|jpe?g|webp|gif)$/i;
  const IMG_PATH = /^[A-Za-z0-9_-][\w.-]*\/[A-Za-z0-9_-][\w.-]*\.(?:png|jpe?g|webp|gif)$/;
  const norm = (x) => String(x == null ? '' : x).normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
  const slug = (x) => norm(x).replace(/[\s_.\-+]+/g, ' ').trim();          // «Bogotá_Empleado» = «bogota empleado»
  const HIDEABLE = ['content', 'src'];

  // ------------------------------------------------------------------ celdas
  function fmtDate(d, m, y) {
    if (y < 100) y += y < 70 ? 2000 : 1900;
    const dt = new Date(Date.UTC(y, m - 1, d));
    if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return null;
    return `${String(d).padStart(2, '0')}/${String(m).padStart(2, '0')}/${y}`;
  }
  function parseNumber(raw) {
    let t = String(raw).trim().replace(/\s/g, '');
    const neg = t.startsWith('-');
    if (neg || t.startsWith('+')) t = t.slice(1);
    if (!/^[\d.,]+$/.test(t) || !/\d/.test(t)) return null;
    let int, frac = '';
    const lastDot = t.lastIndexOf('.'), lastComma = t.lastIndexOf(',');
    if (lastDot >= 0 && lastComma >= 0) {            // los dos: el ÚLTIMO separador es el decimal
      const dec = Math.max(lastDot, lastComma), other = dec === lastDot ? ',' : '.';
      int = t.slice(0, dec); frac = t.slice(dec + 1);
      if (int.split(dec === lastDot ? '.' : ',').length > 1) return null;
      int = int.split(other).join('');
      if (!/^\d+$/.test(int) || !/^\d*$/.test(frac)) return null;
    } else if (lastComma >= 0) {                     // solo comas: la coma es el decimal (formato colombiano)
      if (t.split(',').length > 2) return null;
      [int, frac] = t.split(',');
      if (!/^\d+$/.test(int) || !/^\d*$/.test(frac)) return null;
    } else if (lastDot >= 0) {                       // solo puntos: «1.234» o «1.234.567» son miles; «12.5» es un decimal
      if (/^\d{1,3}(\.\d{3})+$/.test(t)) int = t.split('.').join('');
      else if (t.split('.').length === 2 && /^\d+\.\d+$/.test(t)) [int, frac] = t.split('.');
      else return null;
    } else int = t;
    if (int.length > 15 || frac.length > 8) return null;
    int = int.replace(/^0+(?=\d)/, '');
    return (neg && (int !== '0' || /[1-9]/.test(frac)) ? '-' : '') + int.replace(/\B(?=(\d{3})+(?!\d))/g, '.') + (frac ? ',' + frac : '');
  }
  // Valida y normaliza una celda. Devuelve { value } (value '' = celda vacía, no genera variante) o { error }.
  function parseCell(type, raw, col) {
    const t = String(raw == null ? '' : raw).trim();
    if (!t) return { value: '' };
    if (type === 'text') return t.length > MAX_TEXT ? { error: `El texto es demasiado largo (máximo ${MAX_TEXT} caracteres)` } : { value: t };
    if (type === 'date') {
      let m = /^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2}|\d{4})$/.exec(t), v = null;
      if (m) v = fmtDate(+m[1], +m[2], +m[3]);
      else if ((m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(t))) v = fmtDate(+m[3], +m[2], +m[1]);
      return v ? { value: v } : { error: 'Fecha no válida (escribe dd/mm/aaaa)' };
    }
    if (type === 'number') { const v = parseNumber(t); return v ? { value: v } : { error: 'Número no válido (ejemplo: 1.234,56)' }; }
    if (type === 'options') {
      const hit = ((col && col.options) || []).find((o) => norm(o) === norm(t));
      return hit ? { value: hit } : { error: 'No está en la lista de opciones' };
    }
    if (type === 'image') return (IMG.test(t) && !/[\\/]/.test(t) && !t.startsWith('.')) || IMG_PATH.test(t) ? { value: t } : { error: 'Usa un archivo PNG, JPG, WEBP o GIF' };
    return { error: 'Tipo de columna desconocido' };
  }

  // ------------------------------------------------------------------ filas desde las variables
  // Todas las combinaciones de las opciones (o del subconjunto elegido por variable). Más de 200 → error: hay que elegir un subconjunto.
  function rowsFromVariables(variables, subsets) {
    if (!variables.length || variables.length > MAX_VARS) return { error: `Elige de 1 a ${MAX_VARS} campos que decidan` };
    const lists = variables.map((v, i) => {
      const all = v.options || [], pick = subsets && subsets[i];
      return pick ? all.filter((o) => pick.some((p) => norm(p) === norm(o))) : all;
    });
    const total = lists.reduce((a, l) => a * l.length, 1);
    if (!total) return { error: 'Alguno de los campos no tiene opciones' };
    if (total > MAX_ROWS) return { error: `Son ${total} combinaciones y el máximo es ${MAX_ROWS}: elige un subconjunto de valores`, total };
    let rows = [[]];
    lists.forEach((l) => { rows = rows.flatMap((r) => l.map((o) => r.concat([o]))); });
    return { rows: rows.map((keys) => ({ keys, cells: {} })), total };
  }

  // ------------------------------------------------------------------ tabla → variantes (función pura)
  const leaf = (field, value) => ({ field, op: 'equals', value });
  const whenOf = (spec, row) => (spec.variables.length === 1 ? leaf(spec.variables[0].field, row.keys[0]) : { match: 'all', rules: spec.variables.map((v, i) => leaf(v.field, row.keys[i])) });
  const nameOf = (row) => row.keys.join(' · ').slice(0, 40);

  // `existing`: { fid: { variants: {...} } } o el diseño (design.fields). Devuelve { variants, summary, problems, error? } sin tocar nada.
  function build(spec, existing, opts) {
    opts = opts || {};
    const problems = [], fields = {}, summary = { variants: 0, elements: 0, replaced: 0, rowsWithoutImage: 0, invalid: 0, notInList: 0 };
    const fail = (msg) => ({ error: msg, variants: {}, summary, problems });
    if (!spec.variables.length || spec.variables.length > MAX_VARS) return fail(`Elige de 1 a ${MAX_VARS} campos que decidan`);
    if (!spec.columns.length || spec.columns.length > MAX_COLS) return fail(`La tabla admite de 1 a ${MAX_COLS} columnas`);
    if (spec.rows.length > MAX_ROWS) return fail(`La tabla admite hasta ${MAX_ROWS} filas`);
    const seen = new Set();
    for (const c of spec.columns) { const k = c.field + '\u0000' + c.prop; if (seen.has(k)) return fail(`Dos columnas apuntan a lo mismo («${c.name}»)`); seen.add(k); }
    const ex = (fid, prop) => (((existing || {})[fid] || {}).variants || {})[prop];
    const images = spec.images || {};
    spec.columns.forEach((c) => {
      const items = [];
      spec.rows.forEach((row, ri) => {
        const cell = parseCell(c.type, (row.cells || {})[c.id], c);
        if (cell.error) { if (c.type === 'options') summary.notInList += 1; else summary.invalid += 1; problems.push({ row: ri, col: c.id, message: cell.error }); return; }
        let value = cell.value;
        if (!value) { if (c.type === 'image') summary.rowsWithoutImage += 1; return; }
        if (c.type === 'image' && !IMG_PATH.test(value)) {                   // un nombre de archivo: solo cuenta si ya se subió y emparejó
          if (!images[value]) { summary.rowsWithoutImage += 1; problems.push({ row: ri, col: c.id, message: 'La imagen aún no está subida', soft: true }); return; }
          value = images[value];
        }
        items.push({ when: whenOf(spec, row), value, name: nameOf(row) });
      });
      const prev = ex(c.field, c.prop);
      summary.replaced += prev ? (prev.items || []).length : 0;
      const block = { items };
      if (prev && prev.default) block.default = prev.default;               // el valor por defecto que ya había se conserva
      if (items.length || block.default) { (fields[c.field] = fields[c.field] || {})[c.prop] = block; }
      else if (prev) { (fields[c.field] = fields[c.field] || {})[c.prop] = null; }       // ya no queda nada: se quita la propiedad
      summary.variants += items.length;
    });
    summary.elements = Object.keys(fields).length;
    const others = Number(opts.otherVariants || 0);
    if (summary.variants - summary.replaced + others > MAX_PER_FORM) return fail(`El formulario admitiría más de ${MAX_PER_FORM} variantes en total`);
    return { variants: fields, summary, problems };
  }

  // Aplica el resultado de build a un diseño (REEMPLAZA las propiedades de las columnas; no toca las demás). Devuelve las variantes de cada elemento tocado.
  function applyTo(design, built) {
    Object.entries(built.variants).forEach(([fid, props]) => {
      const f = design.fields[fid]; if (!f) return;
      f.variants = f.variants || {};
      Object.entries(props).forEach(([prop, block]) => {
        if (block) { f.variants[prop] = block; if (HIDEABLE.includes(prop) && !f[prop]) f[prop] = block.default || ''; }
        else delete f.variants[prop];
      });
      if (!Object.keys(f.variants).length) delete f.variants;
    });
    return design;
  }

  // ------------------------------------------------------------------ al revés: del diseño a la tabla (ida y vuelta)
  function fromDesign(design, spec) {
    const rows = spec.rows.map((r) => ({ keys: r.keys.slice(), cells: {} }));
    const index = new Map(rows.map((r, i) => [r.keys.map(norm).join('\u0001'), i]));
    let skipped = 0;
    spec.columns.forEach((c) => {
      const v = (((design.fields[c.field] || {}).variants) || {})[c.prop];
      ((v && v.items) || []).forEach((it) => {
        let leaves = null, w = it.when;
        if (w && !w.rules) leaves = [w]; else if (w && w.rules && w.match !== 'any' && !w.name && w.rules.every((r) => !r.rules)) leaves = w.rules;
        const byField = leaves && leaves.length === spec.variables.length && leaves.every((l) => l.op === 'equals' && typeof l.value === 'string') ? Object.fromEntries(leaves.map((l) => [l.field, l.value])) : null;
        const keys = byField && spec.variables.map((vr) => byField[vr.field]);
        const at = keys && keys.every((k) => k !== undefined) ? index.get(keys.map(norm).join('\u0001')) : undefined;
        if (at === undefined) { skipped += 1; return; }
        rows[at].cells[c.id] = it.value;
      });
    });
    return { rows, skipped };
  }

  // ------------------------------------------------------------------ pegar desde Excel
  // Texto del portapapeles (columnas separadas por tabulador, celdas con comillas como las escribe Excel) → matriz.
  function parsePaste(text) {
    const t = String(text == null ? '' : text).replace(/\r\n?/g, '\n');
    const out = [];
    let row = [], cell = '', q = false, i = 0;
    while (i < t.length) {
      const ch = t[i];
      if (q) {
        if (ch === '"') { if (t[i + 1] === '"') { cell += '"'; i += 2; continue; } q = false; i++; continue; }
        cell += ch; i++; continue;
      }
      if (ch === '"' && cell === '') { q = true; i++; continue; }
      if (ch === '\t') { row.push(cell); cell = ''; i++; continue; }
      if (ch === '\n') { row.push(cell); out.push(row); row = []; cell = ''; i++; continue; }
      cell += ch; i++;
    }
    if (cell !== '' || row.length) { row.push(cell); out.push(row); }
    while (out.length && out[out.length - 1].every((c) => c === '')) out.pop();       // las filas vacías del final no cuentan
    return out;
  }
  // Pone una matriz en la tabla. Columnas de la matriz = [variables..., columnas de datos...] si `byKeys`; si no, empiezan en `startCol` (índice entre las columnas de datos).
  // Con `byKeys` las filas se emparejan por el valor de las variables (sin tildes ni mayúsculas); lo que no esté se informa.
  function pasteInto(spec, grid, o) {
    o = o || {};
    const nv = spec.variables.length, cols = spec.columns, res = { applied: 0, unmatched: [], skippedHeader: false, notInList: [] };
    let data = grid;
    const names = (o.byKeys ? spec.variables.map((v) => v.label || v.field).concat(cols.map((c) => c.name)) : cols.slice(o.startCol || 0).map((c) => c.name));
    if (data.length && data[0].length && data[0].every((c, i) => norm(c) === norm(names[i]))) { data = data.slice(1); res.skippedHeader = true; }       // la fila de encabezados no es un dato
    data.forEach((line, k) => {
      let target, offset = 0;
      if (o.byKeys) {
        const keys = line.slice(0, nv), at = spec.rows.findIndex((r) => r.keys.every((kv, i) => norm(kv) === norm(keys[i])));
        if (at < 0) { res.unmatched.push(k); return; }
        target = spec.rows[at]; offset = nv;
        line.slice(offset).forEach((raw, j) => { const c = cols[j]; if (c) { target.cells[c.id] = raw; res.applied += 1; } });
      } else {
        target = spec.rows[(o.startRow || 0) + k];
        if (!target) { res.unmatched.push(k); return; }
        line.forEach((raw, j) => { const c = cols[(o.startCol || 0) + j]; if (c) { target.cells[c.id] = raw; res.applied += 1; } });
      }
    });
    return res;
  }

  // ------------------------------------------------------------------ imágenes: emparejar por nombre ANTES de subir nada
  // `files`: nombres. Un archivo empareja con la fila cuyo valor (o valores, separados por _ - espacio) coincide con su nombre sin extensión, sin tildes ni mayúsculas.
  // Con 2 o 3 variables se acepta el orden de la tabla. Con varias columnas de imagen: «fila@columna.jpg».
  function matchImages(spec, files) {
    const imageCols = spec.columns.filter((c) => c.type === 'image');
    const matches = [], unmatched = [], duplicated = [], taken = new Set();
    const rowKey = (r) => slug(r.keys.join(' '));
    const byKey = new Map(spec.rows.map((r, i) => [rowKey(r), i]));
    files.forEach((name) => {
      if (!IMG.test(name)) { unmatched.push({ file: name, reason: 'No es una imagen PNG, JPG, WEBP o GIF' }); return; }
      let stem = name.replace(/\.[^.]+$/, ''), col = imageCols[0];
      if (imageCols.length > 1) {
        const at = stem.lastIndexOf('@');
        const named = at >= 0 && imageCols.find((c) => slug(c.name) === slug(stem.slice(at + 1)));
        if (!named) { unmatched.push({ file: name, reason: 'Hay varias columnas de imagen: usa «fila@columna»' }); return; }
        col = named; stem = stem.slice(0, at);
      }
      if (!col) { unmatched.push({ file: name, reason: 'La tabla no tiene una columna de imagen' }); return; }
      const ri = byKey.get(slug(stem));
      if (ri === undefined) { unmatched.push({ file: name, reason: 'No coincide con ninguna fila' }); return; }
      const k = ri + ':' + col.id;
      if (taken.has(k)) { duplicated.push(name); return; }
      taken.add(k);
      matches.push({ file: name, row: ri, col: col.id });
    });
    const rowsWithout = imageCols.reduce((a, c) => a + spec.rows.filter((_, i) => !taken.has(i + ':' + c.id)).length, 0);
    return { matches, unmatched, duplicated, rowsWithout };
  }

  const api = { MAX_ROWS, MAX_COLS, MAX_VARS, MAX_PER_FORM, norm, parseCell, rowsFromVariables, build, applyTo, fromDesign, parsePaste, pasteInto, matchImages };
  if (typeof window !== 'undefined') window.VariantTable = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
