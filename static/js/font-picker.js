/* Selector de tipografías con buscador y vista previa: cada opción se ve escrita en SU PROPIA fuente. Es el MISMO componente en Configuración > Apariencia y en el diseñador de escarapelas, y
   lee la misma lista (`GoldenFonts.choices`, generada por scripts/gen_fonts_css.py) de las mismas fuentes alojadas en static/fonts (orden del 24-oct-2026).

   GoldenFontPicker.mount(host, { value, original, onChange })  → { get(), set(v) }
     original: { value: '', label: 'Original (Agrandir)', css: "'Agrandir', sans-serif" } agrega esa opción al principio (solo Configuración).
   GoldenFontPicker.ensureLoaded(family)  → Promise: espera a que la fuente (normal y negrita) esté cargada ANTES de dibujar/imprimir, para que la etiqueta no cambie de tipografía.
   GoldenFontPicker.filter(names, query) → lista filtrada sin tildes ni mayúsculas (pura; se prueba en tests/js/font_picker_check.js). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(root);
  else root.GoldenFontPicker = factory(root);
})(typeof window !== 'undefined' ? window : this, function (root) {
  function fold(s) { return String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim(); }
  function filter(names, query) {
    const q = fold(query);
    return q ? names.filter((n) => fold(n).indexOf(q) >= 0) : names.slice();
  }
  function ensureLoaded(family) {
    const doc = root.document;
    if (!doc || !doc.fonts || !doc.fonts.load) return Promise.resolve();
    const f = "'" + String(family || 'Roboto').replace(/'/g, '') + "'";
    return Promise.all([doc.fonts.load('400 16px ' + f), doc.fonts.load('700 16px ' + f)]).then(() => undefined, () => undefined);
  }

  const CSS = `
.gfp { position:relative; }
.gfp-btn { width:100%; text-align:left; border:1px solid #ddd; border-radius:8px; padding:7px 28px 7px 10px; font-size:0.95rem; background:#fff; cursor:pointer; box-sizing:border-box; position:relative; min-height:34px; }
.gfp-btn::after { content:'▾'; position:absolute; right:10px; top:50%; transform:translateY(-50%); color:#666; }
.gfp-panel { position:absolute; z-index:10000; left:0; right:0; top:calc(100% + 4px); background:#fff; border:1px solid #ccc; border-radius:10px; box-shadow:0 10px 30px rgba(0,0,0,0.18); padding:6px; min-width:220px; }
.gfp-panel[hidden] { display:none; }
.gfp-search { width:100%; box-sizing:border-box; border:1px solid #ddd; border-radius:8px; padding:7px 10px; font-size:0.85rem; margin-bottom:6px; }
.gfp-list { list-style:none; margin:0; padding:0; max-height:260px; overflow-y:auto; }
.gfp-item { padding:7px 10px; border-radius:6px; cursor:pointer; font-size:1.05rem; line-height:1.25; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.gfp-item:hover, .gfp-item.act { background:#f3efe0; }
.gfp-item[aria-selected="true"] { font-weight:700; }
.gfp-empty { padding:8px 10px; color:#666; font-size:0.82rem; }`;

  function mount(host, opts) {
    opts = opts || {};
    const doc = root.document;
    if (!doc.getElementById('gfp-style')) { const st = doc.createElement('style'); st.id = 'gfp-style'; st.textContent = CSS; doc.head.appendChild(st); }
    const choices = (root.GoldenFonts && root.GoldenFonts.choices) || [];
    const options = (opts.original ? [opts.original] : []).concat(choices.map((n) => ({ value: n, label: n, css: "'" + n + "', sans-serif" })));
    let current = opts.value == null ? (opts.original ? '' : 'Roboto') : opts.value;
    const labelOf = (v) => options.find((o) => o.value === v) || { label: v || '', css: v ? "'" + v + "', sans-serif" : 'inherit' };

    host.classList.add('gfp');
    host.innerHTML = '<button type="button" class="gfp-btn" aria-haspopup="listbox" aria-expanded="false"></button>'
      + '<div class="gfp-panel" hidden><input type="search" class="gfp-search" placeholder="Buscar tipografía…" aria-label="Buscar tipografía" autocomplete="off"><ul class="gfp-list" role="listbox"></ul></div>';
    const btn = host.querySelector('.gfp-btn'), panel = host.querySelector('.gfp-panel'), search = host.querySelector('.gfp-search'), list = host.querySelector('.gfp-list');
    let shown = options, active = -1;

    function paintButton() { const o = labelOf(current); btn.textContent = o.label; btn.style.fontFamily = o.css; }
    function paintList() {
      const names = filter(shown.map((o) => o.label), search.value);
      shown = options.filter((o) => names.indexOf(o.label) >= 0);
      list.innerHTML = '';
      if (!shown.length) { list.innerHTML = '<li class="gfp-empty">Ninguna tipografía se llama así.</li>'; return; }
      shown.forEach((o, i) => {
        const li = doc.createElement('li');
        li.className = 'gfp-item' + (i === active ? ' act' : '');
        li.setAttribute('role', 'option');
        li.setAttribute('aria-selected', o.value === current ? 'true' : 'false');
        li.dataset.value = o.value;
        li.style.fontFamily = o.css;
        li.textContent = o.label;
        list.appendChild(li);
      });
    }
    function open() {
      shown = options; active = Math.max(0, options.findIndex((o) => o.value === current)); search.value = '';
      panel.hidden = false; btn.setAttribute('aria-expanded', 'true'); paintList(); search.focus();
      const a = list.querySelector('.act'); if (a && a.scrollIntoView) a.scrollIntoView({ block: 'nearest' });
    }
    function close() { panel.hidden = true; btn.setAttribute('aria-expanded', 'false'); }
    function pick(value) {
      current = value; paintButton(); close();
      ensureLoaded(value).then(() => { if (opts.onChange) opts.onChange(value); });          // se avisa cuando la fuente ya está lista para dibujarse
    }
    btn.addEventListener('click', () => (panel.hidden ? open() : close()));
    search.addEventListener('input', () => { active = 0; shown = options; paintList(); });
    search.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault(); if (!shown.length) return;
        active = (active + (e.key === 'ArrowDown' ? 1 : -1) + shown.length) % shown.length; paintList();
        const a = list.querySelector('.act'); if (a && a.scrollIntoView) a.scrollIntoView({ block: 'nearest' });
      } else if (e.key === 'Enter') { e.preventDefault(); if (shown[active]) pick(shown[active].value); }
      else if (e.key === 'Escape') { e.preventDefault(); close(); btn.focus(); }
    });
    list.addEventListener('click', (e) => { const li = e.target.closest('.gfp-item'); if (li) pick(li.dataset.value); });
    doc.addEventListener('pointerdown', (e) => { if (!panel.hidden && !host.contains(e.target)) close(); });
    paintButton();
    return { get: () => current, set: (v) => { current = v; paintButton(); } };
  }

  return { mount, ensureLoaded, filter };
});
