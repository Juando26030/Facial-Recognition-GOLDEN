/* CRM - Productos, condiciones y plantillas del PDF (C3, solo admin). Se carga al abrir y tras cada cambio; sin temporizadores. Todo texto de personas con textContent / .value. */
(function () {
  "use strict";
  const X = window.CRMX, root = document.getElementById("catalogRoot");
  if (!X || !root) return;
  const { $, el, api, qs, stateBlock, busy, dialog, field, input, select, errorBox } = X;
  const PAGER_KEY = "crm_products";
  let page = 1, seq = 0, products = [], terms = [], templates = [];

  function editor(title, controls, onSave) {
    const err = errorBox(), body = el("div", "gw-stack"); body.appendChild(err); controls.forEach(([id, label, ctl]) => body.appendChild(field(id, label, ctl)));
    const d = dialog({ title, bodyHtml: "", onEscape: () => d.close(), buttons: [{ id: "edCancel", cls: "gw-btn--secondary", label: "Cancelar" }, { id: "edSave", cls: "gw-btn--primary", label: "Guardar" }] });
    d.dlg.querySelector(".gw-modal__body").replaceChildren(body); d.dlg.querySelector("#edCancel").addEventListener("click", () => d.close());
    d.dlg.querySelector("#edSave").addEventListener("click", async (e) => { err.clear(); try { await busy(e.currentTarget, async () => { await onSave(); d.close(); }); } catch (x) { err.show(x.message); } });
    const first = body.querySelector("input,textarea,select"); if (first) first.focus();
  }
  const area = (max, rows) => { const t = el("textarea", "gw-textarea"); t.maxLength = max; t.rows = rows || 4; return t; };

  /* ---------------------------------------------------------------- productos */
  function photoControl(p) {
    const box = el("div", "pl-photo"), file = el("input"); file.type = "file"; file.accept = "image/png,image/jpeg,.png,.jpg,.jpeg";
    const img = el("img", "pl-thumb"), rm = el("button", "gw-btn gw-btn--secondary gw-btn--sm", "Quitar foto"); rm.type = "button";
    const show = (on) => { img.hidden = !on; rm.hidden = !on; if (on) img.src = "/api/crm/products/" + p.id + "/image?v=" + Date.now(); };
    img.alt = "Foto de " + p.name; show(!!p.has_image);
    file.addEventListener("change", async () => {
      const f = file.files[0]; if (!f) return; const fd = new FormData(); fd.append("file", f);
      try { const r = await fetch("/api/crm/products/" + p.id + "/image", { method: "POST", body: fd }), d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "No se pudo subir la foto."); p.has_image = true; show(true); showToast("Foto guardada.", "success"); }
      catch (x) { showToast(x.message, "error"); file.value = ""; }
    });
    rm.addEventListener("click", async () => { try { await api("DELETE", "/api/crm/products/" + p.id + "/image"); p.has_image = false; show(false); file.value = ""; showToast("Foto quitada.", "success"); } catch (x) { showToast(x.message, "error"); } });
    box.appendChild(img); box.appendChild(file); box.appendChild(rm); return box;
  }
  function productDialog(p) {
    const sku = input("text", 60), name = input("text", 200), cat = input("text", 80), price = input("text"), cost = input("text"), tax = input("text"), cur = select(["COP", "USD", "EUR"].map((c) => ({ value: c, label: c }))), desc = area(20000, 3);
    if (p) { sku.value = p.sku || ""; name.value = p.name; cat.value = p.category || ""; price.value = p.price; cost.value = p.cost; tax.value = p.tax_percent; cur.value = p.currency; desc.value = p.description || ""; } else { price.value = "0"; cost.value = "0"; tax.value = "19"; }
    [price, cost, tax].forEach((c) => { c.inputMode = "decimal"; });
    const photo = p ? photoControl(p) : null;
    editor(p ? "Editar producto" : "Nuevo producto", [["pdName", "Nombre", name], ["pdSku", "Código (SKU, opcional)", sku], ["pdCat", "Categoría (opcional)", cat], ["pdPrice", "Precio", price], ["pdCost", "Costo (opcional)", cost], ["pdCur", "Moneda", cur], ["pdTax", "Impuesto (%)", tax], ["pdDesc", "Descripción (opcional)", desc]].concat(photo ? [["pdPhoto", "Foto para la cotización (opcional)", photo]] : []), async () => {
      const data = { name: name.value.trim(), sku: sku.value.trim() || null, category: cat.value.trim() || null, price: price.value.replace(",", "."), cost: cost.value.replace(",", "."), currency: cur.value, tax_percent: tax.value.replace(",", "."), description: desc.value };
      if (p) await api("PUT", "/api/crm/products/" + p.id, Object.assign(data, { updated_at: p.updated_at })); else await api("POST", "/api/crm/products", data);
      showToast("Producto guardado.", "success"); loadProducts();
    });
  }
  function productRow(p) {
    const tr = document.createElement("tr"), cell = (label, v) => { const td = document.createElement("td"); td.dataset.label = label; if (v instanceof Node) td.appendChild(v); else td.textContent = v == null || v === "" ? "—" : v; tr.appendChild(td); return td; };
    cell("Producto", p.name); cell("Código", p.sku); cell("Precio", p.currency + " " + Number(p.price).toLocaleString("es-CO", { minimumFractionDigits: 2 })); cell("Impuesto", Number(p.tax_percent) + " %");
    cell("Estado", el("span", "gw-badge " + (p.active ? "gw-badge--ok" : ""), p.active ? "Activo" : "Inactivo"));
    const td = cell("Acciones", document.createDocumentFragment()); td.classList.add("crm-actions-cell");
    const ed = el("button", "gw-btn gw-btn--secondary gw-btn--sm", "Editar"); ed.type = "button"; ed.dataset.edit = String(p.id); ed.setAttribute("aria-label", "Editar " + p.name); td.appendChild(ed);
    const tg = el("button", "gw-btn gw-btn--secondary gw-btn--sm", p.active ? "Desactivar" : "Activar"); tg.type = "button"; tg.dataset.toggle = String(p.id); tg.setAttribute("aria-label", (p.active ? "Desactivar " : "Activar ") + p.name); td.appendChild(tg);
    return tr;
  }
  async function loadProducts() {
    const mine = ++seq, body = $("prodBody"), state = $("prodState"), res = $("prodResults");
    try {
      const size = window.GW && GW.pageSize ? GW.pageSize(PAGER_KEY) : 20;
      const data = await api("GET", "/api/crm/products" + qs({ q: $("prodQ").value.trim(), page, size })); if (mine !== seq) return;
      if (!data.items.length && data.total > 0 && page > 1) { page = 1; return loadProducts(); }
      products = data.items; body.replaceChildren(); $("prodPager").replaceChildren();
      if (!data.total) { res.hidden = true; state.hidden = false; state.replaceChildren(stateBlock("empty", "Todavía no hay productos", "Crea el primero con «Nuevo producto».", null, "sheet")); return; }
      res.hidden = false; state.hidden = true; products.forEach((p) => body.appendChild(productRow(p)));
      if (window.GW && GW.pagerBar) $("prodPager").appendChild(GW.pagerBar({ key: PAGER_KEY, total: data.total, page: data.page - 1, onPage: (i) => { page = i + 1; loadProducts(); }, onSize: () => { page = 1; loadProducts(); } }));
    } catch (e) { if (mine === seq) { res.hidden = true; state.hidden = false; state.replaceChildren(stateBlock("error", "No se pudo cargar el catálogo", e.message, loadProducts)); } }
  }
  $("prodBody").addEventListener("click", async (e) => {
    const ed = e.target.closest("[data-edit]"), tg = e.target.closest("[data-toggle]");
    if (ed) { const p = products.find((x) => String(x.id) === ed.dataset.edit); if (p) productDialog(p); }
    if (tg) { const p = products.find((x) => String(x.id) === tg.dataset.toggle); if (!p) return; try { await api("PUT", "/api/crm/products/" + p.id, { active: !p.active, updated_at: p.updated_at }); loadProducts(); } catch (x) { showToast(x.message, "error"); } }
  });
  $("prodFilters").addEventListener("submit", (e) => { e.preventDefault(); page = 1; loadProducts(); });
  $("prodNew").addEventListener("click", () => productDialog(null));

  /* ---------------------------------------------------------------- condiciones */
  function simpleItem(title, sub, attr, id, archived, designHref, dupAttr) {
    const li = document.createElement("li"), t = el("div", "crm-name-wrap"); t.appendChild(el("span", "crm-name", title)); if (sub) t.appendChild(el("span", "crm-sub", sub)); li.appendChild(t);
    const a = el("div", "crm-card-actions"), ed = el("button", "gw-btn gw-btn--secondary gw-btn--sm", "Editar"); ed.type = "button"; ed.dataset[attr] = String(id); ed.setAttribute("aria-label", "Editar " + title); a.appendChild(ed);
    if (designHref) { const dz = el("a", "gw-btn gw-btn--secondary gw-btn--sm", "Diseñar"); dz.href = designHref; dz.setAttribute("aria-label", "Diseñar el PDF de " + title); a.appendChild(dz); }
    if (dupAttr) { const dp = el("button", "gw-btn gw-btn--secondary gw-btn--sm", "Duplicar"); dp.type = "button"; dp.dataset[dupAttr] = String(id); dp.setAttribute("aria-label", "Duplicar " + title); a.appendChild(dp); }
    const ar = el("button", "gw-btn gw-btn--secondary gw-btn--sm", archived ? "Restaurar" : "Archivar"); ar.type = "button"; ar.dataset[attr + "Archive"] = String(id); ar.setAttribute("aria-label", (archived ? "Restaurar " : "Archivar ") + title); a.appendChild(ar); li.appendChild(a); return li;
  }
  function termDialog(t) {
    const name = input("text", 120), bodyT = area(20000, 6); if (t) { name.value = t.name; bodyT.value = t.body; }
    editor(t ? "Editar condición" : "Nueva condición", [["tmName", "Nombre", name], ["tmBody", "Texto", bodyT]], async () => {
      if (t) await api("PUT", "/api/crm/terms/" + t.id, { name: name.value.trim(), body: bodyT.value }); else await api("POST", "/api/crm/terms", { name: name.value.trim(), body: bodyT.value });
      showToast("Condición guardada.", "success"); loadTerms();
    });
  }
  async function loadTerms() {
    const ul = $("termList");
    try { terms = (await api("GET", "/api/crm/terms?archived=true")).items; ul.replaceChildren(); if (!terms.length) ul.appendChild(el("li", "gw-hint", "Todavía no hay condiciones guardadas."));
      terms.forEach((t) => ul.appendChild(simpleItem(t.name + (t.archived ? " (archivada)" : ""), "", "term", t.id, t.archived))); } catch (e) { ul.replaceChildren(el("li", "gw-hint", "No se pudieron cargar las condiciones.")); }
  }
  $("termList").addEventListener("click", async (e) => {
    const ed = e.target.closest("[data-term]"), ar = e.target.closest("[data-term-archive]");
    if (ed) termDialog(terms.find((x) => String(x.id) === ed.dataset.term));
    if (ar) { const t = terms.find((x) => String(x.id) === ar.dataset.termArchive); try { await api("PUT", "/api/crm/terms/" + t.id, { archived: !t.archived }); loadTerms(); } catch (x) { showToast(x.message, "error"); } }
  });
  $("termNew").addEventListener("click", () => termDialog(null));

  /* ---------------------------------------------------------------- plantillas */
  const KIND = { quote: "Cotización", proforma: "Proforma" };
  function templateDialog(t) {
    const kind = select([{ value: "quote", label: "Cotización" }, { value: "proforma", label: "Proforma" }]), name = input("text", 120), head = area(2000, 3), greet = area(2000, 3), foot = area(2000, 3);
    if (t) { kind.value = t.kind; kind.disabled = true; name.value = t.name; head.value = t.header_text || ""; greet.value = t.greeting_text || ""; foot.value = t.footer_text || ""; }
    editor(t ? "Editar plantilla" : "Nueva plantilla", [["tpKind", "Para", kind], ["tpName", "Nombre", name], ["tpHead", "Encabezado", head], ["tpGreet", "Saludo", greet], ["tpFoot", "Pie de página", foot]], async () => {
      const data = { kind: kind.value, name: name.value.trim(), header_text: head.value, greeting_text: greet.value, footer_text: foot.value };
      if (t) await api("PUT", "/api/crm/doc-templates/" + t.id, data); else await api("POST", "/api/crm/doc-templates", data);
      showToast("Plantilla guardada.", "success"); loadTemplates();
    });
  }
  async function loadTemplates() {
    const ul = $("tplList");
    try { templates = (await api("GET", "/api/crm/doc-templates")).items; ul.replaceChildren(); if (!templates.length) ul.appendChild(el("li", "gw-hint", "Todavía no hay plantillas: el PDF sale con el formato básico."));
      templates.forEach((t) => ul.appendChild(simpleItem(t.name, KIND[t.kind] + (t.is_default ? " · predeterminada" : ""), "tpl", t.id, false, t.kind === "quote" ? "/crm/plantillas/" + t.id + "/disenar" : null, "tplDup"))); } catch (e) { ul.replaceChildren(el("li", "gw-hint", "No se pudieron cargar las plantillas.")); }
  }
  $("tplList").addEventListener("click", async (e) => {
    const ed = e.target.closest("[data-tpl]"), ar = e.target.closest("[data-tpl-archive]"), dp = e.target.closest("[data-tpl-dup]");
    if (dp) { try { await api("POST", "/api/crm/doc-templates/" + dp.dataset.tplDup + "/duplicate"); showToast("Plantilla duplicada: la copia se llama «… (copia)».", "success"); loadTemplates(); } catch (x) { showToast(x.message, "error"); } return; }
    if (ed) templateDialog(templates.find((x) => String(x.id) === ed.dataset.tpl));
    if (ar) { const t = templates.find((x) => String(x.id) === ar.dataset.tplArchive); try { await api("PUT", "/api/crm/doc-templates/" + t.id, { archived: true }); loadTemplates(); } catch (x) { showToast(x.message, "error"); } }
  });
  $("tplNew").addEventListener("click", () => templateDialog(null));

  loadProducts(); loadTerms(); loadTemplates();
})();
