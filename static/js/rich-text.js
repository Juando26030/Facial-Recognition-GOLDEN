/* Texto con formato de los formularios web (P3): limpieza por lista blanca, pintado y editor con barra de herramientas.
   Las MISMAS reglas que app/richtext.py (el servidor limpia al guardar; aquí se vuelve a limpiar al pintar). Casos comunes: tests/rich_vectors.json.

     RichText.hasFormat(texto)          ¿tiene etiquetas de la lista blanca? Si no, es texto plano (un texto viejo como «menores de <18 años» se ve igual)
     RichText.clean(html, basic)        HTML limpio (b i u strong em p div br ul ol li span, con estilos filtrados)
     RichText.html(texto, basic)        {rich, html}: texto plano ya escapado, o HTML limpio
     RichText.toPlain(texto)            texto plano (sin etiquetas; saltos de línea y «• » en listas) para destinos sin HTML
     RichText.mount(contenedor, opts)   editor: { value, basic, label, onChange(valor) } -> { getValue, setValue }          */
(function () {
  const TAGS_FULL = ['b', 'strong', 'i', 'em', 'u', 'p', 'div', 'br', 'ul', 'ol', 'li', 'span'];
  const TAGS_BASIC = ['b', 'strong', 'i', 'em', 'u', 'br', 'span'];
  const SKIP = ['script', 'style', 'iframe', 'object', 'embed', 'template', 'svg', 'math', 'noscript', 'textarea', 'title', 'head', 'frame', 'frameset', 'applet', 'xmp', 'plaintext', 'noembed', 'noframes', 'select', 'option'];
  const MAX_DEPTH = 6;
  const FORMAT_RE = /<\/?(?:b|strong|i|em|u|p|div|br|ul|ol|li|span)(?:\s+[a-z-]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>"']*))*\s*\/?>/i;
  const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/;
  const RGB = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*(0|1|0?\.\d{1,3}|1\.0)\s*)?\)$/;
  const SIZE = /^(\d{1,3}(?:\.\d{1,2})?)(px|pt|em|rem|%)$/;
  const SIZE_RANGE = { px: [8, 64], pt: [6, 48], em: [0.5, 4], rem: [0.5, 4], '%': [50, 300] };
  const esc = (t) => String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const hostedFonts = () => (typeof window !== 'undefined' && window.GoldenFonts && window.GoldenFonts.choices) || [];

  const hasFormat = (t) => FORMAT_RE.test(String(t == null ? '' : t));

  function color(v) {
    v = v.trim().toLowerCase();
    if (HEX.test(v)) return v;
    const m = RGB.exec(v);
    if (m && [m[1], m[2], m[3]].every((x) => +x <= 255)) return m[4] !== undefined ? `rgba(${+m[1]},${+m[2]},${+m[3]},${m[4]})` : `rgb(${+m[1]},${+m[2]},${+m[3]})`;
    return null;
  }

  function cleanStyle(style, full) {
    const out = [];
    String(style || '').split(';').forEach((decl) => {
      const i = decl.indexOf(':');
      if (i < 0) return;
      const prop = decl.slice(0, i).trim().toLowerCase(), value = decl.slice(i + 1).trim(), low = value.toLowerCase();
      if (prop === 'color') { const c = color(value); if (c) out.push('color:' + c); }
      else if (prop === 'font-weight' && ['bold', '700', 'normal', '400'].includes(low)) out.push('font-weight:' + (['bold', '700'].includes(low) ? 'bold' : 'normal'));
      else if (prop === 'font-style' && ['italic', 'normal'].includes(low)) out.push('font-style:' + low);
      else if ((prop === 'text-decoration' || prop === 'text-decoration-line') && ['underline', 'none'].includes(low)) out.push('text-decoration:' + low);
      else if (prop === 'font-size' && full) {
        const m = SIZE.exec(low);
        if (m && +m[1] >= SIZE_RANGE[m[2]][0] && +m[1] <= SIZE_RANGE[m[2]][1]) out.push('font-size:' + m[1] + m[2]);
      } else if (prop === 'font-family' && full) {
        const names = value.split(',').map((n) => n.trim().replace(/^['"]|['"]$/g, '')).filter((n) => hostedFonts().includes(n));
        if (names.length) out.push('font-family:' + names.slice(0, 3).map((n) => `'${n}'`).join(','));
      } else if (prop === 'text-align' && full && ['left', 'center', 'right', 'justify'].includes(low)) out.push('text-align:' + low);
    });
    return out.join(';');
  }

  function clean(input, basic) {
    const allowed = basic ? TAGS_BASIC : TAGS_FULL, full = !basic;
    const doc = new DOMParser().parseFromString('<!doctype html><body>' + String(input == null ? '' : input), 'text/html');
    const walk = (node, stack) => {
      let out = '';
      node.childNodes.forEach((n) => {
        if (n.nodeType === 3) { out += esc(n.nodeValue); return; }
        if (n.nodeType !== 1) return;
        const tag = n.localName;
        if (SKIP.includes(tag)) return;
        if (!allowed.includes(tag)) { out += walk(n, stack); return; }
        if (tag === 'li' && !stack.some((t) => t === 'ul' || t === 'ol')) { out += walk(n, stack); return; }
        if (tag === 'br') { out += '<br>'; return; }
        if (stack.length >= MAX_DEPTH) { out += walk(n, stack); return; }
        const st = cleanStyle(n.getAttribute('style'), full);
        out += (st ? `<${tag} style="${st}">` : `<${tag}>`) + walk(n, stack.concat(tag)) + `</${tag}>`;
      });
      return out;
    };
    return walk(doc.body, []).trim();
  }

  function html(text, basic) {
    const t = String(text == null ? '' : text);
    return hasFormat(t) ? { rich: true, html: clean(t, basic) } : { rich: false, html: esc(t) };
  }

  function toPlain(text) {
    const t = String(text == null ? '' : text);
    if (!hasFormat(t)) return t.trim();
    const doc = new DOMParser().parseFromString('<!doctype html><body>' + t, 'text/html');
    let out = '';
    const lists = [];
    const walk = (node) => node.childNodes.forEach((n) => {
      if (n.nodeType === 3) { out += n.nodeValue; return; }
      if (n.nodeType !== 1 || SKIP.includes(n.localName)) return;
      const tag = n.localName;
      if (tag === 'br') { out += '\n'; return; }
      if (tag === 'ul' || tag === 'ol') { lists.push([tag, 0]); walk(n); lists.pop(); out += '\n'; return; }
      if (tag === 'li') { const l = lists[lists.length - 1]; if (l) l[1] += 1; out += '\n' + (l && l[0] === 'ol' ? l[1] + '. ' : '• '); walk(n); return; }
      if (tag === 'p' || tag === 'div') { out += '\n'; walk(n); out += '\n'; return; }
      walk(n);
    });
    walk(doc.body);
    return out.replace(/\n{3,}/g, '\n\n').trim();
  }

  const api = { hasFormat, clean, cleanStyle, html, toPlain, esc };
  if (typeof window === 'undefined') { if (typeof module !== 'undefined') module.exports = api; return; }
  window.RichText = api;

  // Estilo de los textos con formato (listas, párrafos): una sola vez por página.
  function ensureStyle() {
    if (document.getElementById('rt-style')) return;
    const s = document.createElement('style'); s.id = 'rt-style';
    s.textContent = '.rt p,.rt div{margin:0 0 .4em}.rt ul,.rt ol{margin:.3em 0 .3em 1.4em;padding:0}.rt ul{list-style:disc}.rt ol{list-style:decimal}.rt li{margin:0}'
      + '.rt-ed{min-height:5.5em;max-height:18em;overflow:auto;border:1px solid #ccc;border-radius:0 0 8px 8px;padding:8px;background:#fff;color:#222;font-size:.9rem}.rt-ed:focus{outline:2px solid #8aa4ff}'
      + '.rt-bar{display:flex;flex-wrap:wrap;gap:3px;align-items:center;border:1px solid #ccc;border-bottom:none;border-radius:8px 8px 0 0;padding:4px;background:#f5f6fa}'
      + '.rt-bar button{min-width:28px;padding:3px 6px;border:1px solid #ccc;background:#fff;border-radius:6px;cursor:pointer;font-size:.8rem}.rt-bar select{font-size:.78rem;max-width:130px}';
    document.head.appendChild(s);
  }
  api.ensureStyle = ensureStyle;

  const SIZES = [12, 14, 16, 18, 20, 24, 28, 32, 40];
  function mount(host, opts) {
    opts = opts || {};
    const basic = !!opts.basic;
    ensureStyle();
    host.textContent = '';
    const bar = document.createElement('div'); bar.className = 'rt-bar'; bar.setAttribute('role', 'toolbar'); bar.setAttribute('aria-label', 'Formato del texto');
    const ed = document.createElement('div'); ed.className = 'rt-ed'; ed.contentEditable = 'true'; ed.setAttribute('role', 'textbox'); ed.setAttribute('aria-multiline', 'true'); ed.setAttribute('aria-label', opts.label || 'Texto');
    host.append(bar, ed);
    let saved = null;
    const keep = () => { const sel = window.getSelection && window.getSelection(); if (sel && sel.rangeCount && ed.contains(sel.anchorNode)) saved = sel.getRangeAt(0).cloneRange(); };
    document.addEventListener('selectionchange', keep);
    const restore = () => { ed.focus(); if (saved) { const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(saved); } };

    const value = () => {
      const c = clean(ed.innerHTML.replace(/ /g, ' '), basic);
      return hasFormat(c) ? c : ed.textContent.replace(/ /g, ' ');       // sin etiquetas: queda como texto plano (nada de &lt; sueltos)
    };
    const emit = () => { if (opts.onChange) opts.onChange(value()); };
    const setValue = (text) => {
      const h = html(text, basic);
      ed.innerHTML = h.rich ? h.html : h.html.replace(/\n/g, '<br>');
    };
    const exec = (cmd) => { restore(); try { document.execCommand('styleWithCSS', false, true); } catch (e) { /* sin soporte: sigue */ } document.execCommand(cmd, false, null); emit(); };
    const applyStyle = (prop, val) => {
      restore();
      const sel = window.getSelection();
      if (!sel.rangeCount || sel.isCollapsed) return;
      const range = sel.getRangeAt(0), span = document.createElement('span');
      span.style.setProperty(prop, val);
      try { range.surroundContents(span); } catch (e) { span.appendChild(range.extractContents()); range.insertNode(span); }
      emit();
    };
    const btn = (text, title, fn) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = text; b.title = title; b.setAttribute('aria-label', title); b.addEventListener('mousedown', (e) => e.preventDefault()); b.addEventListener('click', fn); bar.append(b); return b; };
    const select = (title, items, fn) => { const s = document.createElement('select'); s.title = title; s.setAttribute('aria-label', title); s.append(new Option(title, '')); items.forEach(([v, l]) => s.append(new Option(l, v))); s.addEventListener('change', () => { if (s.value) fn(s.value); s.value = ''; }); bar.append(s); return s; };

    btn('N', 'Negrilla', () => exec('bold')).style.fontWeight = '700';
    btn('K', 'Cursiva', () => exec('italic')).style.fontStyle = 'italic';
    btn('S', 'Subrayado', () => exec('underline')).style.textDecoration = 'underline';
    const col = document.createElement('input'); col.type = 'color'; col.title = 'Color del texto'; col.setAttribute('aria-label', 'Color del texto'); col.value = '#000000'; col.style.cssText = 'width:30px;height:26px;padding:0;border:1px solid #ccc;border-radius:6px;';
    col.addEventListener('change', () => applyStyle('color', col.value)); bar.append(col);
    if (!basic) {
      select('Tamaño', SIZES.map((n) => [n + 'px', String(n)]), (v) => applyStyle('font-size', v));
      select('Letra', hostedFonts().map((n) => [n, n]), (v) => applyStyle('font-family', `'${v}'`));
      [['⇤', 'Alinear a la izquierda', 'justifyLeft'], ['↔', 'Centrar', 'justifyCenter'], ['⇥', 'Alinear a la derecha', 'justifyRight'], ['☰', 'Justificar', 'justifyFull'], ['•', 'Lista con viñetas', 'insertUnorderedList'], ['1.', 'Lista numerada', 'insertOrderedList']]
        .forEach(([t, title, cmd]) => btn(t, title, () => exec(cmd)));
    }
    btn('✕', 'Quitar el formato', () => exec('removeFormat'));

    ed.addEventListener('input', emit);
    // Pegar: SIEMPRE texto plano (nada de basura de Word o Google Docs); soltar contenido arrastrado, igual.
    const plain = (e, dt) => { e.preventDefault(); const t = dt ? dt.getData('text/plain') : ''; if (t) { restore(); if (!document.execCommand('insertText', false, t)) ed.append(document.createTextNode(t)); emit(); } };
    ed.addEventListener('paste', (e) => plain(e, e.clipboardData));
    ed.addEventListener('drop', (e) => plain(e, e.dataTransfer));
    setValue(opts.value);
    return { getValue: value, setValue, el: ed, destroy: () => document.removeEventListener('selectionchange', keep) };
  }
  api.mount = mount;
})();
