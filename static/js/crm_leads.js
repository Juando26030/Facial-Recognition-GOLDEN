/* CRM - Leads (C2): lista, alta y edición, actividades, conversión en cuenta + contacto (+ oportunidad), descarte y supresión de datos (Ley 1581, solo administradores).
   Lo escrito por personas se pinta con textContent / .value. Sin temporizadores ni sondeos: la lista se carga al abrir y al pulsar «Buscar». */
(function () {
  "use strict";
  const X = window.CRMX, root = document.getElementById("leadsRoot");
  if (!X || !root) return;
  const { $, el, icon, api, qs, plural, stateBlock, busy } = X;
  const canAdmin = root.dataset.canAdmin === "1", PAGER_KEY = "crm_leads";
  const f = { q: $("leadQ"), status: $("leadStatus"), owner: $("leadOwner"), archived: $("leadArchived") };
  const STATUS = { nuevo: "Nuevo", contactado: "Contactado", calificado: "Calificado", convertido: "Convertido", descartado: "Descartado" };
  const BADGE = { nuevo: "gw-badge--info", contactado: "gw-badge--info", calificado: "gw-badge--ok", convertido: "gw-badge--ok", descartado: "" };
  let page = 1, seq = 0;

  function readUrl() {
    const p = new URLSearchParams(window.location.search);
    f.q.value = p.get("q") || ""; f.status.dataset.want = p.get("status") || ""; f.owner.dataset.want = p.get("owner") || ""; if (f.archived) f.archived.checked = p.get("archived") === "1";
    page = Math.max(1, parseInt(p.get("page") || "1", 10) || 1);
  }
  function writeUrl() {
    const p = new URLSearchParams(), set = (k, v) => { if (v) p.set(k, v); };
    set("q", f.q.value.trim()); set("status", f.status.value); set("owner", f.owner.value); if (f.archived && f.archived.checked) p.set("archived", "1"); if (page > 1) p.set("page", String(page));
    const s = p.toString(); try { window.history.replaceState(null, "", window.location.pathname + (s ? "?" + s : "")); } catch (e) { /* sin historial */ }
  }
  const filtered = () => !!(f.q.value.trim() || f.status.value || f.owner.value || (f.archived && f.archived.checked));

  /* ---------------------------------------------------------------- lista */
  function row(l) {
    const tr = document.createElement("tr"), cell = (label, content) => { const td = document.createElement("td"); td.dataset.label = label; if (content instanceof Node) td.appendChild(content); else td.textContent = content == null || content === "" ? "—" : content; tr.appendChild(td); return td; };
    const who = el("div", "crm-name-wrap"); who.appendChild(el("strong", "crm-name-plain", l.full_name || l.company_name || l.email || "Sin nombre"));
    if (l.email) who.appendChild(el("span", "crm-sub", l.email)); if (l.phone) who.appendChild(el("span", "crm-sub", l.phone));
    cell("Lead", who); cell("Empresa", l.company_name);
    const st = el("span", "gw-badge " + (BADGE[l.status] || ""), STATUS[l.status] || l.status); const sw = el("div", "crm-name-wrap"); sw.appendChild(st); if (l.archived) sw.appendChild(el("span", "gw-badge", "Archivado")); cell("Estado", sw);
    cell("Origen", l.source); cell("Responsable", l.owner_name || "Sin responsable");
    const items = [{ label: "Actividades", data: { act: "activities" } }];
    if (l.status !== "convertido") { items.unshift({ label: "Editar", data: { act: "edit" } }); items.push({ label: "Convertir en cuenta…", data: { act: "convert" } }); }
    if (l.status !== "convertido" && l.status !== "descartado") items.push({ label: "Descartar", data: { act: "discard" } });
    if (canAdmin) { items.push({ label: l.archived ? "Restaurar" : "Archivar", data: { act: l.archived ? "restore" : "archive" } }); items.push({ label: "Suprimir sus datos…", data: { act: "erase" } }); }
    const td = cell("Acciones", X.menu("Acciones", items, "Acciones del lead " + (l.full_name || l.company_name || ""))); td.classList.add("crm-actions-cell");
    if (l.converted_account_id) { const a = el("a", "gw-btn gw-btn--secondary gw-btn--sm", "Ver la cuenta"); a.href = "/crm/cuentas/" + l.converted_account_id; td.appendChild(a); }
    tr._lead = l; return tr;
  }
  async function load() {
    const mine = ++seq, body = $("leadBody"), state = $("leadState"), results = $("leadResults"), pager = $("leadPager"); writeUrl(); results.setAttribute("aria-busy", "true");
    try {
      const size = window.GW && GW.pageSize ? GW.pageSize(PAGER_KEY) : 20;
      const data = await api("GET", "/api/crm/leads" + qs({ q: f.q.value.trim(), status: f.status.value, owner_id: f.owner.value, archived: !!(f.archived && f.archived.checked), page, size }));
      if (mine !== seq) return;
      if (!data.items.length && data.total > 0 && page > 1) { page = 1; return load(); }
      body.replaceChildren(); pager.replaceChildren();
      if (!data.total) { results.hidden = true; state.hidden = false; state.replaceChildren(stateBlock("empty", filtered() ? "Ningún lead coincide" : "Todavía no hay leads", filtered() ? "Prueba con otra palabra o quita algún filtro." : "Registra el primero con «Nuevo lead».", null, "users")); return; }
      results.hidden = false; state.hidden = true;
      data.items.forEach((l) => body.appendChild(row(l)));
      if (window.GW && GW.pagerBar) pager.appendChild(GW.pagerBar({ key: PAGER_KEY, total: data.total, page: data.page - 1, onPage: (i) => { page = i + 1; load(); window.scrollTo({ top: 0, behavior: "smooth" }); }, onSize: () => { page = 1; load(); } }));
    } catch (e) { if (mine === seq) { results.hidden = true; state.hidden = false; state.replaceChildren(stateBlock("error", "No se pudo cargar la lista", e.message, load)); } }
    finally { if (mine === seq) results.setAttribute("aria-busy", "false"); }
  }

  /* ---------------------------------------------------------------- alta y edición */
  const FIELDS = [["first_name", "Nombres", 120], ["last_name", "Apellidos", 120], ["company_name", "Empresa", 200], ["job_title", "Cargo", 120], ["email", "Correo", 200], ["phone", "Teléfono", 60], ["source", "Origen (cómo llegó)", 60]];
  async function leadForm(lead) {
    const own = await X.owners(), isNew = !lead, form = el("form", "gw-stack"); form.noValidate = true; const err = X.errorBox(); form.appendChild(err);
    const inputs = {}, row = el("div", "gw-fields-row gw-fields-row--2");
    FIELDS.forEach(([k, label, max]) => { inputs[k] = X.input(k === "email" ? "email" : k === "phone" ? "tel" : "text", max); inputs[k].value = lead && lead[k] ? lead[k] : ""; row.appendChild(X.field("lf_" + k, label, inputs[k])); });
    if (lead) { inputs.first_name.value = lead.first_name || ""; inputs.last_name.value = lead.last_name || ""; }
    form.appendChild(row);
    const status = X.select(["nuevo", "contactado", "calificado", "descartado"].map((s) => ({ value: s, label: STATUS[s] }))), ownerSel = X.select(own.map((o) => ({ value: o.id, label: o.name })), isNew ? "Yo" : "Sin responsable");
    const r2 = el("div", "gw-fields-row gw-fields-row--2"); if (!isNew) { status.value = lead.status; r2.appendChild(X.field("lf_status", "Estado", status)); } if (lead && lead.owner_staff_id) ownerSel.value = String(lead.owner_staff_id); r2.appendChild(X.field("lf_owner", "Responsable", ownerSel)); form.appendChild(r2);
    const desc = el("textarea", "gw-textarea"); desc.rows = 3; desc.maxLength = 20000; desc.value = lead && lead.description ? lead.description : ""; form.appendChild(X.field("lf_desc", "Notas del lead", desc));
    form.appendChild(el("p", "gw-hint", "Las notas son texto libre: no pegues datos personales de terceros."));
    const d = X.dialog({ title: isNew ? "Nuevo lead" : "Editar lead", bodyHtml: "", onEscape: () => d.close(), buttons: [{ id: "lfCancel", cls: "gw-btn--secondary", label: "Cancelar" }, { id: "lfSave", cls: "gw-btn--primary", label: isNew ? "Crear lead" : "Guardar" }] });
    d.dlg.querySelector(".gw-modal__body").replaceChildren(form); d.dlg.querySelector("#lfCancel").addEventListener("click", () => d.close()); inputs.first_name.focus();
    const save = (confirmDup) => busy(d.dlg.querySelector("#lfSave"), async () => {
      err.clear(); const body = {}; FIELDS.forEach(([k]) => { body[k] = inputs[k].value.trim(); }); body.description = desc.value.trim();
      body.owner_staff_id = ownerSel.value ? Number(ownerSel.value) : null; if (!isNew) { body.status = status.value; body.updated_at = lead.updated_at; } else if (confirmDup) body.confirm_duplicate = true;
      try { await api(isNew ? "POST" : "PUT", "/api/crm/leads" + (isNew ? "" : "/" + lead.id), body); d.close(); showToast(isNew ? "Lead creado." : "Cambios guardados.", "success"); load(); }
      catch (e) {
        if (isNew && e.status === 409 && /correo/i.test(e.message)) { if (await showConfirm("", { variant: "warning", title: "Ya hay un lead con ese correo", text: e.message, confirmLabel: "Crear de todos modos" })) return save(true); return; }
        err.show(e.message);
      }
    });
    d.dlg.querySelector("#lfSave").addEventListener("click", () => save(false)); form.addEventListener("submit", (ev) => { ev.preventDefault(); save(false); });
  }

  /* ---------------------------------------------------------------- convertir */
  async function convertForm(lead) {
    const m = await X.meta(), form = el("form", "gw-stack"); form.noValidate = true; const err = X.errorBox(); form.appendChild(err);
    form.appendChild(el("p", "gw-modal__text", "Se crea el contacto con los datos del lead. Elige qué cuenta recibe al contacto."));
    const mode = el("div", "gw-segment"); mode.setAttribute("role", "group"); mode.setAttribute("aria-label", "Cuenta de destino");
    const bNew = el("button", "gw-segment__opt", "Crear cuenta nueva"), bOld = el("button", "gw-segment__opt", "Usar una cuenta que ya existe"); [bNew, bOld].forEach((b) => { b.type = "button"; mode.appendChild(b); }); form.appendChild(mode);
    const newBox = el("div", "gw-stack"), oldBox = el("div", "gw-stack"); oldBox.hidden = true;
    const accName = X.input("text", 200); accName.value = lead.company_name || lead.full_name || ""; newBox.appendChild(X.field("cv_name", "Nombre de la cuenta nueva", accName));
    const accPick = X.accountPicker("cv_found"); oldBox.appendChild(X.pickerField("cv_found", "Cuenta que ya existe", accPick, "Escribe parte del nombre, el código o el NIT y elige de la lista."));
    form.appendChild(newBox); form.appendChild(oldBox);
    function setMode(useOld) { oldBox.hidden = !useOld; newBox.hidden = useOld; bNew.setAttribute("aria-pressed", useOld ? "false" : "true"); bOld.setAttribute("aria-pressed", useOld ? "true" : "false"); }
    setMode(false); bNew.addEventListener("click", () => setMode(false)); bOld.addEventListener("click", () => setMode(true));
    const chk = el("label", "gw-check"), cb = el("input"); cb.type = "checkbox"; chk.appendChild(cb); chk.appendChild(document.createTextNode(" Crear también una oportunidad")); form.appendChild(chk);
    const oppBox = el("div", "gw-stack"); oppBox.hidden = true;
    const oName = X.input("text", 200), oAmount = X.input("text", 20), oCur = X.select(m.currencies.map((c) => ({ value: c, label: c }))), oClose = X.input("date");
    oppBox.appendChild(X.field("cv_oname", "Nombre de la oportunidad", oName)); const r = el("div", "gw-fields-row gw-fields-row--3"); r.appendChild(X.field("cv_oamount", "Monto", oAmount)); r.appendChild(X.field("cv_ocur", "Moneda", oCur)); r.appendChild(X.field("cv_oclose", "Cierre esperado", oClose)); oppBox.appendChild(r); form.appendChild(oppBox);
    cb.addEventListener("change", () => { oppBox.hidden = !cb.checked; });
    const d = X.dialog({ title: "Convertir el lead", bodyHtml: "", onEscape: () => d.close(), buttons: [{ id: "cvCancel", cls: "gw-btn--secondary", label: "Cancelar" }, { id: "cvGo", cls: "gw-btn--primary", label: "Convertir" }] });
    d.dlg.querySelector(".gw-modal__body").replaceChildren(form); d.dlg.querySelector("#cvCancel").addEventListener("click", () => d.close());
    const run = (confirmDup) => busy(d.dlg.querySelector("#cvGo"), async () => {
      err.clear(); const useOld = !oldBox.hidden, body = {};
      if (useOld) { if (!accPick.value) { err.show("Elige la cuenta de la lista que aparece al escribir."); return; } body.account_id = Number(accPick.value); } else { body.account_name = accName.value.trim(); if (confirmDup) body.confirm_duplicate = true; }
      if (cb.checked) { body.create_opportunity = true; body.name = oName.value.trim() || undefined; body.amount = oAmount.value.trim(); body.currency = oCur.value; body.expected_close = oClose.value; }
      try {
        const r2 = await api("POST", "/api/crm/leads/" + lead.id + "/convert", body); d.close(); showToast("Lead convertido.", "success");
        if (r2.opportunity_id) window.location.href = "/crm/oportunidades/" + r2.opportunity_id; else window.location.href = "/crm/cuentas/" + r2.account_id;
      } catch (e) {
        if (e.status === 409 && /existe una cuenta/i.test(e.message)) { if (await showConfirm("", { variant: "warning", title: "Ya hay una cuenta parecida", text: e.message, confirmLabel: "Crear de todos modos" })) return run(true); return; }
        err.show(e.message);
      }
    });
    d.dlg.querySelector("#cvGo").addEventListener("click", () => run(false)); form.addEventListener("submit", (ev) => { ev.preventDefault(); run(false); });
  }

  /* ---------------------------------------------------------------- actividades del lead */
  function activitiesDialog(lead) {
    const box = el("div", "gw-stack"), holder = el("div"), add = el("button", "gw-btn gw-btn--primary", "Programar actividad"); add.type = "button"; box.appendChild(add); box.appendChild(holder);
    const d = X.dialog({ title: "Actividades de " + (lead.full_name || lead.company_name || "este lead"), bodyHtml: "", onEscape: () => d.close(), buttons: [{ id: "alClose", cls: "gw-btn--secondary", label: "Cerrar" }] });
    d.dlg.querySelector(".gw-modal__body").replaceChildren(box); d.dlg.querySelector("#alClose").addEventListener("click", () => d.close());
    const list = X.activityList(holder, { lead_id: lead.id }); add.addEventListener("click", () => list.schedule());
  }

  /* ---------------------------------------------------------------- supresión (Ley 1581) */
  function eraseLines(k) {
    const out = ["su ficha de lead"]; if (k.activities) out.push(plural(k.activities, "actividad suya", "actividades suyas")); if (k.changes) out.push(plural(k.changes, "cambio de su historial", "cambios de su historial"));
    return out;
  }
  function reviewLines(r) {
    const out = []; if (!r) return out;
    if (r.converted_contact) out.push("Este lead se convirtió y su contacto sigue en la cuenta: suprímelo también desde la ficha de la cuenta (pestaña Contactos).");
    if (r.account_notes) out.push(plural(r.account_notes, "nota de la cuenta parece mencionarlo.", "notas de la cuenta parecen mencionarlo."));
    if (r.account_activities) out.push(plural(r.account_activities, "actividad de la cuenta parece mencionarlo.", "actividades de la cuenta parecen mencionarlo."));
    if (r.opportunity_texts) out.push(plural(r.opportunity_texts, "oportunidad con texto que parece mencionarlo.", "oportunidades con texto que parece mencionarlo."));
    return out;
  }
  async function eraseFlow(lead) {
    let counts; const shown = lead.full_name || lead.company_name || lead.email || "";
    try { counts = (await api("GET", "/api/crm/leads/" + lead.id + "/erase-preview")).counts; } catch (e) { showToast(e.message, "error"); return; }
    const body = el("div", "gw-stack"); body.appendChild(el("p", "gw-modal__text", "Esto borra para siempre los datos de " + shown + " en el CRM y no se puede deshacer. Se quitará:"));
    const ul = el("ul", "crm-erase__list"); eraseLines(counts).forEach((t) => ul.appendChild(el("li", null, t))); body.appendChild(ul);
    const rv = reviewLines(counts.review);
    if (rv.length) { const warn = el("div", "gw-alert gw-alert--warn"); warn.appendChild(icon("alert")); const inner = el("div"); inner.appendChild(el("p", "gw-alert__title", "Después tendrás que revisar a mano")); rv.forEach((t) => inner.appendChild(el("p", "gw-alert__body", t))); warn.appendChild(inner); body.appendChild(warn); }
    else body.appendChild(el("p", "gw-hint", "No encontramos texto libre que parezca mencionarlo."));
    const err = X.errorBox(), reason = X.input("text", 200), nm = X.input("text", 240); body.appendChild(err); body.appendChild(X.field("le_reason", "Motivo de la supresión", reason)); body.appendChild(X.field("le_name", "Escribe su nombre (o empresa) tal como aparece para confirmar", nm));
    const d = X.dialog({ title: "Suprimir los datos de un lead", warning: true, bodyHtml: "", onEscape: () => d.close(), buttons: [{ id: "leCancel", cls: "gw-btn--secondary", label: "Cancelar" }, { id: "leGo", cls: "gw-btn--danger", label: "Suprimir definitivamente" }] });
    d.dlg.querySelector(".gw-modal__body").replaceChildren(body);
    const go = d.dlg.querySelector("#leGo"); go.disabled = true; const ready = () => { go.disabled = !(reason.value.trim() && nm.value.trim().toLowerCase() === shown.trim().toLowerCase()); }; reason.addEventListener("input", ready); nm.addEventListener("input", ready);
    d.dlg.querySelector("#leCancel").addEventListener("click", () => d.close()); reason.focus();
    go.addEventListener("click", () => busy(go, async () => {
      try { const r = await api("POST", "/api/crm/leads/" + lead.id + "/erase", { reason: reason.value.trim(), confirm_name: nm.value.trim() }); d.close(); showReview(r.counts); load(); } catch (e) { err.show(e.message); }
    }));
  }
  function showReview(k) {
    const box = $("leadReview"), rv = reviewLines(k.review); box.hidden = false; box.replaceChildren(); box.className = "gw-alert " + (rv.length ? "gw-alert--warn" : "gw-alert--ok");
    box.appendChild(icon(rv.length ? "alert" : "check")); const inner = el("div", "gw-stack"); inner.appendChild(el("p", "gw-alert__title", rv.length ? "Datos suprimidos. Falta revisar" : "Datos suprimidos"));
    inner.appendChild(el("p", "gw-alert__body", "Se quitó: " + eraseLines(k).join(", ") + ".")); rv.forEach((t) => inner.appendChild(el("p", "gw-alert__body", t)));
    const ok = el("button", "gw-btn gw-btn--secondary gw-btn--sm", rv.length ? "Ya lo revisé" : "Cerrar"); ok.type = "button"; ok.addEventListener("click", () => { box.hidden = true; box.replaceChildren(); }); inner.appendChild(ok); box.appendChild(inner); box.scrollIntoView({ block: "center" });
  }

  /* ---------------------------------------------------------------- eventos */
  $("leadBody").addEventListener("click", async (e) => {
    if (X.menuClick(e)) return;
    const b = e.target.closest("[data-act]"); if (!b) return; const lead = b.closest("tr")._lead; X.closeMenus();
    if (b.dataset.act === "edit") return leadForm(lead);
    if (b.dataset.act === "convert") return convertForm(lead);
    if (b.dataset.act === "activities") return activitiesDialog(lead);
    if (b.dataset.act === "erase") return eraseFlow(lead);
    if (b.dataset.act === "discard") {
      if (!await showConfirm("", { variant: "warning", title: "Descartar lead", text: "El lead queda marcado como descartado. Puedes devolverlo a «nuevo» editándolo.", confirmLabel: "Descartar" })) return;
      try { await api("POST", "/api/crm/leads/" + lead.id + "/discard"); showToast("Lead descartado.", "success"); load(); } catch (err) { showToast(err.message, "error"); }
      return;
    }
    if (b.dataset.act === "archive" || b.dataset.act === "restore") { try { await api("POST", "/api/crm/leads/" + lead.id + "/" + b.dataset.act); showToast("Listo.", "success"); load(); } catch (err) { showToast(err.message, "error"); } }
  });
  $("leadNew").addEventListener("click", () => leadForm(null));
  $("leadFilters").addEventListener("submit", (e) => { e.preventDefault(); page = 1; load(); });
  [f.status, f.owner, f.archived].forEach((n) => { if (n) n.addEventListener("change", () => { page = 1; load(); }); });
  $("leadClear").addEventListener("click", () => { f.q.value = ""; f.status.value = ""; f.owner.value = ""; if (f.archived) f.archived.checked = false; page = 1; load(); });

  async function init() {
    readUrl();
    try {
      const [m, own] = await Promise.all([X.meta(), X.owners()]);
      f.status.replaceChildren(new Option("Todos", "")); m.lead_statuses.forEach((s) => f.status.appendChild(new Option(STATUS[s] || s, s))); if (f.status.dataset.want) f.status.value = f.status.dataset.want;
      f.owner.replaceChildren(new Option("Todos", "")); own.forEach((o) => f.owner.appendChild(new Option(o.name, o.id))); if (f.owner.dataset.want) f.owner.value = f.owner.dataset.want;
    } catch (e) { /* los filtros quedan en «Todos» */ }
    load();
  }
  init();
})();
