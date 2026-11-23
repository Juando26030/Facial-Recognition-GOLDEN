/* CRM (etapa C2): utilidades compartidas por el tablero, la ficha de oportunidad, los leads y los embudos (window.CRMX).
   Todo lo que escribió una persona se pinta con textContent / .value, nunca con HTML armado a mano. Sin onclick en línea. Sin temporizadores ni sondeos: nada se refresca solo. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const busy = (btn, work) => (window.GW && GW.busy ? GW.busy(btn, work) : Promise.resolve(work()));

  function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function icon(name, cls) {
    const ns = "http://www.w3.org/2000/svg", s = document.createElementNS(ns, "svg"), u = document.createElementNS(ns, "use");
    s.setAttribute("class", "gw-icon " + (cls || "")); s.setAttribute("aria-hidden", "true"); u.setAttribute("href", "/static/img/icons.svg#i-" + name); s.appendChild(u); return s;
  }
  async function api(method, url, body) {
    const r = await fetch(url, { method, headers: { Accept: "application/json", "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const err = new Error(typeof data.detail === "string" ? data.detail : "No se pudo completar la acción."); err.status = r.status; throw err; }
    return data;
  }
  const qs = (obj) => { const p = new URLSearchParams(); Object.keys(obj).forEach((k) => { const v = obj[k]; if (v !== "" && v != null && v !== false) p.set(k, v === true ? "true" : v); }); const s = p.toString(); return s ? "?" + s : ""; };
  const plural = (n, one, many) => n + " " + (n === 1 ? one : many);

  function utc(iso) { return new Date(iso + (/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? "" : "Z")); }
  function fmtDateTime(iso) { return iso ? utc(iso).toLocaleString("es-CO", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : ""; }
  function fmtDay(iso) { if (!iso) return ""; const d = /^\d{4}-\d\d-\d\d$/.test(iso) ? new Date(iso + "T12:00:00") : utc(iso); return d.toLocaleDateString("es-CO", { day: "2-digit", month: "short", year: "numeric" }); }
  function fmtMoney(amount, currency) {
    const n = Number(amount);
    if (!isFinite(n)) return "—";
    return (currency || "COP") + " " + n.toLocaleString("es-CO", { maximumFractionDigits: 0 });
  }
  /* <input type="datetime-local"> trabaja en hora local; el servidor guarda UTC: se manda ISO con «Z». */
  function localToIso(value) { if (!value) return null; const d = new Date(value); return isNaN(d.getTime()) ? null : d.toISOString(); }

  function stateBlock(kind, title, text, retry, iconName) {
    const box = el("div", "gw-state" + (kind === "error" ? " gw-state--error" : "")), ic = el("div", "gw-state__icon");
    ic.appendChild(icon(kind === "error" ? "error" : (iconName || "inbox"))); box.appendChild(ic);
    box.appendChild(el("p", "gw-state__title", title)); if (text) box.appendChild(el("p", "gw-state__text", text));
    if (retry) { const b = el("button", "gw-btn gw-btn--primary", "Reintentar"); b.type = "button"; b.addEventListener("click", retry); box.appendChild(b); }
    return box;
  }
  function dialog(cfg) { const d = window.openGwDialog(cfg); d.dlg.classList.add("crm-dialog"); return d; }

  function field(id, label, control) {
    const w = el("div", "gw-field"), l = el("label", "gw-label", label); l.htmlFor = id; control.id = id; w.appendChild(l); w.appendChild(control); return w;
  }
  function input(type, max) { const i = el("input", "gw-input"); i.type = type; if (max) i.maxLength = max; i.autocomplete = "off"; return i; }
  function select(options, first) {
    const s = el("select", "gw-select"); if (first != null) s.appendChild(new Option(first, ""));
    options.forEach((o) => s.appendChild(new Option(o.label, o.value))); return s;
  }
  function errorBox() {
    const a = el("div", "gw-alert gw-alert--err"); a.setAttribute("role", "alert"); a.hidden = true; a.appendChild(el("div", "gw-alert__body"));
    a.show = (t) => { a.hidden = false; a.firstChild.textContent = t; }; a.clear = () => { a.hidden = true; }; return a;
  }

  /* Menú «Más» / «Mover a…» con el patrón .gw-menu de la plataforma: se abre con clic o teclado y se cierra al elegir o al hacer clic afuera. */
  function menu(label, items, ariaLabel) {
    const wrap = el("div", "gw-menu"), toggle = el("button", "gw-btn gw-btn--secondary gw-btn--sm", label);
    toggle.type = "button"; toggle.dataset.menuToggle = ""; toggle.setAttribute("aria-haspopup", "true"); toggle.setAttribute("aria-expanded", "false"); if (ariaLabel) toggle.setAttribute("aria-label", ariaLabel);
    wrap.appendChild(toggle);
    const panel = el("div", "gw-menu__panel"); panel.hidden = true; panel.setAttribute("role", "group");
    items.forEach((it) => { const b = el("button", "gw-menu__item", it.label); b.type = "button"; Object.keys(it.data || {}).forEach((k) => { b.dataset[k] = it.data[k]; }); panel.appendChild(b); });
    wrap.appendChild(panel); return wrap;
  }
  function closeMenus(scope) {
    (scope || document).querySelectorAll(".gw-menu").forEach((m) => { const p = m.querySelector(".gw-menu__panel"); if (p) p.hidden = true; const t = m.querySelector("[data-menu-toggle]"); if (t) t.setAttribute("aria-expanded", "false"); });
  }
  /* Un solo oyente por pantalla: devuelve true si el clic fue en un botón de menú (ya lo atendió). */
  function menuClick(e) {
    const t = e.target.closest("[data-menu-toggle]");
    if (t) { const wrap = t.closest(".gw-menu"), panel = wrap.querySelector(".gw-menu__panel"), open = panel.hidden; closeMenus(); panel.hidden = !open; t.setAttribute("aria-expanded", open ? "true" : "false"); return true; }
    return false;
  }
  document.addEventListener("click", (e) => { if (!e.target.closest || !e.target.closest(".gw-menu")) closeMenus(); });

  let metaCache = null, ownersCache = null;
  async function meta() { if (!metaCache) metaCache = await api("GET", "/api/crm/pipeline/meta"); return metaCache; }
  async function owners() { if (!ownersCache) ownersCache = (await api("GET", "/api/crm/meta")).owners; return ownersCache; }

  /* ---------------------------------------------------------------- actividades (se usan en la ficha de oportunidad y en los leads) */
  const toInputLocal = (iso) => { if (!iso) return ""; const d = utc(iso), p = (n) => String(n).padStart(2, "0"); return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + "T" + p(d.getHours()) + ":" + p(d.getMinutes()); };

  async function activityForm(link, existing, onDone) {
    const m = await meta(), own = await owners();
    const body = el("form", "gw-stack"); body.noValidate = true;
    const err = errorBox(); body.appendChild(err);
    const kind = select(m.activity_kinds.filter((k) => k.key !== "note" || !existing).map((k) => ({ value: k.key, label: k.label })));
    const subject = input("text", 200), when = input("datetime-local"), remind = input("datetime-local"), desc = el("textarea", "gw-textarea"); desc.rows = 3; desc.maxLength = 20000;
    const pick = !!(link && link.pick && !existing), accPick = pick ? window.CRMX.accountPicker("act_account") : null, oppPick = pick ? window.CRMX.opportunityPicker("act_opp", () => accPick.value) : null;
    if (pick) { body.appendChild(window.CRMX.pickerField("act_account", "¿Con qué cuenta?", accPick, "Toda tarea va ligada a una cuenta. Escribe parte del nombre o el código y elige de la lista.")); body.appendChild(window.CRMX.pickerField("act_opp", "Oportunidad (opcional)", oppPick, "Solo si la tarea es de una oportunidad en particular.")); }
    body.appendChild(field("act_kind", "Tipo", kind)); body.appendChild(field("act_subject", "Asunto", subject)); body.appendChild(field("act_due", "Fecha y hora", when));
    body.appendChild(field("act_remind", "Recordar antes (opcional)", remind)); body.appendChild(field("act_desc", "Detalle (opcional)", desc));
    const hint = el("p", "gw-hint", "No escribas datos personales de terceros en el asunto ni en el detalle: ese texto es libre."); body.appendChild(hint);
    if (existing) { kind.value = existing.kind; subject.value = existing.subject; when.value = toInputLocal(existing.due_at); remind.value = toInputLocal(existing.remind_at); desc.value = existing.description || ""; kind.disabled = true; }
    const d = dialog({ title: existing ? "Editar actividad" : (pick ? "Nueva tarea" : "Programar actividad"), bodyHtml: "", onEscape: () => d.close(),
      buttons: [{ id: "actCancel", cls: "gw-btn--secondary", label: "Cancelar" }, { id: "actSave", cls: "gw-btn--primary", label: existing ? "Guardar" : (pick ? "Crear tarea" : "Programar") }] });
    d.dlg.querySelector(".gw-modal__body").replaceChildren(body);
    d.dlg.querySelector("#actCancel").addEventListener("click", () => d.close());
    if (pick && link.due) when.value = link.due + "T09:00";          // «+ tarea» desde un día del calendario: ya trae la fecha
    (pick ? accPick : subject).focus();
    const save = () => busy(d.dlg.querySelector("#actSave"), async () => {
      err.clear();
      if (pick && !accPick.value) { err.show("Elige la cuenta de la lista que aparece al escribir."); return; }
      const payload = { subject: subject.value.trim(), description: desc.value.trim(), due_at: localToIso(when.value), remind_at: localToIso(remind.value) };
      try {
        if (existing) { payload.updated_at = existing.updated_at; await api("PUT", "/api/crm/activities/" + existing.id, payload); }
        else { payload.kind = kind.value; if (pick) { payload.account_id = Number(accPick.value); if (oppPick.value) payload.opportunity_id = Number(oppPick.value); } else Object.assign(payload, link); await api("POST", "/api/crm/activities", payload); }
        d.close(); showToast(existing ? "Cambios guardados." : "Actividad programada.", "success"); onDone();
      } catch (e) { err.show(e.message); }
    });
    d.dlg.querySelector("#actSave").addEventListener("click", save);
    if (pick) d.dlg.querySelector(".gw-modal__body").appendChild(el("p", "gw-hint", "Tipos: Llamada, Tarea (comunicado, correo, trámite) o Reunión."));
    body.addEventListener("submit", (ev) => { ev.preventDefault(); save(); });
  }

  async function completeForm(a, onDone) {
    const m = await meta();
    const body = el("form", "gw-stack"); body.noValidate = true; const err = errorBox(); body.appendChild(err);
    const result = select(m.results.map((r) => ({ value: r.key, label: r.label })), "Sin resultado");
    body.appendChild(field("act_result", "¿Cómo salió?", result));
    const d = dialog({ title: "Cerrar actividad", bodyHtml: "", onEscape: () => d.close(),
      buttons: [{ id: "cmpCancel", cls: "gw-btn--secondary", label: "Cancelar" }, { id: "cmpSave", cls: "gw-btn--primary", label: "Marcar como hecha" }] });
    d.dlg.querySelector(".gw-modal__body").replaceChildren(body);
    d.dlg.querySelector("#cmpCancel").addEventListener("click", () => d.close());
    const save = () => busy(d.dlg.querySelector("#cmpSave"), async () => {
      try { await api("POST", "/api/crm/activities/" + a.id + "/complete", { result: result.value || null }); d.close(); showToast("Actividad cerrada.", "success"); onDone(); } catch (e) { err.show(e.message); }
    });
    d.dlg.querySelector("#cmpSave").addEventListener("click", save);
    body.addEventListener("submit", (ev) => { ev.preventDefault(); save(); });
  }

  function activityItem(a) {
    const li = el("li", "crm-act" + (a.status !== "planned" ? " crm-act--closed" : "")); li.dataset.activityId = a.id; li._activity = a;
    const head = el("div", "crm-act__head");
    head.appendChild(el("span", "gw-badge " + (a.status === "done" ? "gw-badge--ok" : a.status === "cancelled" ? "" : "gw-badge--info"), a.kind_label));
    head.appendChild(el("strong", "crm-act__subject", a.subject));
    if (a.status === "done") head.appendChild(el("span", "gw-badge gw-badge--ok", "Hecha"));
    if (a.status === "cancelled") head.appendChild(el("span", "gw-badge", "Cancelada"));
    li.appendChild(head);
    const meta2 = [];
    if (a.due_at) meta2.push((a.status === "planned" ? "Para el " : "Era para el ") + fmtDateTime(a.due_at));
    if (a.done_at) meta2.push("Cerrada el " + fmtDateTime(a.done_at));
    if (a.result_label) meta2.push("Resultado: " + a.result_label);
    if (a.owner_name) meta2.push("Responsable: " + a.owner_name);
    if (meta2.length) li.appendChild(el("p", "crm-act__meta", meta2.join(" · ")));
    if (a.description) li.appendChild(el("p", "crm-act__body", a.description));
    if (a.status === "planned") {
      const row = el("div", "crm-act__actions");
      [["done", "Marcar hecha"], ["edit", "Editar"], ["cancel", "Cancelar"]].forEach(([act, label]) => { const b = el("button", "gw-btn gw-btn--secondary gw-btn--sm", label); b.type = "button"; b.dataset.act = act; row.appendChild(b); });
      li.appendChild(row);
    }
    return li;
  }

  /* Línea de actividades dentro de `box` para una liga ({opportunity_id: 3} o {lead_id: 5}). Devuelve {reload}. */
  function activityList(box, link, onChange) {
    const list = el("ol", "crm-acts"); box.replaceChildren(list);
    async function reload() {
      try {
        const data = await api("GET", "/api/crm/activities" + qs(link));
        list.replaceChildren();
        if (!data.items.length) { list.appendChild(el("li", "gw-hint", "Todavía no hay actividades. Programa la próxima llamada, tarea o reunión.")); }
        data.items.forEach((a) => list.appendChild(activityItem(a)));
      } catch (e) { box.replaceChildren(stateBlock("error", "No se pudieron cargar las actividades", e.message, reload)); }
      if (onChange) onChange();
    }
    box.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-act]"); if (!b) return;
      const li = b.closest(".crm-act"), a = li._activity;
      if (b.dataset.act === "done") return completeForm(a, reload);
      if (b.dataset.act === "edit") return activityForm(link, a, reload);
      if (b.dataset.act === "cancel") {
        if (!await showConfirm("", { variant: "warning", title: "Cancelar actividad", text: "La actividad se marca como cancelada y deja de contar como pendiente.", confirmLabel: "Cancelar actividad" })) return;
        try { await api("POST", "/api/crm/activities/" + a.id + "/cancel"); showToast("Actividad cancelada.", "success"); reload(); } catch (err) { showToast(err.message, "error"); }
      }
    });
    reload();
    return { reload, schedule: () => activityForm(link, null, reload) };
  }


  window.CRMX = { $, el, icon, api, qs, plural, fmtDateTime, fmtDay, fmtMoney, localToIso, stateBlock, dialog, field, input, select, errorBox, menu, closeMenus, menuClick, meta, owners, busy, activityList, activityForm, completeForm };
})();
