/* CRM - Ficha de oportunidad (C2). Los datos se guardan con la barra única de la pantalla (GWParams, bloque «oportunidad»); mover de etapa, crear el evento y archivar son actos inmediatos.
   Guarda con la versión (`updated_at`) que la persona vio: si otra persona guardó antes, el servidor responde 409 y se pide recargar.
   El historial se carga solo cuando se pide. Sin temporizadores ni sondeos. Lo escrito por personas se pinta con textContent / .value. */
(function () {
  "use strict";
  const X = window.CRMX, root = document.getElementById("oppDetail");
  if (!X || !root) return;
  const { $, el, api, fmtMoney, fmtDay, fmtDateTime, stateBlock, busy } = X;
  const id = root.dataset.opportunityId;
  const form = $("opForm"), inputs = () => Array.from(form.querySelectorAll("[name]"));
  let opp = null, meta = null, acts = null;

  /* Un acto inmediato (mover de etapa, ganar, archivar) vuelve a leer la ficha del servidor: si hay datos pendientes, primero se guardan (si no se pudieron guardar, el acto no sigue y no se pierde nada). */
  async function savePendingFirst() {
    if (!window.GWParams || !GWParams.hasDirty()) return true;
    const r = await GWParams.flush("oportunidad");
    if (r.failed.length) { showToast("Primero guarda los cambios de los datos: " + r.failed[0].error, "error"); return false; }
    return true;
  }

  function showError(title, text, retry) {
    $("opLoading").hidden = true; $("opMain").hidden = true; $("opActions").hidden = true; const box = $("opState"); box.hidden = false; box.replaceChildren(stateBlock("error", title, text, retry));
    if (!retry) { const a = el("a", "gw-btn gw-btn--secondary", "Volver a las oportunidades"); a.href = "/crm/oportunidades"; box.firstChild.appendChild(a); }
  }

  /* ---------------------------------------------------------------- barra de etapas */
  function stages() { const p = meta.pipelines.find((x) => x.id === opp.pipeline_id); return p ? p.stages : []; }
  function drawStagebar() {
    const bar = $("opStagebar"); bar.replaceChildren();
    const list = stages(), idx = list.findIndex((s) => s.id === opp.stage_id);
    list.forEach((s, i) => {
      const li = el("li", "gw-stagebar__step"), isCurrent = s.id === opp.stage_id;
      if (isCurrent) li.setAttribute("aria-current", "step");
      if (!isCurrent && s.kind === "open" && idx >= 0 && i < idx) li.classList.add("is-done");
      if (isCurrent && s.kind === "lost") li.classList.add("is-lost");
      if (s.kind === "open" && opp.outcome === "won") li.classList.add("is-done");
      const b = el("button"); b.type = "button"; b.dataset.stage = s.id; const live = Boolean(opp.event_id) && !opp.event_archived; const locked = live && opp.event_status !== "creado" && s.kind !== "won";          // un evento en proceso o finalizado no deja salir de «ganada»; uno «creado» sí (se archiva)
      b.disabled = isCurrent || opp.archived || locked; if (locked) b.title = "El evento ya está en proceso o finalizado: no se puede sacar de «ganada».";
      b.appendChild(el("span", null, s.name));
      b.appendChild(el("span", "gw-stagebar__state", isCurrent ? "Etapa actual" : locked ? "No disponible" : s.kind === "won" ? "Cerrar como ganada" : s.kind === "lost" ? "Cerrar como perdida" : "Mover aquí"));
      li.appendChild(b); bar.appendChild(li);
    });
    $("opStageHint").textContent = opp.outcome === "won" ? "Ganada el " + fmtDay(opp.closed_at) + "." : opp.outcome === "lost" ? "Perdida el " + fmtDay(opp.closed_at) + (opp.lost_reason ? " · Motivo: " + opp.lost_reason : ".") : "Pulsa una etapa para mover la oportunidad.";
    if (opp.event_id && !opp.event_archived) $("opStageHint").textContent += opp.event_status === "creado" ? " Su evento (" + (opp.event_code || opp.code) + ") está «Creado»: si la sacas de «Ganada», el evento se archiva y vuelve cuando la ganes otra vez." : " Como su evento (" + (opp.event_code || opp.code) + ") ya está en proceso o finalizado, no puede volver a una etapa anterior.";
    if (opp.event_id && opp.event_archived) $("opStageHint").textContent += " Su evento (" + (opp.event_code || opp.code) + ") está archivado: al ganarla otra vez se restaura.";
  }
  $("opStagebar").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-stage]"); if (!b || b.disabled) return;
    const s = stages().find((x) => x.id === Number(b.dataset.stage)), payload = { stage_id: s.id, updated_at: opp.updated_at };
    if (s.kind === "lost") { const reason = await showPrompt("Motivo por el que se perdió (opcional)", { title: "Marcar como perdida", confirmLabel: "Marcar perdida" }); if (reason === null) return; payload.lost_reason = reason.trim(); }
    else if (s.kind === "won" && !await showConfirm("", { variant: "warning", title: "Marcar como ganada", text: "La oportunidad se cierra como ganada y se crea el evento con el número " + opp.code + (opp.account_is_client ? "." : ", junto con el cliente de la plataforma (la cuenta aún no lo es)."), confirmLabel: "Ganar y crear evento" })) return;
    await busy(b, async () => {
      if (!(await savePendingFirst())) return;
      payload.updated_at = opp.updated_at;
      try { opp = await api("POST", "/api/crm/opportunities/" + id + "/move", payload); fill(); showToast("Movida a «" + s.name + "».", "success"); } catch (err) { handleError(err); }
    });
  });

  $("opBadges").addEventListener("click", async (e) => {
    const b = e.target.closest("#opMakeEvent"); if (!b) return;
    await busy(b, async () => { if (!(await savePendingFirst())) return; try { opp = await api("POST", "/api/crm/opportunities/" + id + "/win"); fill(); showToast("Evento " + opp.event.event_code + " creado.", "success"); } catch (err) { handleError(err); } });
  });

  /* ---------------------------------------------------------------- datos */
  function fill() {
    inputs().forEach((i) => { const v = i.name === "probability" ? opp.own_probability : opp[i.name]; i.value = v == null ? "" : String(v); });
    $("opTitle").textContent = opp.name; document.title = opp.name + " | CRM | Orum";
    $("opEyebrow").textContent = "CRM · Oportunidad " + opp.code;
    $("opSub").textContent = (opp.account_name || "") + " · " + fmtMoney(opp.amount, opp.currency) + " · " + opp.probability + " %";
    const badges = $("opBadges"); badges.replaceChildren();
    badges.appendChild(el("span", "gw-badge gw-badge--info", opp.stage_name));
    if (opp.outcome === "won") badges.appendChild(el("span", "gw-badge gw-badge--ok", "Ganada")); if (opp.outcome === "lost") badges.appendChild(el("span", "gw-badge gw-badge--warn", "Perdida")); if (opp.archived) badges.appendChild(el("span", "gw-badge", "Archivada"));
    if (opp.event_id && !opp.event_archived) { const ev = el("a", "gw-badge gw-badge--ok", "Ver evento " + (opp.event_code || opp.code)); ev.href = "/kiosk/" + opp.event_id; badges.appendChild(ev); }
    if (opp.outcome === "won" && !opp.event_id && !opp.archived) { const mk = el("button", "gw-btn gw-btn--primary gw-btn--sm", "Crear el evento"); mk.type = "button"; mk.id = "opMakeEvent"; badges.appendChild(mk); }
    if (opp.no_next_activity) badges.appendChild(el("span", "gw-badge gw-badge--warn", "Sin próxima actividad"));
    const link = el("a", "gw-badge", "Cuenta " + (opp.account_name || "")); link.href = "/crm/cuentas/" + opp.account_id; badges.appendChild(link);
    const lbl = $("opArchiveLabel"); if (lbl) lbl.textContent = opp.archived ? "Restaurar oportunidad" : "Archivar oportunidad";
    inputs().forEach((i) => { i.disabled = !!opp.archived; });          // archivada: no se edita (antes se bloqueaba el botón Guardar)
    drawStagebar();
  }
  function handleError(err) {
    if (err.status === 409 && /modific/i.test(err.message)) { $("opConflict").hidden = false; $("opConflict").scrollIntoView({ block: "center" }); }
    else showToast(err.message, "error");
  }
  /* Lo guarda la barra única. Lanza Error(mensaje) si falla; el conflicto de versión (409) también muestra el aviso de recarga. */
  async function saveData() {
    const body = {}; inputs().forEach((i) => { body[i.name] = i.value.trim(); });
    ["owner_staff_id", "primary_contact_id"].forEach((k) => { if (body[k] === "") body[k] = null; else body[k] = Number(body[k]); });
    body.updated_at = opp.updated_at;
    try { opp = await api("PUT", "/api/crm/opportunities/" + id, body); }
    catch (err) { if (err.status === 409 && /modific/i.test(err.message)) { $("opConflict").hidden = false; $("opConflict").scrollIntoView({ block: "center" }); } throw err; }
    $("opConflict").hidden = true; fill();
  }
  form.addEventListener("submit", (e) => { e.preventDefault(); const b = $("paramsSaveBtn"); if (b && !b.disabled) b.click(); });       // Enter en un campo = el mismo botón de la barra
  if (window.GWParams) GWParams.register({ key: "oportunidad", label: "Datos de la oportunidad", order: 10, save: saveData });
  $("opReload").addEventListener("click", () => window.location.reload());
  const arch = $("opArchive");
  if (arch) arch.addEventListener("click", async () => {
    const archiving = !opp.archived;
    if (!await showConfirm("", { variant: "warning", title: archiving ? "Archivar oportunidad" : "Restaurar oportunidad", confirmLabel: archiving ? "Archivar" : "Restaurar",
      text: archiving ? "La oportunidad deja de salir en el tablero y en la lista normal, pero no se borra." : "La oportunidad vuelve al tablero." })) return;
    await busy(arch, async () => { if (!(await savePendingFirst())) return; try { opp = await api("POST", "/api/crm/opportunities/" + id + (archiving ? "/archive" : "/restore")); fill(); showToast(archiving ? "Oportunidad archivada." : "Oportunidad restaurada.", "success"); } catch (err) { showToast(err.message, "error"); } });
  });

  /* ---------------------------------------------------------------- historial (bajo demanda) */
  const FIELD = { name: "Nombre", account_id: "Cuenta", pipeline_id: "Embudo", stage_id: "Etapa", amount: "Monto", currency: "Moneda", probability: "Probabilidad", expected_close: "Cierre esperado", opp_type: "Tipo",
    source: "Origen", next_step: "Siguiente paso", description: "Descripción", owner_staff_id: "Responsable", primary_contact_id: "Contacto principal", event_start: "Inicio del evento", city: "Ciudad",
    outcome: "Resultado", lost_reason: "Motivo de pérdida", event_id: "Evento", archived_at: "Archivada" };
  $("opHistLoad").addEventListener("click", async (e) => {
    const box = $("opHist");
    await busy(e.currentTarget, async () => {
      try {
        const rows = await api("GET", "/api/crm/opportunities/" + id + "/history"); box.replaceChildren();
        if (!rows.length) { box.appendChild(el("p", "gw-hint", "Todavía no hay cambios registrados.")); return; }
        const wrap = el("div", "gw-table-wrap"), t = el("table", "gw-table gw-table-cards crm-history"), head = el("thead"), hr = el("tr");
        ["Cuándo", "Quién", "Qué cambió"].forEach((h) => { const th = el("th", null, h); th.scope = "col"; hr.appendChild(th); }); head.appendChild(hr); t.appendChild(head);
        const body = el("tbody");
        rows.forEach((r) => {
          const tr = el("tr"), c = (label, text) => { const td = el("td", null, text); td.dataset.label = label; tr.appendChild(td); return td; };
          c("Cuándo", fmtDateTime(r.at)); c("Quién", r.by || "Sistema");
          const free = r.field === "description" || r.field === "next_step", fld = FIELD[r.field] || r.field;
          c("Qué cambió", free ? fld + " (cambió)" : fld + ": " + (r.old || "—") + " → " + (r.new || "—")).classList.add("crm-history__change"); body.appendChild(tr);
        });
        t.appendChild(body); wrap.appendChild(t); box.appendChild(wrap);
      } catch (err) { box.replaceChildren(stateBlock("error", "No se pudo cargar el historial", err.message)); }
    });
  });

  /* ---------------------------------------------------------------- arranque */
  /* Historial de cotizaciones de la oportunidad: versión, estado, total, fecha, anotación, «Ver» y «Descargar PDF» de cada una. */
  async function loadQuotes() {
    const box = $("opQuotes");
    try {
      const d = await api("GET", "/api/crm/opportunities/" + id + "/quotes"); box.replaceChildren();
      if (!d.items.length) { box.appendChild(el("p", "gw-hint", "Todavía no hay cotizaciones de esta oportunidad.")); return; }
      const ul = el("ul", "crm-history-list");
      d.items.forEach((q) => {
        const li = document.createElement("li"), head = el("div", "crm-name-wrap");
        head.appendChild(el("span", "crm-name", "Cotización " + q.number + " · versión " + q.version + (q.is_last ? " · la última" : "") + (q.archived ? " · archivada" : "")));
        head.appendChild(el("span", "crm-sub", q.stage + " · " + fmtMoney(q.total, q.currency) + " · " + fmtDateTime(q.created_at)));
        head.appendChild(el("span", "crm-sub", q.meeting_notes ? "Anotación: " + q.meeting_notes : "Sin anotación"));
        const acts2 = el("div", "crm-card-actions"), v = el("a", "gw-btn gw-btn--secondary gw-btn--sm", "Ver"), p = el("a", "gw-btn gw-btn--secondary gw-btn--sm", "Descargar PDF");
        v.href = "/crm/cotizaciones/" + q.id; v.setAttribute("aria-label", "Ver la cotización " + q.number + " versión " + q.version);
        p.href = "/api/crm/quotes/" + q.id + "/pdf"; p.target = "_blank"; p.rel = "noopener"; p.setAttribute("aria-label", "Descargar el PDF de la cotización " + q.number + " versión " + q.version);
        acts2.appendChild(v); acts2.appendChild(p); li.appendChild(head); li.appendChild(acts2); ul.appendChild(li);
      });
      box.appendChild(ul);
    } catch (e) { box.replaceChildren(stateBlock("error", "No se pudo cargar las cotizaciones", e.message, loadQuotes)); }
  }

  async function init() {
    try {
      meta = await X.meta(); const [o, own] = await Promise.all([api("GET", "/api/crm/opportunities/" + id), X.owners()]); opp = o;
      const ownerSel = $("f_owner_staff_id"); own.forEach((x) => ownerSel.appendChild(new Option(x.name, x.id)));
      try {
        const contacts = await api("GET", "/api/crm/accounts/" + opp.account_id + "/contacts"), sel = $("f_primary_contact_id");
        contacts.forEach((c) => sel.appendChild(new Option(c.full_name + (c.is_primary ? " (principal de la cuenta)" : ""), c.id)));
      } catch (e) { /* sin contactos: el campo queda en «Sin contacto» */ }
      fill(); if (window.GWParams) GWParams.markClean("oportunidad"); $("opLoading").hidden = true; $("opMain").hidden = false; $("opActions").hidden = false;
      loadQuotes();
      acts = X.activityList($("opActs"), { opportunity_id: id }, () => { /* la fecha de la próxima actividad se ve al recargar la ficha */ });
    } catch (e) { showError(e.status === 404 ? "No encontramos esta oportunidad" : "No se pudo cargar la oportunidad", e.status === 404 ? "Puede que se haya borrado. Vuelve a la lista." : e.message, e.status === 404 ? null : init); }
  }
  [$("opSchedule"), $("opSchedule2")].forEach((b) => b.addEventListener("click", () => acts && acts.schedule()));
  init();
})();
