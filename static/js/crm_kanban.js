/* CRM - Oportunidades (C2): tablero Kanban y lista. Se carga al abrir la pantalla, al pulsar «Buscar» y al mover una tarjeta; no hay sondeos ni temporizadores.
   Arrastrar con el ratón Y «Mover a…» (teclado y pantalla táctil) hacen exactamente lo mismo. Si el servidor rechaza el cambio (otra persona movió la tarjeta, error de red) se avisa y el tablero se recarga. */
(function () {
  "use strict";
  const X = window.CRMX, root = document.getElementById("oppRoot");
  if (!X || !root) return;
  const { $, el, icon, api, qs, fmtMoney, fmtDay, stateBlock, busy } = X;
  const canAdmin = root.dataset.canAdmin === "1";
  const PAGER_KEY = "crm_oportunidades";
  const f = { q: $("oppQ"), owner: $("oppOwner"), currency: $("oppCurrency"), from: $("oppFrom"), to: $("oppTo"), noAct: $("oppNoAct"), archived: $("oppArchived"), pipe: $("oppPipe") };
  let view = "board", pipelines = [], owners = {}, seq = 0, listPage = 1, board = null;

  /* ---------------------------------------------------------------- estado en la dirección */
  function readUrl() {
    const p = new URLSearchParams(window.location.search);
    f.q.value = p.get("q") || ""; f.currency.value = p.get("currency") || ""; f.from.value = p.get("from") || ""; f.to.value = p.get("to") || "";
    f.noAct.checked = p.get("sin_actividad") === "1"; if (f.archived) f.archived.checked = p.get("archived") === "1";
    f.owner.dataset.want = p.get("owner") || ""; f.pipe.dataset.want = p.get("pipeline") || "";
    view = p.get("vista") === "lista" ? "list" : "board"; listPage = Math.max(1, parseInt(p.get("page") || "1", 10) || 1);
  }
  function writeUrl() {
    const p = new URLSearchParams(), set = (k, v) => { if (v) p.set(k, v); };
    set("q", f.q.value.trim()); set("owner", f.owner.value); set("currency", f.currency.value); set("from", f.from.value); set("to", f.to.value); set("pipeline", f.pipe.value);
    if (f.noAct.checked) p.set("sin_actividad", "1"); if (f.archived && f.archived.checked) p.set("archived", "1");
    if (view === "list") { p.set("vista", "lista"); if (listPage > 1) p.set("page", String(listPage)); }
    const s = p.toString();
    try { window.history.replaceState(null, "", window.location.pathname + (s ? "?" + s : "")); } catch (e) { /* sin historial */ }
  }
  function filterQuery() {
    return { q: f.q.value.trim(), owner_id: f.owner.value, currency: f.currency.value, close_from: f.from.value, close_to: f.to.value, no_activity: f.noAct.checked, archived: !!(f.archived && f.archived.checked) };
  }
  const anyFilter = () => { const q = filterQuery(); return !!(q.q || q.owner_id || q.currency || q.close_from || q.close_to || q.no_activity || q.archived); };

  /* ---------------------------------------------------------------- tablero */
  function sumLines(col) {
    if (!col.totals.length) return [el("p", "gw-kanban__sum", "Sin oportunidades")];
    return col.totals.map((t) => el("p", "gw-kanban__sum", fmtMoney(t.amount, t.currency) + " · ponderado " + fmtMoney(t.weighted, t.currency)));
  }
  function card(c, col) {
    const a = el("article", "gw-kcard"); a.draggable = !c.archived; a.dataset.id = c.id; a.dataset.updated = c.updated_at; a.dataset.stage = col.id;
    const h = el("h4", "gw-kcard__title"), link = el("a", null, c.name); link.href = "/crm/oportunidades/" + c.id; link.draggable = false; h.appendChild(link); a.appendChild(h);
    a.appendChild(el("p", "gw-kcard__sub", c.code + " · " + (c.account_name || "")));
    a.appendChild(el("p", "gw-kcard__amount", fmtMoney(c.amount, c.currency)));
    const meta = el("p", "gw-kcard__meta");
    meta.appendChild(el("span", null, c.probability + " %"));
    if (c.expected_close) meta.appendChild(el("span", null, "Cierre " + fmtDay(c.expected_close)));
    meta.appendChild(el("span", null, c.owner_name || "Sin responsable"));
    a.appendChild(meta);
    if (c.no_next_activity) { const flag = el("p", "gw-kcard__flag"); flag.appendChild(icon("alert", "gw-icon--sm")); flag.appendChild(document.createTextNode("Sin próxima actividad")); a.appendChild(flag); }
    else if (c.next_activity_at && c.outcome === "open") a.appendChild(el("p", "gw-kcard__meta", "Próxima: " + X.fmtDateTime(c.next_activity_at)));
    if (c.archived) a.appendChild(el("span", "gw-badge", "Archivada"));
    else {
      const foot = el("div", "gw-kcard__foot");
      const targets = board.columns.filter((s) => s.id !== col.id).map((s) => ({ label: s.name, data: { move: s.id } }));
      const m = X.menu("Mover a…", targets, "Mover " + c.name + " a otra etapa"); m.querySelector("[data-menu-toggle]").classList.add("gw-kcard__move"); foot.appendChild(m); a.appendChild(foot);
    }
    return a;
  }
  function column(col) {
    const s = el("section", "gw-kanban__col"); s.dataset.stageId = col.id; s.dataset.kind = col.kind; s.setAttribute("aria-label", col.name);
    const head = el("div", "gw-kanban__head"); head.appendChild(el("h3", "gw-kanban__title", col.name)); head.appendChild(el("span", "gw-kanban__count", String(col.count)));
    if (col.kind === "won") head.appendChild(el("span", "gw-badge gw-badge--ok", "Ganada")); if (col.kind === "lost") head.appendChild(el("span", "gw-badge gw-badge--warn", "Perdida"));
    sumLines(col).forEach((p) => head.appendChild(p)); s.appendChild(head);
    const body = el("div", "gw-kanban__body"); body.dataset.stageId = col.id;
    if (!col.cards.length) body.appendChild(el("p", "gw-kanban__empty", anyFilter() ? "Ninguna coincide con los filtros." : "Nada en esta etapa."));
    col.cards.forEach((c) => body.appendChild(card(c, col)));
    s.appendChild(body);
    if (col.has_more) { const more = el("button", "gw-btn gw-btn--secondary gw-kanban__more", "Ver más (" + (col.count - col.cards.length) + ")"); more.type = "button"; more.dataset.more = col.id; s.appendChild(more); }
    return s;
  }
  function drawBoard() {
    const box = $("oppBoard"); box.replaceChildren();
    const wrap = el("div", "gw-kanban"); wrap.tabIndex = 0; wrap.setAttribute("aria-label", "Columnas del tablero");
    board.columns.forEach((c) => wrap.appendChild(column(c)));
    box.appendChild(wrap);
    const note = $("oppClosedNote"); note.hidden = false;
    note.textContent = "Las columnas «Ganada» y «Perdida» muestran lo cerrado en los últimos " + board.closed_days + " días. La lista trae todo.";
  }
  async function loadBoard() {
    const mine = ++seq, box = $("oppBoard"); box.setAttribute("aria-busy", "true"); writeUrl();
    if (!box.firstChild) box.appendChild(el("p", "gw-hint", "Cargando el tablero…"));
    try {
      board = await api("GET", "/api/crm/opportunities/board" + qs(Object.assign({ pipeline_id: f.pipe.value }, filterQuery())));
      if (mine !== seq) return;
      drawBoard();
    } catch (e) { if (mine === seq) box.replaceChildren(stateBlock("error", "No se pudo cargar el tablero", e.message, loadBoard)); }
    finally { if (mine === seq) box.setAttribute("aria-busy", "false"); }
  }
  async function loadMore(stageId, btn) {
    const col = board.columns.find((c) => c.id === Number(stageId)); if (!col) return;
    await busy(btn, async () => {
      try {
        const data = await api("GET", "/api/crm/opportunities/board" + qs(Object.assign({ pipeline_id: board.pipeline.id, stage_id: stageId, offset: col.cards.length }, filterQuery())));
        const more = data.columns[0]; col.cards = col.cards.concat(more.cards); col.has_more = more.has_more; col.count = more.count;
        const sec = document.querySelector('.gw-kanban__col[data-stage-id="' + stageId + '"]'), body = sec.querySelector(".gw-kanban__body");
        more.cards.forEach((c) => body.appendChild(card(c, col)));
        if (!col.has_more) btn.remove(); else btn.textContent = "Ver más (" + (col.count - col.cards.length) + ")";
      } catch (e) { showToast(e.message, "error"); }
    });
  }

  /* ---------------------------------------------------------------- mover */
  async function move(cardEl, stageId) {
    const col = board.columns.find((c) => c.id === Number(stageId)); if (!col || String(cardEl.dataset.stage) === String(stageId)) return;
    const name = cardEl.querySelector(".gw-kcard__title a").textContent, payload = { stage_id: Number(stageId), updated_at: cardEl.dataset.updated };
    if (col.kind === "lost") {
      const reason = await showPrompt("Motivo por el que se perdió «" + window.escapeHtml(name) + "» (opcional)", { title: "Marcar como perdida", confirmLabel: "Marcar perdida" });
      if (reason === null) return; payload.lost_reason = reason.trim();
    } else if (col.kind === "won") {
      if (!await showConfirm("", { variant: "warning", title: "Marcar como ganada", text: "«" + name + "» se cierra como ganada y se crea su evento (con el cliente de la plataforma si la cuenta aún no lo es).", confirmLabel: "Ganar y crear evento" })) return;
    }
    try { await api("POST", "/api/crm/opportunities/" + cardEl.dataset.id + "/move", payload); showToast("Movida a «" + col.name + "».", "success"); }
    catch (e) { showToast(e.message, "error"); }
    loadBoard();          // totales y orden salen del servidor, también cuando falló
  }
  const boardBox = $("oppBoard");
  boardBox.addEventListener("click", (e) => {
    if (X.menuClick(e)) return;
    const mv = e.target.closest("[data-move]");
    if (mv) { const cardEl = mv.closest(".gw-kcard"); X.closeMenus(); move(cardEl, mv.dataset.move); return; }
    const more = e.target.closest("[data-more]"); if (more) loadMore(more.dataset.more, more);
  });
  let dragged = null;
  boardBox.addEventListener("dragstart", (e) => {
    const c = e.target.closest && e.target.closest(".gw-kcard"); if (!c || c.draggable === false) return;
    dragged = c; c.classList.add("is-dragging"); try { e.dataTransfer.setData("text/plain", c.dataset.id); e.dataTransfer.effectAllowed = "move"; } catch (err) { /* navegador sin dataTransfer */ }
  });
  boardBox.addEventListener("dragend", () => { if (dragged) dragged.classList.remove("is-dragging"); dragged = null; boardBox.querySelectorAll(".is-over").forEach((n) => n.classList.remove("is-over")); });
  boardBox.addEventListener("dragover", (e) => { const b = e.target.closest && e.target.closest(".gw-kanban__col"); if (!b || !dragged) return; e.preventDefault(); b.querySelector(".gw-kanban__body").classList.add("is-over"); });
  boardBox.addEventListener("dragleave", (e) => { const b = e.target.closest && e.target.closest(".gw-kanban__body"); if (b && !b.contains(e.relatedTarget)) b.classList.remove("is-over"); });
  boardBox.addEventListener("drop", (e) => {
    const b = e.target.closest && e.target.closest(".gw-kanban__col"); if (!b || !dragged) return;
    e.preventDefault(); const c = dragged, stage = b.dataset.stageId; dragged = null; c.classList.remove("is-dragging");
    boardBox.querySelectorAll(".is-over").forEach((n) => n.classList.remove("is-over"));
    move(c, stage);
  });

  /* ---------------------------------------------------------------- lista */
  function listRow(o) {
    const tr = document.createElement("tr"), cell = (label, content) => { const td = document.createElement("td"); td.dataset.label = label; if (content instanceof Node) td.appendChild(content); else td.textContent = content == null || content === "" ? "—" : content; tr.appendChild(td); };
    cell("Código", String(o.code));
    const a = el("a", "crm-name", o.name); a.href = "/crm/oportunidades/" + o.id; const w = el("div", "crm-name-wrap"); w.appendChild(a);
    if (o.outcome === "won") w.appendChild(el("span", "gw-badge gw-badge--ok", "Ganada")); if (o.outcome === "lost") w.appendChild(el("span", "gw-badge gw-badge--warn", "Perdida")); if (o.archived) w.appendChild(el("span", "gw-badge", "Archivada"));
    cell("Oportunidad", w); cell("Cuenta", o.account_name); cell("Etapa", o.stage_name); cell("Monto", fmtMoney(o.amount, o.currency)); cell("Cierre", o.expected_close ? fmtDay(o.expected_close) : ""); cell("Responsable", o.owner_name);
    return tr;
  }
  async function loadList() {
    const mine = ++seq, body = $("oppListBody"), state = $("oppListState"), pager = $("oppListPager"); writeUrl();
    try {
      const size = window.GW && GW.pageSize ? GW.pageSize(PAGER_KEY) : 20;
      const data = await api("GET", "/api/crm/opportunities" + qs(Object.assign({ pipeline_id: f.pipe.value, page: listPage, size }, filterQuery())));
      if (mine !== seq) return;
      if (!data.items.length && data.total > 0 && listPage > 1) { listPage = 1; return loadList(); }
      state.hidden = true; body.replaceChildren(); pager.replaceChildren();
      if (!data.total) { state.hidden = false; state.replaceChildren(stateBlock("empty", anyFilter() ? "Ninguna oportunidad coincide" : "Todavía no hay oportunidades", anyFilter() ? "Prueba con otra palabra o quita algún filtro." : "Crea la primera con «Nueva oportunidad».")); return; }
      data.items.forEach((o) => body.appendChild(listRow(o)));
      if (window.GW && GW.pagerBar) pager.appendChild(GW.pagerBar({ key: PAGER_KEY, total: data.total, page: data.page - 1, onPage: (i) => { listPage = i + 1; loadList(); window.scrollTo({ top: 0, behavior: "smooth" }); }, onSize: () => { listPage = 1; loadList(); } }));
    } catch (e) { if (mine === seq) { state.hidden = false; state.replaceChildren(stateBlock("error", "No se pudo cargar la lista", e.message, loadList)); } }
  }

  function setView(v) {
    view = v; $("oppViewBoard").setAttribute("aria-pressed", v === "board" ? "true" : "false"); $("oppViewList").setAttribute("aria-pressed", v === "list" ? "true" : "false");
    $("oppBoardSection").hidden = v !== "board"; $("oppListSection").hidden = v !== "list";
    (v === "board" ? loadBoard : loadList)();
  }
  $("oppViewBoard").addEventListener("click", () => { if (view !== "board") setView("board"); });
  $("oppViewList").addEventListener("click", () => { if (view !== "list") { listPage = 1; setView("list"); } });
  $("oppFilters").addEventListener("submit", (e) => { e.preventDefault(); listPage = 1; (view === "board" ? loadBoard : loadList)(); });
  [f.owner, f.currency, f.noAct, f.archived, f.pipe].forEach((n) => { if (n) n.addEventListener("change", () => { listPage = 1; (view === "board" ? loadBoard : loadList)(); }); });
  $("oppClear").addEventListener("click", () => { f.q.value = ""; f.owner.value = ""; f.currency.value = ""; f.from.value = ""; f.to.value = ""; f.noAct.checked = false; if (f.archived) f.archived.checked = false; listPage = 1; (view === "board" ? loadBoard : loadList)(); });

  /* ---------------------------------------------------------------- nueva oportunidad */
  async function newOpportunity(presetAccountId) {
    const m = await X.meta(), own = await X.owners(), pipe = pipelines.find((p) => String(p.id) === String(f.pipe.value)) || pipelines[0];
    const form = el("form", "gw-stack"); form.noValidate = true; const err = X.errorBox(); form.appendChild(err);
    const name = X.input("text", 200), amount = X.input("text", 20), curr = X.select(m.currencies.map((c) => ({ value: c, label: c }))), close = X.input("date"), start = X.input("date"), city = X.input("text", 120);
    const stage = X.select(pipe.stages.filter((s) => s.kind === "open").map((s) => ({ value: s.id, label: s.name }))), ownerSel = X.select(own.map((o) => ({ value: o.id, label: o.name })), "Yo");
    const search = X.input("search", 200), found = X.select([], "Primero busca la cuenta"); found.size = 1;
    const row = el("div", "crm-inline"); row.appendChild(search); const go = el("button", "gw-btn gw-btn--secondary", "Buscar cuenta"); go.type = "button"; row.appendChild(go);
    const accWrap = el("div", "gw-field"); const lab = el("label", "gw-label", "Cuenta"); lab.htmlFor = "no_search"; search.id = "no_search"; accWrap.appendChild(lab); accWrap.appendChild(row);
    found.id = "no_account"; found.setAttribute("aria-label", "Cuentas encontradas"); accWrap.appendChild(found);
    form.appendChild(accWrap); form.appendChild(X.field("no_name", "Nombre de la oportunidad", name));
    const r1 = el("div", "gw-fields-row gw-fields-row--2"); r1.appendChild(X.field("no_amount", "Monto", amount)); r1.appendChild(X.field("no_curr", "Moneda", curr)); form.appendChild(r1);
    const r2 = el("div", "gw-fields-row gw-fields-row--2"); r2.appendChild(X.field("no_close", "Cierre esperado", close)); r2.appendChild(X.field("no_start", "Inicio del evento", start)); form.appendChild(r2);
    const r3 = el("div", "gw-fields-row gw-fields-row--2"); r3.appendChild(X.field("no_city", "Ciudad", city)); r3.appendChild(X.field("no_stage", "Etapa inicial", stage)); form.appendChild(r3);
    form.appendChild(X.field("no_owner", "Responsable", ownerSel));
    const d = X.dialog({ title: "Nueva oportunidad", bodyHtml: "", onEscape: () => d.close(), buttons: [{ id: "noCancel", cls: "gw-btn--secondary", label: "Cancelar" }, { id: "noSave", cls: "gw-btn--primary", label: "Crear oportunidad" }] });
    d.dlg.querySelector(".gw-modal__body").replaceChildren(form); d.dlg.querySelector("#noCancel").addEventListener("click", () => d.close());
    async function lookup() {
      err.clear();
      try {
        const data = await api("GET", "/api/crm/accounts" + qs({ q: search.value.trim(), size: 20 }));
        found.replaceChildren(); if (!data.items.length) { found.appendChild(new Option("Ninguna cuenta coincide", "")); found.size = 1; return; }
        data.items.forEach((a) => found.appendChild(new Option(a.code + " · " + a.name, a.id))); found.size = Math.min(6, data.items.length + 1); found.selectedIndex = 0;
      } catch (e) { err.show(e.message); }
    }
    go.addEventListener("click", lookup); search.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); lookup(); } });
    if (presetAccountId) { try { const a = await api("GET", "/api/crm/accounts/" + presetAccountId); search.value = a.name; await lookup(); found.value = String(a.id); } catch (e) { /* queda para buscar a mano */ } }
    search.focus();
    const save = () => busy(d.dlg.querySelector("#noSave"), async () => {
      err.clear();
      if (!found.value) { err.show("Busca y elige la cuenta de la oportunidad."); return; }
      const payload = { account_id: Number(found.value), name: name.value.trim(), amount: amount.value.trim(), currency: curr.value, expected_close: close.value, event_start: start.value, city: city.value.trim(), pipeline_id: pipe.id, stage_id: Number(stage.value) };
      if (ownerSel.value) payload.owner_staff_id = Number(ownerSel.value);
      try { const o = await api("POST", "/api/crm/opportunities", payload); d.close(); window.location.href = "/crm/oportunidades/" + o.id; } catch (e) { err.show(e.message); }
    });
    d.dlg.querySelector("#noSave").addEventListener("click", save); form.addEventListener("submit", (ev) => { ev.preventDefault(); save(); });
  }
  $("oppNew").addEventListener("click", () => newOpportunity(null));

  /* ---------------------------------------------------------------- arranque */
  async function init() {
    readUrl();
    try {
      const [m, own] = await Promise.all([X.meta(), X.owners()]);
      pipelines = m.pipelines; own.forEach((o) => { owners[o.id] = o.name; });
      f.owner.replaceChildren(new Option("Todos", "")); own.forEach((o) => f.owner.appendChild(new Option(o.name, o.id))); if (f.owner.dataset.want) f.owner.value = f.owner.dataset.want;
      f.pipe.replaceChildren(); pipelines.forEach((p) => f.pipe.appendChild(new Option(p.name, p.id)));
      const def = pipelines.find((p) => p.is_default) || pipelines[0]; f.pipe.value = f.pipe.dataset.want && pipelines.some((p) => String(p.id) === f.pipe.dataset.want) ? f.pipe.dataset.want : (def ? def.id : "");
      $("oppPipeWrap").hidden = pipelines.length < 2;
    } catch (e) { /* los filtros quedan en «Todos»; el tablero muestra el error si hace falta */ }
    setView(view);
    const p = new URLSearchParams(window.location.search); if (p.get("nueva") === "1" || p.get("account_id")) newOpportunity(p.get("account_id"));
  }
  init();
})();
