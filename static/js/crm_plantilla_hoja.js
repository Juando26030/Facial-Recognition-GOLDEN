/* CRM - Hoja LIBRE del diseñador del PDF (26-nov-2026, pedido de Juan David: «armar el PDF como armo los certificados o las escarapelas»).
   Textos (con datos como {{cliente}}), imágenes, rectángulos y líneas que se arrastran y cambian de tamaño sobre la hoja; el recuadro «Contenido» (tabla de productos, totales…)
   también se mueve y se agranda. Medidas internas en PUNTOS (como el PDF, app/crm/quote_free.py); en pantalla se muestran en milímetros.
   La usa static/js/crm_plantilla.js: PlSheet.mount({ get, meta, base, changed, onFlow }). Sin HTML armado a mano ni temporizadores; todo texto con textContent / .value. */
(function () {
  "use strict";
  const MM = 25.4 / 72, PT = 72 / 25.4;
  const SIZES = [6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 40, 48, 60, 72];
  const VAR_LABEL = { numero: "Número", cliente: "Cliente", contacto: "Contacto", titulo: "Asunto", fecha_evento: "Fecha del evento", valida_hasta: "Válida hasta", subtotal: "Subtotal",
    impuestos: "Impuestos", total: "Total", moneda: "Moneda", hoy: "Fecha de hoy", evento: "Evento", ciudad: "Ciudad", emision: "Fecha de emisión", vence: "Vence", estado: "Estado", pagina: "N.º de página" };
  const TYPE_LABEL = { text: "Texto", image: "Imagen", rect: "Rectángulo", line: "Línea" };

  function mount(opts) {
    const X = window.CRMX, { $, el } = X;
    const page = $("pdxPage"), scroll = $("pdxScroll"), propsBox = $("pdxProps");
    let selected = null, zoom = 1, scale = 1, seq = 0, drag = null;
    const L = () => opts.get();
    const meta = () => opts.meta();
    const size = () => meta().page_sizes[L().page] || meta().page_sizes.a4;
    const mm = (pt) => Math.round(pt * MM * 10) / 10;
    const byId = (id) => L().elements.find((e) => e.id === id);
    const fill = (t) => String(t || "").replace(/\{\{\s*([a-z_]+)\s*\}\}/g, (m, k) => (meta().sample && meta().sample[k] != null ? meta().sample[k] : m));
    function newId() { const used = new Set(L().elements.map((e) => e.id)); let i = L().elements.length + 1, id; do { id = "e" + (i++); } while (used.has(id)); return id; }
    function changed() { opts.changed(); }

    /* ------------------------------------------------------------ escala: la hoja cabe a lo ancho; «+» y «−» acercan o alejan */
    function fit() {
      const [pw] = size(), avail = Math.max(240, scroll.clientWidth - 24);
      scale = (avail / pw) * zoom;
    }
    if (window.ResizeObserver) new ResizeObserver(() => { const old = scale; fit(); if (Math.abs(old - scale) > 0.001) paint(); }).observe(scroll);

    /* ------------------------------------------------------------ dibujo de la hoja */
    function place(node, x, y, w, h) { node.style.left = (x * scale) + "px"; node.style.top = (y * scale) + "px"; node.style.width = (w * scale) + "px"; node.style.height = (h * scale) + "px"; }
    function body(e) {
      const n = el("div", "pdx-el pdx-el--" + e.type + (e.id === selected ? " is-selected" : "")); n.dataset.id = e.id;
      n.setAttribute("role", "button"); n.tabIndex = -1; n.setAttribute("aria-label", TYPE_LABEL[e.type] + (e.type === "text" ? ": " + (e.text || "").slice(0, 40) : ""));
      place(n, e.x, e.y, e.w, e.h);
      if (e.type === "text") {
        const t = el("div", "pdx-text", fill(e.text) || "Texto vacío");
        t.style.fontSize = (e.size * scale) + "px"; t.style.lineHeight = String(e.line || 1.25); t.style.fontWeight = e.bold ? "700" : "400"; t.style.fontStyle = e.italic ? "italic" : "normal";
        t.style.textAlign = e.align || "left"; t.style.color = e.color || "#000000"; if (!e.text) t.classList.add("is-empty");
        n.style.height = "auto"; n.style.minHeight = (e.h * scale) + "px"; n.appendChild(t);
      } else if (e.type === "image") {
        if (e.asset) { const img = el("img", "pdx-img"); img.alt = ""; img.draggable = false; img.src = opts.base + "/assets/" + e.asset.split("/").pop(); n.appendChild(img); }
        else n.appendChild(el("span", "pdx-missing", "Falta la imagen"));
      } else if (e.type === "rect") {
        n.style.background = e.fill || "transparent"; n.style.borderRadius = ((e.radius || 0) * scale) + "px";
        n.style.border = e.stroke && e.stroke_w ? Math.max(1, e.stroke_w * scale) + "px solid " + e.stroke : "";
        if (!e.fill && !(e.stroke && e.stroke_w)) n.classList.add("is-ghost");
      } else if (e.type === "line") { n.style.background = e.color || "#000000"; }
      if (e.pages !== "first") n.appendChild(el("span", "pdx-badge", e.pages === "all" ? "Todas" : "2.ª en adelante"));
      if (e.id === selected) { const hd = el("span", "pdx-handle"); hd.dataset.handle = "1"; hd.setAttribute("aria-hidden", "true"); n.appendChild(hd); }
      return n;
    }
    function flowBox() {
      const f = L().flow, n = el("div", "pdx-flow" + (selected === "flow" ? " is-selected" : "")); n.dataset.id = "flow"; n.setAttribute("role", "button"); n.tabIndex = -1;
      n.setAttribute("aria-label", "Recuadro del contenido"); place(n, f.x, f.y, f.w, f.h);
      n.appendChild(el("span", "pdx-flow__title", "Contenido"));
      const list = el("ul", "pdx-flow__list");
      (f.blocks || []).forEach((b) => list.appendChild(el("li", "pdx-flow__item pdx-flow__item--" + b.type, (meta().blocks[b.type] || b.type) + (b.type === "heading" || b.type === "text" ? ": " + (fill(b.text || "").slice(0, 50) || "(vacío)") : ""))));
      if (!(f.blocks || []).length) list.appendChild(el("li", "pdx-flow__item", "Vacío: agrega la tabla de productos, los totales… en «2. Contenido»."));
      n.appendChild(list); n.appendChild(el("span", "pdx-flow__hint", "Si no cabe, sigue en la página siguiente."));
      if (selected === "flow") { const hd = el("span", "pdx-handle"); hd.dataset.handle = "1"; hd.setAttribute("aria-hidden", "true"); n.appendChild(hd); }
      return n;
    }
    function paint() {
      if (!L()) return; fit();
      const [pw, ph] = size(); page.style.width = (pw * scale) + "px"; page.style.height = (ph * scale) + "px";
      page.replaceChildren(); L().elements.forEach((e) => page.appendChild(body(e))); page.appendChild(flowBox());
      $("pdxZoom").textContent = Math.round(zoom * 100) + " %";
      paintProps();
    }
    function select(id) { selected = id; paint(); if (id === "flow" && opts.onFlow) opts.onFlow(); }

    /* ------------------------------------------------------------ arrastrar y cambiar de tamaño (mouse, lápiz o dedo) */
    page.addEventListener("pointerdown", (ev) => {
      const node = ev.target.closest(".pdx-el, .pdx-flow");
      if (!node) { if (selected) select(null); return; }
      const id = node.dataset.id, item = id === "flow" ? L().flow : byId(id); if (!item) return;
      if (selected !== id) select(id);
      ev.preventDefault(); page.focus({ preventScroll: true });
      drag = { id, item, resize: !!ev.target.closest("[data-handle]"), sx: ev.clientX, sy: ev.clientY, x: item.x, y: item.y, w: item.w, h: item.h, moved: false };
      page.setPointerCapture(ev.pointerId);
    });
    page.addEventListener("pointermove", (ev) => {
      if (!drag) return;
      const dx = (ev.clientX - drag.sx) / scale, dy = (ev.clientY - drag.sy) / scale, it = drag.item, [pw, ph] = size();
      if (Math.abs(dx) + Math.abs(dy) > 0.5) drag.moved = true;
      if (drag.resize) {
        const minW = drag.id === "flow" ? 60 : 4, minH = drag.id === "flow" ? 60 : (it.type === "line" ? 0.3 : 4);
        it.w = Math.round(Math.max(minW, drag.w + dx)); it.h = Math.max(minH, Math.round((drag.h + dy) * 10) / 10);
        if (drag.id === "flow") { it.w = Math.min(it.w, pw - it.x); it.h = Math.min(it.h, ph - it.y); }
      } else {
        it.x = Math.round(drag.x + dx); it.y = Math.round(drag.y + dy);
        if (drag.id === "flow") { it.x = Math.max(0, Math.min(pw - it.w, it.x)); it.y = Math.max(0, Math.min(ph - it.h, it.y)); }
      }
      const node = page.querySelector('[data-id="' + drag.id + '"]');
      if (node) { node.style.left = (it.x * scale) + "px"; node.style.top = (it.y * scale) + "px"; node.style.width = (it.w * scale) + "px"; if (!(it.type === "text")) node.style.height = (it.h * scale) + "px"; else node.style.minHeight = (it.h * scale) + "px"; }
      syncGeom();
    });
    function endDrag() { if (!drag) return; const moved = drag.moved; drag = null; if (moved) { changed(); paint(); } }
    page.addEventListener("pointerup", endDrag); page.addEventListener("pointercancel", endDrag);
    page.addEventListener("dblclick", (ev) => { const n = ev.target.closest(".pdx-el--text"); if (n) { const t = propsBox.querySelector("textarea"); if (t) t.focus(); } });
    page.addEventListener("keydown", (ev) => {
      if (!selected || ev.target !== page) return;
      const it = selected === "flow" ? L().flow : byId(selected); if (!it) return;
      const step = ev.shiftKey ? 10 : 1, k = ev.key;
      if (k === "ArrowLeft") it.x -= step; else if (k === "ArrowRight") it.x += step; else if (k === "ArrowUp") it.y -= step; else if (k === "ArrowDown") it.y += step;
      else if ((k === "Delete" || k === "Backspace") && selected !== "flow") { remove(selected); ev.preventDefault(); return; }
      else if (k === "Escape") { select(null); return; } else return;
      ev.preventDefault(); changed(); paint();
    });

    /* ------------------------------------------------------------ agregar */
    function add(e) {
      if (L().elements.length >= meta().limits.elements) { showToast("Una hoja admite hasta " + meta().limits.elements + " elementos.", "error"); return null; }
      const [pw] = size(), n = L().elements.length % 8;
      const base = { id: newId(), pages: "first", x: Math.round(pw / 2 - (e.w || 160) / 2 + n * 8), y: 60 + n * 14 };
      const item = Object.assign(base, e); L().elements.push(item); changed(); select(item.id); return item;
    }
    const addText = (text) => add({ type: "text", w: 200, h: 18, text: text || "Escribe aquí", size: 11, bold: false, italic: false, align: "left", color: "#1b1f3b", line: 1.25 });
    $("pdxAddText").addEventListener("click", () => addText());
    $("pdxAddVar").addEventListener("change", (ev) => { const v = ev.target.value; if (!v) return; addText((VAR_LABEL[v] || v) + ": {{" + v + "}}"); ev.target.value = ""; });
    $("pdxAddRect").addEventListener("click", () => add({ type: "rect", w: 200, h: 80, fill: "#f2efe6", stroke: "", stroke_w: 0, radius: 6 }));
    $("pdxAddLine").addEventListener("click", () => add({ type: "line", w: 200, h: 1.5, color: "#b8862b", vertical: false }));
    $("pdxAddImage").addEventListener("change", async (ev) => {
      const f = ev.target.files[0]; ev.target.value = ""; if (!f) return;
      try {
        const d = await upload(f); if (d.kind === "pdf") throw new Error("Ese archivo es un PDF: en la hoja van imágenes PNG o JPG (un PDF se inserta en «2. Contenido»).");
        const w = 160, h = d.width && d.height ? Math.round(w * d.height / d.width) : 100; add({ type: "image", w, h, asset: d.key });
      } catch (e) { showToast(e.message, "error"); }
    });
    async function upload(file) {
      const fd = new FormData(); fd.append("file", file);
      const r = await fetch(opts.base + "/assets", { method: "POST", body: fd }), data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "No se pudo subir el archivo.");
      return data;
    }
    function remove(id) { const i = L().elements.findIndex((e) => e.id === id); if (i < 0) return; L().elements.splice(i, 1); selected = null; changed(); paint(); }
    function reorder(id, to) {
      const els = L().elements, i = els.findIndex((e) => e.id === id); if (i < 0) return;
      const [e] = els.splice(i, 1); els.splice(to === "front" ? els.length : to === "back" ? 0 : Math.max(0, Math.min(els.length, i + to)), 0, e); changed(); paint();
    }

    /* ------------------------------------------------------------ hoja y zoom */
    $("pdxPageSize").addEventListener("change", (ev) => { L().page = ev.target.value; changed(); paint(); });
    $("pdxZoomIn").addEventListener("click", () => { zoom = Math.min(3, zoom + 0.25); paint(); });
    $("pdxZoomOut").addEventListener("click", () => { zoom = Math.max(0.5, zoom - 0.25); paint(); });
    $("pdxZoomFit").addEventListener("click", () => { zoom = 1; paint(); });

    /* ------------------------------------------------------------ propiedades */
    function field(label, control, hint) {
      const w = el("div", "gw-field"), id = "pdx" + (seq++), l = el("label", "gw-label", label); l.htmlFor = id; control.id = id; w.appendChild(l); w.appendChild(control);
      if (hint) w.appendChild(el("p", "gw-hint", hint)); return w;
    }
    function num(value, step, onSet, min) {
      const i = el("input", "gw-input"); i.type = "number"; i.step = String(step); i.value = String(value); if (min != null) i.min = String(min);
      i.addEventListener("change", () => { const v = Number(i.value); if (Number.isFinite(v)) { onSet(v); changed(); paint(); } }); return i;
    }
    function colorIn(value, onSet) { const i = el("input", "pdx-color"); i.type = "color"; i.value = value || "#000000"; i.addEventListener("input", () => { onSet(i.value); changed(); paint(); }); return i; }
    function choice(pairs, cur, onSet) { const s = el("select", "gw-select"); pairs.forEach(([v, l]) => { const o = el("option", null, l); o.value = String(v); s.appendChild(o); }); s.value = String(cur); s.addEventListener("change", () => { onSet(s.value); changed(); paint(); }); return s; }
    function check(label, on, onSet) { const lab = el("label", "gw-check"), c = el("input"); c.type = "checkbox"; c.checked = !!on; c.addEventListener("change", () => { onSet(c.checked); changed(); paint(); }); lab.appendChild(c); lab.appendChild(document.createTextNode(" " + label)); return lab; }
    function btn(label, act, extra) { const b = el("button", "gw-btn gw-btn--secondary gw-btn--sm" + (extra ? " " + extra : ""), label); b.type = "button"; b.dataset.act = act; return b; }
    function geom(it, isFlow) {
      const g = el("div", "pdx-grid");
      g.appendChild(field("Desde la izquierda (mm)", num(mm(it.x), 0.5, (v) => { it.x = v * PT; })));
      g.appendChild(field("Desde arriba (mm)", num(mm(it.y), 0.5, (v) => { it.y = v * PT; })));
      g.appendChild(field("Ancho (mm)", num(mm(it.w), 0.5, (v) => { it.w = Math.max(isFlow ? 60 : 1, v * PT); }, 1)));
      g.appendChild(field(it.type === "line" && !it.vertical ? "Grosor (mm)" : "Alto (mm)", num(mm(it.h), 0.1, (v) => { it.h = Math.max(isFlow ? 60 : 0.3, v * PT); }, 0.1)));
      g.dataset.geom = "1"; return g;
    }
    function syncGeom() {
      const g = propsBox.querySelector("[data-geom]"), it = selected === "flow" ? L().flow : byId(selected); if (!g || !it) return;
      const ins = g.querySelectorAll("input"); [it.x, it.y, it.w, it.h].forEach((v, i) => { if (ins[i] && document.activeElement !== ins[i]) ins[i].value = String(mm(v)); });
    }
    function varChips(area, it) {
      const box = el("div", "pl-vars"); box.appendChild(el("span", "gw-hint", "Insertar un dato:"));
      (meta().variables || []).forEach((v) => {
        const c = el("button", "gw-btn gw-btn--secondary gw-btn--sm", VAR_LABEL[v] || v); c.type = "button"; c.title = "{{" + v + "}}";
        c.addEventListener("click", () => { const s = area.selectionStart == null ? area.value.length : area.selectionStart, e = area.selectionEnd == null ? s : area.selectionEnd, t = "{{" + v + "}}";
          area.value = area.value.slice(0, s) + t + area.value.slice(e); area.focus(); area.selectionStart = area.selectionEnd = s + t.length; it.text = area.value; changed(); paint(); });
        box.appendChild(c);
      }); return box;
    }
    function layers() {
      const box = el("div", "gw-stack pdx-layers"); box.appendChild(el("h3", "pdx-props__title", "Capas de la hoja"));
      box.appendChild(el("p", "gw-hint", "Lo de abajo de la lista queda al frente. Toca uno para elegirlo (sirve para lo que está tapado)."));
      const ul = el("ul", "pdx-layers__list");
      const item = (id, label) => { const li = el("li"), b = el("button", "pdx-layer" + (selected === id ? " is-selected" : ""), label); b.type = "button"; b.dataset.pick = id; li.appendChild(b); ul.appendChild(li); };
      L().elements.forEach((e) => item(e.id, TYPE_LABEL[e.type] + (e.type === "text" ? " · " + (e.text || "").replace(/\s+/g, " ").slice(0, 30) : "")));
      item("flow", "Contenido (tabla, totales…)"); box.appendChild(ul); return box;
    }
    function paintProps() {
      propsBox.replaceChildren();
      const head = (t) => propsBox.appendChild(el("h3", "pdx-props__title", t));
      if (!selected) {
        head("Elige algo de la hoja");
        propsBox.appendChild(el("p", "gw-hint", "Agrega textos, datos, imágenes, rectángulos o líneas con los botones de arriba. Arrástralos para moverlos; la esquina de abajo a la derecha cambia el tamaño. Con el teclado: flechas para mover (con Mayús, de a 10) y Suprimir para quitar."));
      } else if (selected === "flow") {
        const f = L().flow, nx = L().next;
        head("Contenido de la " + (opts.kindLabel || "cotización"));
        propsBox.appendChild(el("p", "gw-hint", "Aquí van los datos, la tabla de productos, los totales y las condiciones (los ordenas en «2. Contenido», abajo). Si no caben, siguen en la página siguiente."));
        propsBox.appendChild(geom(f, true));
        const g = el("div", "pdx-grid");
        g.appendChild(field("Páginas siguientes: margen de arriba (mm)", num(mm(nx.top), 1, (v) => { nx.top = Math.max(0, v * PT); }, 0)));
        g.appendChild(field("Páginas siguientes: margen de abajo (mm)", num(mm(nx.bottom), 1, (v) => { nx.bottom = Math.max(0, v * PT); }, 0)));
        propsBox.appendChild(g);
        propsBox.appendChild(el("p", "gw-hint", "Deja espacio para lo que se repite en todas las páginas (encabezado o pie)."));
      } else {
        const it = byId(selected); if (!it) { selected = null; paintProps(); return; }
        head(TYPE_LABEL[it.type]);
        if (it.type === "text") {
          const t = el("textarea", "gw-textarea"); t.rows = 4; t.maxLength = 5000; t.value = it.text || ""; t.addEventListener("input", () => { it.text = t.value; changed(); const n = page.querySelector('[data-id="' + it.id + '"] .pdx-text'); if (n) { n.textContent = fill(it.text) || "Texto vacío"; n.classList.toggle("is-empty", !it.text); } });
          propsBox.appendChild(field("Texto", t, "Los datos entre llaves, como {{cliente}}, se cambian por los de cada " + (opts.kindLabel || "cotización") + "."));
          propsBox.appendChild(varChips(t, it));
          const g = el("div", "pdx-grid");
          g.appendChild(field("Tamaño de la letra", choice(SIZES.map((s) => [s, s + " pt"]).concat(SIZES.includes(it.size) ? [] : [[it.size, it.size + " pt"]]), it.size, (v) => { it.size = Number(v); })));
          g.appendChild(field("Alineación", choice([["left", "Izquierda"], ["center", "Centro"], ["right", "Derecha"]], it.align || "left", (v) => { it.align = v; })));
          g.appendChild(field("Color", colorIn(it.color, (v) => { it.color = v; })));
          g.appendChild(field("Interlineado", choice([[1, "Junto"], [1.25, "Normal"], [1.5, "Amplio"], [2, "Doble"]], it.line || 1.25, (v) => { it.line = Number(v); })));
          propsBox.appendChild(g);
          const c = el("div", "pdx-checks"); c.appendChild(check("Negrita", it.bold, (v) => { it.bold = v; })); c.appendChild(check("Cursiva", it.italic, (v) => { it.italic = v; })); propsBox.appendChild(c);
        } else if (it.type === "image") {
          const f = el("input"); f.type = "file"; f.accept = "image/png,image/jpeg,.png,.jpg,.jpeg";
          f.addEventListener("change", async () => { const file = f.files[0]; if (!file) return; try { const d = await upload(file); if (d.kind === "pdf") throw new Error("Elige una imagen PNG o JPG."); it.asset = d.key; if (d.width && d.height) it.h = Math.round(it.w * d.height / d.width); changed(); paint(); } catch (e) { showToast(e.message, "error"); f.value = ""; } });
          propsBox.appendChild(field("Cambiar la imagen (PNG o JPG, hasta " + meta().limits.image_mb + " MB)", f, "La imagen se ajusta dentro del recuadro sin deformarse. Para un fondo de hoja completa, agrándala a toda la hoja y mándala atrás."));
          propsBox.appendChild(btn("Ajustar el alto a la imagen", "ratio"));
        } else if (it.type === "rect") {
          const g = el("div", "pdx-grid");
          g.appendChild(field("Relleno", colorIn(it.fill || "#ffffff", (v) => { it.fill = v; })));
          g.appendChild(field("Borde", colorIn(it.stroke || "#000000", (v) => { it.stroke = v; if (!it.stroke_w) it.stroke_w = 1; })));
          g.appendChild(field("Grosor del borde (pt)", num(it.stroke_w || 0, 0.5, (v) => { it.stroke_w = Math.max(0, Math.min(20, v)); }, 0)));
          g.appendChild(field("Esquinas redondeadas (pt)", num(it.radius || 0, 1, (v) => { it.radius = Math.max(0, Math.min(100, v)); }, 0)));
          propsBox.appendChild(g); propsBox.appendChild(check("Sin relleno (solo el borde)", !it.fill, (v) => { it.fill = v ? "" : "#ffffff"; }));
        } else if (it.type === "line") {
          const g = el("div", "pdx-grid");
          g.appendChild(field("Color", colorIn(it.color, (v) => { it.color = v; })));
          g.appendChild(field("Dirección", choice([["h", "Horizontal"], ["v", "Vertical"]], it.vertical ? "v" : "h", (v) => { const vert = v === "v"; if (vert !== !!it.vertical) { const w = it.w; it.w = it.h; it.h = w; } it.vertical = vert; })));
          propsBox.appendChild(g);
        }
        propsBox.appendChild(geom(it, false));
        propsBox.appendChild(field("Sale en", choice(Object.entries(meta().page_rules), it.pages || "first", (v) => { it.pages = v; }), "«Todas las páginas» sirve para un encabezado o un pie que se repite."));
        const tools = el("div", "crm-card-actions pdx-tools");
        [["Centrar en la hoja", "center"], ["Al frente", "front"], ["Atrás", "back"], ["Duplicar", "dup"]].forEach(([l, a]) => tools.appendChild(btn(l, a)));
        tools.appendChild(btn("Quitar", "del", "gw-btn--danger-outline")); propsBox.appendChild(tools);
      }
      propsBox.appendChild(layers());
    }
    propsBox.addEventListener("click", async (ev) => {
      const pick = ev.target.closest("[data-pick]"); if (pick) { select(pick.dataset.pick); return; }
      const b = ev.target.closest("[data-act]"); if (!b) return;
      const it = byId(selected); if (!it) return;
      const act = b.dataset.act, [pw] = size();
      if (act === "center") { it.x = Math.round((pw - it.w) / 2); changed(); paint(); }
      else if (act === "front" || act === "back") reorder(it.id, act);
      else if (act === "dup") { const c = JSON.parse(JSON.stringify(it)); c.id = newId(); c.x += 10; c.y += 10; add(c); }          // add() elige la copia
      else if (act === "del") { if (await showConfirm("¿Quitar este elemento de la hoja?", { confirmLabel: "Sí, quitar", variant: "warning" })) remove(it.id); }
      else if (act === "ratio") { const img = page.querySelector('[data-id="' + it.id + '"] img'); if (img && img.naturalWidth) { it.h = Math.round(it.w * img.naturalHeight / img.naturalWidth); changed(); paint(); } }
    });

    return { paint, select, refresh: () => { const s = $("pdxPageSize"); s.value = L().page; if (selected && selected !== "flow" && !byId(selected)) selected = null; paint(); } };
  }

  window.PlSheet = { mount };
})();
