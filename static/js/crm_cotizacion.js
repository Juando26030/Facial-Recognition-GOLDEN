/* CRM - Cotización (C3): editor. Se carga al abrir (una consulta del detalle + catálogos) y al guardar; sin temporizadores ni sondeos.
   Lo escrito por personas se pinta con textContent / .value. Los totales de pantalla son una vista previa: el servidor los recalcula siempre al guardar. */
(function () {
  "use strict";
  const X = window.CRMX, root = document.getElementById("quoteRoot");
  if (!X || !root) return;
  const { $, el, api, qs, stateBlock, busy, dialog, field, input, select, errorBox, menu } = X;
  const id = Number(root.dataset.quoteId), canAdmin = root.dataset.canAdmin === "1";
  const STAGE = { borrador: "Borrador", enviada: "Enviada", negociada: "Negociada", aprobada: "Aprobada", rechazada: "Rechazada", vencida: "Vencida" };
  let q = null, meta = null, lines = [], dirty = false;

  /* Dinero con 2 decimales y redondeo de mitad hacia arriba, igual que el servidor (se calcula en centavos enteros). */
  const toCents = (v) => Math.round((Number(String(v).replace(",", ".")) || 0) * 100 + 1e-9);
  const fmt = (cents, cur) => (cur || "COP") + " " + (cents / 100).toLocaleString("es-CO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  function lineCents(l) {
    const gross = Math.round(Number(l.qty || 0) * toCents(l.unit_price) + 1e-9), disc = Math.round(gross * Number(l.discount_percent || 0) / 100 + 1e-9), net = gross - disc;
    return { net, disc, tax: Math.round(net * Number(l.tax_percent || 0) / 100 + 1e-9) };
  }
  function totals() { let sub = 0, disc = 0, tax = 0; lines.forEach((l) => { const c = lineCents(l); sub += c.net; disc += c.disc; tax += c.tax; }); return { sub, disc, tax, total: sub + tax }; }
  function showTotals() {
    const t = totals(), dl = $("qTotals"); dl.replaceChildren();
    [["Subtotal", t.sub], ["Descuentos", t.disc], ["Impuestos", t.tax]].forEach(([k, v]) => { dl.appendChild(el("dt", "", k)); dl.appendChild(el("dd", "", fmt(v, q.currency))); });
    const a = el("dt", "is-total", "Total"), b = el("dd", "is-total", fmt(t.total, q.currency)); dl.appendChild(a); dl.appendChild(b);
  }
  const markDirty = () => { dirty = true; };
  window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });

  function lineRow(l, i) {
    const tr = document.createElement("tr"), cell = (label, node) => { const td = document.createElement("td"); td.dataset.label = label; td.appendChild(node); tr.appendChild(td); return td; };
    const nm = input("text", 200); nm.value = l.name || ""; nm.setAttribute("aria-label", "Concepto de la línea " + (i + 1)); nm.addEventListener("input", () => { l.name = nm.value; markDirty(); });
    const qty = input("text"), price = input("text"), disc = input("text"), tax = input("text");
    [[qty, "qty", "Cantidad"], [price, "unit_price", "Precio unitario"], [disc, "discount_percent", "Descuento"], [tax, "tax_percent", "Impuesto"]].forEach(([c, k, lab]) => {
      c.inputMode = "decimal"; c.value = l[k]; c.setAttribute("aria-label", lab + " de la línea " + (i + 1));
      c.addEventListener("input", () => { l[k] = c.value.replace(",", "."); markDirty(); total.textContent = fmt(lineCents(l).net, q.currency); showTotals(); });
    });
    const total = el("span", "", fmt(lineCents(l).net, q.currency));
    const wrap = el("div", "gw-stack"); wrap.appendChild(nm);
    const desc = el("textarea", "gw-textarea"); desc.rows = 2; desc.maxLength = 20000; desc.value = l.description || ""; desc.placeholder = "Descripción (opcional)"; desc.setAttribute("aria-label", "Descripción de la línea " + (i + 1)); desc.addEventListener("input", () => { l.description = desc.value; markDirty(); }); wrap.appendChild(desc);
    cell("Concepto", wrap); cell("Cant.", qty); cell("Precio", price); cell("Desc. %", disc); cell("Imp. %", tax); cell("Total", total);
    const rm = el("button", "gw-btn gw-btn--secondary gw-btn--sm", "Quitar"); rm.type = "button"; rm.setAttribute("aria-label", "Quitar la línea " + (i + 1)); rm.dataset.remove = String(i); cell("Quitar", rm);
    return tr;
  }
  function renderLines() {
    const body = $("qLines"); body.replaceChildren(); lines.forEach((l, i) => body.appendChild(lineRow(l, i))); $("qLinesEmpty").hidden = lines.length > 0; showTotals();
  }
  $("qLines").addEventListener("click", (e) => { const b = e.target.closest("[data-remove]"); if (!b) return; lines.splice(Number(b.dataset.remove), 1); markDirty(); renderLines(); });
  $("qAddLine").addEventListener("click", () => { lines.push({ name: "", description: "", qty: "1", unit_price: "0", discount_percent: "0", tax_percent: "19", product_id: null }); markDirty(); renderLines(); const rows = $("qLines").querySelectorAll("tr"); const last = rows[rows.length - 1]; if (last) last.querySelector("input").focus(); });

  async function addFromProduct() {
    const search = input("search", 100), found = select([], "Escribe y pulsa «Buscar»"), err = errorBox(), find = el("button", "gw-btn gw-btn--secondary gw-btn--sm", "Buscar"); find.type = "button";
    const body = el("div", "gw-stack"); body.appendChild(err); body.appendChild(field("apSearch", "Producto o servicio", search)); body.appendChild(find); body.appendChild(field("apFound", "Resultado", found));
    let items = [];
    const d = dialog({ title: "Agregar desde un producto", bodyHtml: "", onEscape: () => d.close(), buttons: [{ id: "apCancel", cls: "gw-btn--secondary", label: "Cancelar" }, { id: "apOk", cls: "gw-btn--primary", label: "Agregar" }] });
    d.dlg.querySelector(".gw-modal__body").replaceChildren(body);
    const lookup = async () => { try { const r = await api("GET", "/api/crm/products" + qs({ q: search.value.trim(), active: true, size: 20 })); items = r.items; found.replaceChildren(new Option(items.length ? "Elige un producto…" : "Sin resultados", "")); items.forEach((p) => found.appendChild(new Option(p.name + " (" + p.currency + " " + Number(p.price).toLocaleString("es-CO") + ")", String(p.id)))); } catch (e) { err.show(e.message); } };
    find.addEventListener("click", lookup); search.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); lookup(); } });
    d.dlg.querySelector("#apCancel").addEventListener("click", () => d.close());
    d.dlg.querySelector("#apOk").addEventListener("click", () => {
      const p = items.find((x) => String(x.id) === found.value); if (!p) { err.show("Elige un producto de la lista."); return; }
      lines.push({ name: p.name, description: p.description || "", qty: "1", unit_price: p.price, discount_percent: "0", tax_percent: p.tax_percent, product_id: p.id }); markDirty(); renderLines(); d.close();
    });
    search.focus();
  }
  $("qAddProduct").addEventListener("click", addFromProduct);

  /* ---------------------------------------------------------------- guardar y acciones */
  const err = (t) => { const b = $("qError"); b.hidden = !t; if (t) b.firstChild.textContent = t; };
  function body() {
    return { updated_at: q.updated_at, title: $("fTitle").value.trim(), contact_id: $("fContact").value || null, currency: $("fCurrency").value, valid_until: $("fValid").value || null, event_start: $("fEvent").value || null,
             template_id: $("fTemplate").value || null, terms_id: $("fTerms").value || null, terms_text: $("fTermsText").value, meeting_notes: $("fNotes").value,
             lines: lines.map((l) => ({ product_id: l.product_id, name: l.name, description: l.description, qty: l.qty, unit_price: l.unit_price, discount_percent: l.discount_percent, tax_percent: l.tax_percent })) };
  }
  async function save(btn) {
    err("");
    try { await busy(btn, async () => { q = await api("PUT", "/api/crm/quotes/" + id, body()); dirty = false; paint(); showToast("Cotización guardada.", "success"); loadHistory(); }); }
    catch (e) { err(e.message); }
  }
  $("qSave").addEventListener("click", (e) => save(e.currentTarget));
  $("fTerms").addEventListener("change", () => { const t = meta.terms.find((x) => String(x.id) === $("fTerms").value); if (t) $("fTermsText").value = t.body; markDirty(); });
  ["fTitle", "fContact", "fCurrency", "fValid", "fEvent", "fTemplate", "fTermsText", "fNotes"].forEach((k) => $(k).addEventListener("input", markDirty));
  $("fCurrency").addEventListener("change", () => { q.currency = $("fCurrency").value; renderLines(); });

  async function guarded(fn) { if (dirty && !(await showConfirm("Tienes cambios sin guardar. Guárdalos primero con «Guardar cambios». ¿Continuar sin guardarlos?", { title: "Cambios sin guardar", confirmLabel: "Continuar" }))) return; err(""); try { await fn(); } catch (e) { err(e.message); } }
  async function setStage(stage) { await guarded(async () => { q = await api("POST", "/api/crm/quotes/" + id + "/stage", { stage, updated_at: q.updated_at }); dirty = false; fillForm(); paint(); loadHistory(); showToast("Etapa actualizada.", "success"); }); }
  async function newVersion() { await guarded(async () => { const nq = await api("POST", "/api/crm/quotes/" + id + "/new-version"); window.location.href = "/crm/cotizaciones/" + nq.id; }); }
  async function toProforma() {
    const ev = input("text", 200), city = input("text", 120), e2 = errorBox(), b = el("div", "gw-stack"); ev.value = q.title; b.appendChild(e2); b.appendChild(field("pfEvent", "Nombre del evento", ev)); b.appendChild(field("pfCity", "Ciudad (opcional)", city));
    const d = dialog({ title: "Crear proforma", bodyHtml: "", onEscape: () => d.close(), buttons: [{ id: "pfCancel", cls: "gw-btn--secondary", label: "Cancelar" }, { id: "pfOk", cls: "gw-btn--primary", label: "Crear proforma" }] });
    d.dlg.querySelector(".gw-modal__body").replaceChildren(b); d.dlg.querySelector("#pfCancel").addEventListener("click", () => d.close());
    d.dlg.querySelector("#pfOk").addEventListener("click", async (e) => {
      e2.clear(); try { await busy(e.currentTarget, async () => { const p = await api("POST", "/api/crm/quotes/" + id + "/proforma", { event_name: ev.value.trim() || q.title, city: city.value.trim() || null }); d.close(); showToast("Proforma " + p.number + " creada.", "success"); window.open("/api/crm/proformas/" + p.id + "/pdf", "_blank", "noopener"); }); } catch (x) { e2.show(x.message); }
    });
  }
  async function archive(restore) {
    if (!restore && !(await showConfirm("La cotización deja de verse en la lista, pero no se borra. ¿Archivar?", { title: "Archivar cotización", confirmLabel: "Archivar" }))) return;
    err(""); try { q = await api("POST", "/api/crm/quotes/" + id + (restore ? "/restore" : "/archive")); paint(); } catch (e) { err(e.message); }
  }

  /* ---------------------------------------------------------------- pintar */
  function fillForm() {
    $("fTitle").value = q.title || ""; $("fValid").value = q.valid_until || ""; $("fEvent").value = q.event_start || ""; $("fCurrency").value = q.currency; $("fTemplate").value = q.template_id || ""; $("fTerms").value = q.terms_id || "";
    $("fTermsText").value = q.terms_text || ""; $("fNotes").value = q.meeting_notes || ""; $("fContact").value = q.contact_id || "";
    lines = q.lines.map((l) => ({ product_id: l.product_id, name: l.name, description: l.description || "", qty: l.qty, unit_price: l.unit_price, discount_percent: l.discount_percent, tax_percent: l.tax_percent })); renderLines();
  }
  function paint() {
    $("qNumber").textContent = "Cotización N.º " + q.number + (q.version > 1 ? " · versión " + q.version : "");
    $("qTitle").textContent = q.title; $("qSub").textContent = (q.account_name || "") + (q.owner_name ? " · Responsable: " + q.owner_name : "");
    const open = q.stage === "borrador" || q.stage === "enviada" || q.stage === "negociada", locked = q.archived;
    const notice = $("qNotice"), msgs = []; if (q.expired) msgs.push("Esta cotización ya pasó su fecha de validez."); if (q.archived) msgs.push("Está archivada: no se puede editar."); if (q.stage !== "borrador" && !q.archived) msgs.push("Ya fue enviada. Si necesitas cambiar precios, crea una versión nueva; la anterior queda intacta.");
    notice.hidden = !msgs.length; notice.firstChild.textContent = msgs.join(" ");
    const acts = $("qActions"); acts.replaceChildren();
    const pdf = el("a", "gw-btn gw-btn--secondary", "Descargar PDF"); pdf.href = "/api/crm/quotes/" + id + "/pdf"; pdf.target = "_blank"; pdf.rel = "noopener"; acts.appendChild(pdf);
    const items = [];
    if (q.stage === "borrador") items.push({ label: "Marcar como enviada", data: { act: "stage", v: "enviada" } });
    if (q.stage === "enviada") items.push({ label: "Pasar a negociación", data: { act: "stage", v: "negociada" } });
    if (open && q.stage !== "borrador") { items.push({ label: "Marcar como aprobada", data: { act: "stage", v: "aprobada" } }); items.push({ label: "Marcar como rechazada", data: { act: "stage", v: "rechazada" } }); }
    if (q.stage !== "borrador") items.push({ label: "Crear versión nueva", data: { act: "version" } });
    if (["enviada", "negociada", "aprobada"].includes(q.stage)) items.push({ label: "Crear proforma", data: { act: "proforma" } });
    if (canAdmin) items.push({ label: q.archived ? "Restaurar" : "Archivar", data: { act: q.archived ? "restore" : "archive" } });
    if (items.length) acts.appendChild(menu("Más acciones", items, "Más acciones de la cotización"));
    const sb = el("span", "gw-badge", STAGE[q.stage] || q.stage); acts.insertBefore(sb, acts.firstChild);
    $("qSave").disabled = locked; $("qSaveBar").hidden = locked;
    const ul = $("qVersions"); ul.replaceChildren();
    q.versions.forEach((v) => { const li = document.createElement("li"), t = "Versión " + v.version + " · " + (STAGE[v.stage] || v.stage); if (v.id === q.id) li.appendChild(el("span", "gw-badge gw-badge--info", t + " (actual)")); else { const a = el("a", "gw-btn gw-btn--secondary gw-btn--sm", t); a.href = "/crm/cotizaciones/" + v.id; li.appendChild(a); } ul.appendChild(li); });
    showTotals();
  }
  $("qActions").addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]"); if (!b) return; X.closeMenus();
    ({ stage: () => setStage(b.dataset.v), version: newVersion, proforma: toProforma, archive: () => archive(false), restore: () => archive(true) })[b.dataset.act]();
  });

  async function loadHistory() {
    const box = $("qHistory");
    try {
      const rows = await api("GET", "/api/crm/quotes/" + id + "/history"); box.replaceChildren();
      if (!rows.length) { box.appendChild(el("p", "gw-hint", "Todavía no hay cambios registrados.")); return; }
      const ul = el("ul", "crm-history-list");
      rows.forEach((r) => { const li = document.createElement("li"); li.textContent = X.fmtDateTime(r.at) + " · " + r.field + (r.source ? " (" + r.source + ")" : "") + (r.old != null || r.new != null ? ": " + (r.old == null ? "—" : r.old) + " → " + (r.new == null ? "—" : r.new) : ""); ul.appendChild(li); });
      box.appendChild(ul);
    } catch (e) { box.replaceChildren(el("p", "gw-hint", "No se pudo cargar el historial.")); }
  }

  async function start() {
    const state = $("quoteState"), main = $("quoteMain");
    try {
      [q, meta] = await Promise.all([api("GET", "/api/crm/quotes/" + id), api("GET", "/api/crm/quotes/meta")]);
      meta.currencies.forEach((c) => $("fCurrency").appendChild(new Option(c, c)));
      meta.templates.filter((t) => t.kind === "quote").forEach((t) => $("fTemplate").appendChild(new Option(t.name, String(t.id))));
      meta.terms.forEach((t) => $("fTerms").appendChild(new Option(t.name, String(t.id))));
      try { const cs = await api("GET", "/api/crm/accounts/" + q.account_id + "/contacts"); cs.forEach((c) => $("fContact").appendChild(new Option(c.full_name, String(c.id)))); } catch (e) { /* sin contactos se puede cotizar igual */ }
      fillForm(); paint(); state.hidden = true; main.hidden = false; loadHistory();
    } catch (e) { main.hidden = true; state.hidden = false; state.replaceChildren(stateBlock("error", "No se pudo abrir la cotización", e.message, start)); }
  }
  start();
})();
