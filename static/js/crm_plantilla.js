/* CRM - Diseñador del PDF de cotización (solo admin). El diseño se guarda con la barra única de la pantalla (GWParams, bloque «plantilla»). Bloques que se agregan (clic o arrastrando), se ordenan (flechas o arrastrando) y se ajustan; la vista previa es el PDF REAL que arma el servidor.
   Sin temporizadores propios (la espera de la vista previa usa CRMX.debounce de crm_live.js). Todo texto de personas con textContent / .value. */
(function () {
  "use strict";
  const X = window.CRMX, root = document.getElementById("plRoot");
  if (!X || !root || !X.debounce) return;
  const { $, el, api, qs, busy, stateBlock } = X;
  const TID = Number(root.dataset.templateId);
  const BASE = "/api/crm/doc-templates/" + TID;
  const DESC = {
    logo: "Tu logo, arriba o donde quieras.", image: "Una foto o imagen (portada, firma, sello).", heading: "Un título grande.", text: "Un párrafo; puede llevar datos como el cliente o el total.",
    fields: "Cliente, atención, asunto y fechas.", table: "Los productos de la cotización, con foto si quieres.", totals: "Subtotal, impuestos y total.", terms: "Las condiciones comerciales de la cotización.",
    line: "Una línea para separar.", spacer: "Un espacio en blanco.", pagebreak: "Empieza una hoja nueva.", pdf: "Inserta las páginas de otro PDF (por ejemplo, tu portafolio) en este punto."
  };
  const ORDER = ["logo", "heading", "text", "fields", "table", "totals", "terms", "image", "pdf", "line", "spacer", "pagebreak"];
  const GRAYS = [[0, "Negro"], [30, "Gris oscuro"], [55, "Gris"]];
  const SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 22, 28];
  const VAR_LABEL = { numero: "Número", cliente: "Cliente", contacto: "Contacto", titulo: "Asunto", fecha_evento: "Fecha del evento", valida_hasta: "Válida hasta", subtotal: "Subtotal", impuestos: "Impuestos", total: "Total", moneda: "Moneda", hoy: "Fecha de hoy" };

  let meta = null, tpl = null, layout = null, selected = null, dirty = false, seq = 0, blobUrl = null, nextId = 1, dragging = null;
  const clone = (o) => JSON.parse(JSON.stringify(o));

  /* ---------------------------------------------------------------- estado
     «dirty» avisa que hay cambios sin guardar; cada cambio refresca la vista previa (con una espera corta para juntar lo que se escribe). */
  function setDirty(on) { dirty = on; if (window.GWParams) { if (on) GWParams.markDirty("plantilla"); else GWParams.markClean("plantilla"); } }
  const refreshSoon = X.debounce(() => preview(), 900);
  function changed() { setDirty(true); refreshSoon(); }
  function newId() { const used = new Set(layout.blocks.map((b) => b.id)); let id; do { id = "b" + (nextId++); } while (used.has(id)); return id; }

  /* ---------------------------------------------------------------- bloques: valores iniciales y resumen */
  function fresh(type) {
    const id = newId();
    switch (type) {
      case "logo": return { id, type, asset: "", width: 140, align: "left" };
      case "image": return { id, type, asset: "", width: 300, align: "center" };
      case "heading": return { id, type, text: "Título", size: 16, align: "left", bold: true, gray: 0 };
      case "text": return { id, type, text: "", size: 10, align: "left", bold: false, gray: 0 };
      case "fields": return { id, type, items: ["cliente", "contacto", "titulo", "fecha_evento", "valida_hasta"] };
      case "table": return { id, type, columns: ["pos", "nombre", "cantidad", "precio", "descuento", "total"], photo_size: 56 };
      case "terms": return { id, type, title: "Condiciones comerciales" };
      case "spacer": return { id, type, height: 16 };
      case "pdf": return { id, type, asset: "", pages: "", name: "" };
      default: return { id, type };
    }
  }
  function summary(b) {
    const cut = (s) => (s.length > 60 ? s.slice(0, 57) + "…" : s);
    switch (b.type) {
      case "heading": case "text": return b.text ? cut(b.text.replace(/\s+/g, " ")) : "(vacío)";
      case "logo": case "image": return b.asset ? "Imagen cargada" : "Falta subir la imagen";
      case "fields": return (b.items || []).map((k) => meta.fields[k]).join(", ") || "(sin datos)";
      case "table": return (b.columns || []).map((k) => meta.columns[k]).join(" · ");
      case "terms": return b.title || "";
      case "spacer": return (b.height || 0) + " puntos";
      case "pdf": return b.asset ? (b.name || "PDF cargado") + (b.pages ? " · páginas " + b.pages : " · todas las páginas") : "Falta subir el PDF";
      default: return "";
    }
  }

  /* ---------------------------------------------------------------- paleta */
  function paintPalette() {
    const ul = $("plPalette"); ul.replaceChildren();
    ORDER.filter((t) => meta.blocks[t]).forEach((t) => {
      const li = el("li", "pl-pal"), b = el("button", "pl-pal__btn"); b.type = "button"; b.draggable = true; b.dataset.add = t;
      b.appendChild(el("span", "pl-pal__name", meta.blocks[t])); b.appendChild(el("span", "pl-pal__desc", DESC[t] || "")); li.appendChild(b); ul.appendChild(li);
    });
  }
  function addBlock(type, at) {
    if (layout.blocks.length >= meta.limits.blocks) { showToast("Un diseño admite hasta " + meta.limits.blocks + " bloques.", "error"); return; }
    const b = fresh(type), i = at == null ? (selected ? layout.blocks.findIndex((x) => x.id === selected) + 1 || layout.blocks.length : layout.blocks.length) : at;
    layout.blocks.splice(i, 0, b); selected = b.id; paintBlocks(); changed();
    const card = $("plBlocks").querySelector('[data-id="' + b.id + '"]'); if (card) card.scrollIntoView({ block: "nearest" });
  }

  /* ---------------------------------------------------------------- lista de bloques */
  function paintBlocks() {
    const ol = $("plBlocks"); ol.replaceChildren();
    if (!layout.blocks.length) ol.appendChild(el("li", "gw-hint pl-empty", "Todavía no hay bloques. Agrega el primero desde la izquierda."));
    layout.blocks.forEach((b, i) => ol.appendChild(card(b, i)));
  }
  function card(b, i) {
    const li = el("li", "pl-block" + (b.id === selected ? " is-selected" : "")); li.dataset.id = b.id; li.draggable = true;
    const head = el("div", "pl-block__head"), grip = el("span", "pl-block__grip", "⠿"); grip.setAttribute("aria-hidden", "true");
    const main = el("button", "pl-block__main"); main.type = "button"; main.dataset.select = b.id; main.setAttribute("aria-expanded", b.id === selected ? "true" : "false");
    main.appendChild(el("span", "pl-block__type", meta.blocks[b.type])); main.appendChild(el("span", "pl-block__sum", summary(b)));
    const tools = el("div", "pl-block__tools");
    [["up", "↑", "Subir", i === 0], ["down", "↓", "Bajar", i === layout.blocks.length - 1], ["dup", "Duplicar", "Duplicar", false], ["del", "Quitar", "Quitar", false]].forEach(([act, label, aria, off]) => {
      const t = el("button", "gw-btn gw-btn--secondary gw-btn--sm", label); t.type = "button"; t.dataset.act = act; t.dataset.id = b.id; t.disabled = off; t.setAttribute("aria-label", aria + " el bloque " + meta.blocks[b.type]); tools.appendChild(t);
    });
    head.appendChild(grip); head.appendChild(main); head.appendChild(tools); li.appendChild(head);
    if (b.id === selected) li.appendChild(props(b));
    return li;
  }

  /* ---------------------------------------------------------------- propiedades de cada bloque */
  function row(label, control, hint) {
    const w = el("div", "gw-field"), id = "pp" + (seq++); const l = el("label", "gw-label", label); l.htmlFor = id; control.id = id; w.appendChild(l); w.appendChild(control);
    if (hint) w.appendChild(el("p", "gw-hint", hint)); return w;
  }
  function numSelect(values, cur, onChange) {
    const s = el("select", "gw-select"); values.forEach((v) => { const o = el("option", null, String(v)); o.value = String(v); s.appendChild(o); });
    if (!values.includes(Number(cur))) { const o = el("option", null, String(cur)); o.value = String(cur); s.appendChild(o); } s.value = String(cur); s.addEventListener("change", () => onChange(Number(s.value))); return s;
  }
  function alignSelect(cur, onChange) {
    const s = el("select", "gw-select"); [["left", "A la izquierda"], ["center", "Centrado"], ["right", "A la derecha"]].forEach(([v, l]) => { const o = el("option", null, l); o.value = v; s.appendChild(o); }); s.value = cur || "left"; s.addEventListener("change", () => onChange(s.value)); return s;
  }
  function checkRow(label, on, onChange) {
    const lab = el("label", "gw-check"), c = el("input"); c.type = "checkbox"; c.checked = on; c.addEventListener("change", () => onChange(c.checked)); lab.appendChild(c); lab.appendChild(document.createTextNode(" ")); lab.appendChild(el("span", "gw-choice__text", label)); return lab;
  }
  function varChips(area, b) {
    const box = el("div", "pl-vars"); box.appendChild(el("span", "gw-hint", "Insertar un dato del cliente:"));
    meta.variables.forEach((v) => {
      const c = el("button", "gw-btn gw-btn--secondary gw-btn--sm", VAR_LABEL[v] || v); c.type = "button"; c.title = "{{" + v + "}}";
      c.addEventListener("click", () => { const s = area.selectionStart == null ? area.value.length : area.selectionStart, e = area.selectionEnd == null ? s : area.selectionEnd, t = "{{" + v + "}}";
        area.value = area.value.slice(0, s) + t + area.value.slice(e); area.focus(); area.selectionStart = area.selectionEnd = s + t.length; b.text = area.value; syncSummary(b); changed(); });
      box.appendChild(c);
    }); return box;
  }
  function syncSummary(b) { const li = $("plBlocks").querySelector('[data-id="' + b.id + '"] .pl-block__sum'); if (li) li.textContent = summary(b); }
  function uploadRow(b, kind) {
    const w = el("div", "gw-field"), file = el("input"); file.type = "file"; file.accept = kind === "pdf" ? "application/pdf,.pdf" : "image/png,image/jpeg,.png,.jpg,.jpeg"; file.id = "pp" + (seq++);
    const l = el("label", "gw-label", kind === "pdf" ? "Archivo PDF" : "Imagen (PNG o JPG)"); l.htmlFor = file.id; w.appendChild(l);
    if (b.asset && kind !== "pdf") { const img = el("img", "pl-thumb"); img.alt = "Imagen del bloque"; img.src = BASE + "/assets/" + b.asset.split("/").pop(); w.appendChild(img); }
    w.appendChild(file); w.appendChild(el("p", "gw-hint", kind === "pdf" ? "Hasta " + meta.limits.pdf_mb + " MB y " + meta.limits.pdf_pages + " páginas." : "Hasta " + meta.limits.image_mb + " MB."));
    file.addEventListener("change", async () => {
      const f = file.files[0]; if (!f) return; const fd = new FormData(); fd.append("file", f);
      try {
        const r = await fetch(BASE + "/assets", { method: "POST", body: fd }), data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "No se pudo subir el archivo.");
        if ((kind === "pdf") !== (data.kind === "pdf")) throw new Error(kind === "pdf" ? "Ese archivo no es un PDF." : "Ese archivo es un PDF: elige una imagen PNG o JPG.");
        b.asset = data.key; if (kind === "pdf") { b.name = data.name || ""; b.pages_total = data.pages; }
        paintBlocks(); changed(); showToast("Archivo cargado.", "success");
      } catch (e) { showToast(e.message, "error"); file.value = ""; }
    });
    return w;
  }
  function props(b) {
    const box = el("div", "pl-props gw-stack");
    const set = (k) => (v) => { b[k] = v; syncSummary(b); changed(); };
    if (b.type === "heading" || b.type === "text") {
      const t = el("textarea", "gw-textarea"); t.rows = b.type === "heading" ? 2 : 5; t.maxLength = 5000; t.value = b.text || ""; t.addEventListener("input", () => { b.text = t.value; syncSummary(b); changed(); });
      box.appendChild(row("Texto", t)); box.appendChild(varChips(t, b));
      const line = el("div", "pl-props__line");
      line.appendChild(row("Tamaño", numSelect(SIZES, b.size, set("size")))); line.appendChild(row("Alineación", alignSelect(b.align, set("align"))));
      const g = el("select", "gw-select"); GRAYS.forEach(([v, l]) => { const o = el("option", null, l); o.value = String(v); g.appendChild(o); }); g.value = String(b.gray || 0); g.addEventListener("change", () => set("gray")(Number(g.value)));
      line.appendChild(row("Color", g)); box.appendChild(line); box.appendChild(checkRow("En negrita", !!b.bold, set("bold")));
    } else if (b.type === "logo" || b.type === "image") {
      box.appendChild(uploadRow(b, "image"));
      const w = el("input"); w.type = "range"; w.min = "40"; w.max = "515"; w.step = "5"; w.value = String(b.width || 140); w.addEventListener("input", () => set("width")(Number(w.value)));
      box.appendChild(row("Tamaño (ancho)", w, "De pequeño a toda la hoja.")); box.appendChild(row("Alineación", alignSelect(b.align, set("align"))));
    } else if (b.type === "fields") {
      box.appendChild(el("p", "gw-hint", "Marca qué datos salen (los que estén vacíos no se muestran)."));
      Object.keys(meta.fields).forEach((k) => box.appendChild(checkRow(meta.fields[k], (b.items || []).includes(k), (on) => { const cur = (b.items || []).filter((x) => x !== k); if (on) cur.push(k); b.items = Object.keys(meta.fields).filter((x) => cur.includes(x)); syncSummary(b); changed(); })));
    } else if (b.type === "table") {
      box.appendChild(el("p", "gw-hint", "Marca las columnas. La descripción siempre sale. «Foto» usa la foto que subas a cada producto en Productos y servicios."));
      Object.keys(meta.columns).forEach((k) => { const lab = checkRow(meta.columns[k], (b.columns || []).includes(k), (on) => { const cur = (b.columns || []).filter((x) => x !== k); if (on) cur.push(k); b.columns = Object.keys(meta.columns).filter((x) => cur.includes(x)); syncSummary(b); changed(); }); if (k === "nombre") lab.querySelector("input").disabled = true; box.appendChild(lab); });
      box.appendChild(row("Tamaño de la foto", numSelect([40, 56, 80, 110], b.photo_size || 56, set("photo_size"))));
    } else if (b.type === "terms") {
      const t = el("input", "gw-input"); t.type = "text"; t.maxLength = 120; t.value = b.title || ""; t.addEventListener("input", () => set("title")(t.value)); box.appendChild(row("Título", t, "El texto sale de la cotización (lo eliges al cotizar)."));
    } else if (b.type === "spacer") {
      box.appendChild(row("Alto del espacio", numSelect([4, 8, 12, 16, 24, 32, 48, 64, 96], b.height || 12, set("height"))));
    } else if (b.type === "pdf") {
      box.appendChild(uploadRow(b, "pdf"));
      const p = el("input", "gw-input"); p.type = "text"; p.maxLength = 40; p.placeholder = "Todas"; p.value = b.pages || ""; p.addEventListener("input", () => set("pages")(p.value.trim()));
      box.appendChild(row("Páginas a insertar", p, "Déjalo vacío para todas, o escribe 1-3 o 1,3,5. Las páginas del PDF aparecen en esta posición del documento."));
    } else { box.appendChild(el("p", "gw-hint", "Este bloque no tiene opciones.")); }
    return box;
  }

  /* ---------------------------------------------------------------- mover, duplicar, quitar */
  function move(id, to) {
    const from = layout.blocks.findIndex((b) => b.id === id); if (from < 0) return; const [b] = layout.blocks.splice(from, 1);
    layout.blocks.splice(Math.max(0, Math.min(to, layout.blocks.length)), 0, b); paintBlocks(); changed();
  }
  $("plBlocks").addEventListener("click", async (e) => {
    const sel = e.target.closest("[data-select]"), act = e.target.closest("[data-act]");
    if (sel) { selected = selected === sel.dataset.select ? null : sel.dataset.select; paintBlocks(); return; }
    if (!act || act.disabled) return;
    const i = layout.blocks.findIndex((b) => b.id === act.dataset.id); if (i < 0) return;
    if (act.dataset.act === "up") move(act.dataset.id, i - 1);
    else if (act.dataset.act === "down") move(act.dataset.id, i + 1);
    else if (act.dataset.act === "dup") { if (layout.blocks.length >= meta.limits.blocks) { showToast("Un diseño admite hasta " + meta.limits.blocks + " bloques.", "error"); return; } const c = clone(layout.blocks[i]); c.id = newId(); layout.blocks.splice(i + 1, 0, c); selected = c.id; paintBlocks(); changed(); }
    else if (act.dataset.act === "del") { if (!(await showConfirm("¿Quitar este bloque del diseño?", { confirmLabel: "Sí, quitar" }))) return; layout.blocks.splice(i, 1); if (selected === act.dataset.id) selected = null; paintBlocks(); changed(); }
  });
  $("plPalette").addEventListener("click", (e) => { const b = e.target.closest("[data-add]"); if (b) addBlock(b.dataset.add); });

  /* ---------------------------------------------------------------- arrastrar y soltar (el teclado y el celular usan las flechas y «agregar») */
  function dropIndex(list, y) {
    const items = Array.from(list.querySelectorAll(".pl-block:not(.is-dragging)"));
    for (let i = 0; i < items.length; i++) { const r = items[i].getBoundingClientRect(); if (y < r.top + r.height / 2) return i; }
    return items.length;
  }
  function clearMark() { $("plBlocks").classList.remove("is-over"); $("plBlocks").querySelectorAll(".pl-block").forEach((n) => n.classList.remove("pl-before", "pl-after")); }
  function mark(list, idx) {
    clearMark(); list.classList.add("is-over"); const items = Array.from(list.querySelectorAll(".pl-block:not(.is-dragging)"));
    if (!items.length) return; if (idx >= items.length) items[items.length - 1].classList.add("pl-after"); else items[idx].classList.add("pl-before");
  }
  document.addEventListener("dragstart", (e) => {
    const pal = e.target.closest && e.target.closest("[data-add]"), blk = e.target.closest && e.target.closest(".pl-block");
    if (pal) dragging = { kind: "new", type: pal.dataset.add }; else if (blk && !e.target.closest(".pl-props")) { dragging = { kind: "move", id: blk.dataset.id }; blk.classList.add("is-dragging"); } else return;
    if (e.dataTransfer) { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", "bloque"); }
  });
  document.addEventListener("dragend", () => { dragging = null; clearMark(); $("plBlocks").querySelectorAll(".is-dragging").forEach((n) => n.classList.remove("is-dragging")); });
  $("plBlocks").addEventListener("dragover", (e) => { if (!dragging) return; e.preventDefault(); mark($("plBlocks"), dropIndex($("plBlocks"), e.clientY)); });
  $("plBlocks").addEventListener("dragleave", (e) => { if (!$("plBlocks").contains(e.relatedTarget)) clearMark(); });
  $("plBlocks").addEventListener("drop", (e) => {
    if (!dragging) return; e.preventDefault(); const idx = dropIndex($("plBlocks"), e.clientY), d = dragging; dragging = null; clearMark();
    if (d.kind === "new") addBlock(d.type, idx); else move(d.id, idx);
  });

  /* ---------------------------------------------------------------- vista previa (el PDF real) */
  async function preview() {
    if (!layout) return; const mine = ++seq, state = $("plPrevState"), qid = $("plQuote").value; state.textContent = "Actualizando…";
    try {
      const r = await fetch(BASE + "/preview", { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/pdf" }, body: JSON.stringify({ layout, quote_id: qid ? Number(qid) : null }) });
      if (mine !== seq) return;
      if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(typeof d.detail === "string" ? d.detail : "No se pudo armar la vista previa."); }
      const url = URL.createObjectURL(await r.blob()); if (blobUrl) URL.revokeObjectURL(blobUrl); blobUrl = url; $("plFrame").src = url + "#toolbar=0&navpanes=0"; state.textContent = "Listo.";
    } catch (e) { if (mine === seq) state.textContent = e.message; }
  }
  $("plRefresh").addEventListener("click", preview);
  $("plQuote").addEventListener("change", preview);

  /* ---------------------------------------------------------------- guardar y empezar */
  /* Lo guarda la barra única. Lanza Error(mensaje) si falla. */
  async function saveLayout() {
    const saved = await api("PUT", BASE, { layout });
    tpl = saved; layout = clone(saved.layout); dirty = false; paintBlocks(); preview();
  }
  if (window.GWParams) GWParams.register({ key: "plantilla", label: "Diseño del PDF", order: 10, save: saveLayout });
  async function start(name) { try { const s = await api("GET", "/api/crm/doc-layout/starter" + qs({ name })); layout = s.layout; nextId = layout.blocks.length + 1; selected = null; show(); setDirty(true); preview(); } catch (x) { showToast(x.message, "error"); } }
  $("plStart").addEventListener("click", (e) => { const b = e.target.closest("[data-start]"); if (b) start(b.dataset.start); });
  $("plCopy").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    const from = Number($("plCopyFrom").value); if (!from) return;
    try { const r = await api("POST", BASE + "/copy-layout", { from_id: from }); layout = r.layout; nextId = layout.blocks.length + 1; selected = null; show(); setDirty(true); preview(); showToast("Diseño copiado. Revísalo y pulsa «Guardar cambios».", "success"); }
    catch (x) { showToast(x.message, "error"); }
  }));
  function fillCopy(list) {
    const s = $("plCopyFrom"); s.replaceChildren(); const others = (list || []).filter((t) => t.id !== TID && t.kind === "quote" && t.has_layout);
    others.forEach((t) => { const o = el("option", null, t.name); o.value = String(t.id); s.appendChild(o); }); $("plCopyWrap").hidden = !others.length;
  }
  $("plClassic").addEventListener("click", async () => {
    if (!(await showConfirm("Se reemplaza el diseño que ves por uno nuevo (no se guarda hasta que pulses «Guardar cambios»). ¿Empezar de nuevo?", { confirmLabel: "Sí, empezar de nuevo" }))) return;
    $("plStart").hidden = false; $("plEditor").hidden = true;
  });
  function show() { $("plStart").hidden = true; $("plEditor").hidden = false; paintPalette(); paintBlocks(); }

  async function loadQuotes() {
    try { const d = await api("GET", "/api/crm/quotes" + qs({ size: 15 })), s = $("plQuote"); (d.items || []).forEach((q) => { const o = el("option", null, "N.º " + q.number + " · " + (q.title || q.account_name || "")); o.value = String(q.id); s.appendChild(o); }); } catch (e) { /* la de ejemplo basta */ }
  }
  async function init() {
    const state = $("plState");
    try {
      const [list, starter] = await Promise.all([api("GET", "/api/crm/doc-templates"), api("GET", "/api/crm/doc-layout/starter")]);
      meta = starter; tpl = (list.items || []).find((t) => t.id === TID);
      if (!tpl || tpl.kind !== "quote") { state.replaceChildren(stateBlock("error", "Esta plantilla no se puede diseñar", "Solo las plantillas de cotización tienen diseñador.", null)); return; }
      fillCopy(list.items);
      $("plTitle").textContent = "Diseñar la plantilla «" + tpl.name + "»";
      loadQuotes();
      if (tpl.layout) { layout = clone(tpl.layout); nextId = layout.blocks.length + 1; show(); preview(); } else { $("plStart").hidden = false; }
    } catch (e) { state.replaceChildren(stateBlock("error", "No se pudo abrir el diseñador", e.message, init)); }
  }
  init();
})();
