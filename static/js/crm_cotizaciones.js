/* CRM - Cotizaciones (C3): lista con filtros, filtros guardados, nueva cotización y exportación (admin). Sin temporizadores ni sondeos: se carga al abrir y al pulsar «Buscar».
   Lo escrito por personas se pinta con textContent / .value. El texto de búsqueda NO se guarda en los filtros (podría ser el nombre de una persona). */
(function () {
  "use strict";
  const X = window.CRMX, root = document.getElementById("quotesRoot");
  if (!X || !root) return;
  const { $, el, api, qs, stateBlock, busy, dialog, field, input, select, errorBox } = X;
  const canAdmin = root.dataset.canAdmin === "1", PAGER_KEY = "crm_quotes";
  const f = { q: $("quoteQ"), stage: $("quoteStage"), archived: $("quoteArchived"), saved: $("quoteSaved") };
  const STAGE = { borrador: "Borrador", enviada: "Enviada", negociada: "Negociada", aprobada: "Aprobada", rechazada: "Rechazada", vencida: "Vencida" };
  const BADGE = { borrador: "", enviada: "gw-badge--info", negociada: "gw-badge--info", aprobada: "gw-badge--ok", rechazada: "gw-badge--warn", vencida: "gw-badge--warn" };
  const money = (v, c) => c + " " + Number(v).toLocaleString("es-CO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  let page = 1, seq = 0, savedFilters = [];

  function readUrl() { const p = new URLSearchParams(window.location.search); f.q.value = p.get("q") || ""; f.stage.dataset.want = p.get("stage") || ""; if (f.archived) f.archived.checked = p.get("archived") === "1"; page = Math.max(1, parseInt(p.get("page") || "1", 10) || 1); }
  function writeUrl() { const p = new URLSearchParams(), set = (k, v) => { if (v) p.set(k, v); }; set("q", f.q.value.trim()); set("stage", f.stage.value); if (f.archived && f.archived.checked) p.set("archived", "1"); if (page > 1) p.set("page", String(page)); const s = p.toString(); try { window.history.replaceState(null, "", window.location.pathname + (s ? "?" + s : "")); } catch (e) { /* sin historial */ } }
  const filtered = () => !!(f.q.value.trim() || f.stage.value || (f.archived && f.archived.checked));

  function row(q) {
    const tr = document.createElement("tr"), cell = (label, content) => { const td = document.createElement("td"); td.dataset.label = label; if (content instanceof Node) td.appendChild(content); else td.textContent = content == null || content === "" ? "—" : content; tr.appendChild(td); return td; };
    cell("Número", "N.º " + q.number + (q.version > 1 ? " · v" + q.version : ""));
    const who = el("div", "crm-name-wrap"), a = el("a", "crm-name", q.title); a.href = "/crm/cotizaciones/" + q.id; who.appendChild(a); who.appendChild(el("span", "crm-sub", q.account_name || "")); cell("Cotización", who);
    const sw = el("div", "crm-name-wrap"); sw.appendChild(el("span", "gw-badge " + (BADGE[q.stage] || ""), STAGE[q.stage] || q.stage)); if (q.expired) sw.appendChild(el("span", "gw-badge gw-badge--warn", "Vencida")); if (q.archived) sw.appendChild(el("span", "gw-badge", "Archivada")); cell("Etapa", sw);
    cell("Total", money(q.total, q.currency)); cell("Válida hasta", q.valid_until ? X.fmtDay(q.valid_until) : "");
    const td = cell("Acciones", ""); td.classList.add("crm-actions-cell");
    const open = el("a", "gw-btn gw-btn--secondary gw-btn--sm", "Abrir"); open.href = "/crm/cotizaciones/" + q.id; td.appendChild(open);
    const pdf = el("a", "gw-btn gw-btn--secondary gw-btn--sm", "PDF"); pdf.href = "/api/crm/quotes/" + q.id + "/pdf"; pdf.target = "_blank"; pdf.rel = "noopener"; pdf.setAttribute("aria-label", "Descargar el PDF de la cotización " + q.number); td.appendChild(pdf);
    return tr;
  }
  async function load() {
    const mine = ++seq, body = $("quoteBody"), state = $("quoteState"), results = $("quoteResults"), pager = $("quotePager"); writeUrl(); results.setAttribute("aria-busy", "true");
    try {
      const size = window.GW && GW.pageSize ? GW.pageSize(PAGER_KEY) : 20;
      const data = await api("GET", "/api/crm/quotes" + qs({ q: f.q.value.trim(), stage: f.stage.value, archived: !!(f.archived && f.archived.checked), page, size }));
      if (mine !== seq) return;
      if (!data.items.length && data.total > 0 && page > 1) { page = 1; return load(); }
      body.replaceChildren(); pager.replaceChildren();
      if (!data.total) { results.hidden = true; state.hidden = false; state.replaceChildren(stateBlock("empty", filtered() ? "Ninguna cotización coincide" : "Todavía no hay cotizaciones", filtered() ? "Prueba con otra palabra o quita algún filtro." : "Crea la primera con «Nueva cotización».", null, "sheet")); return; }
      results.hidden = false; state.hidden = true; data.items.forEach((q) => body.appendChild(row(q)));
      if (window.GW && GW.pagerBar) pager.appendChild(GW.pagerBar({ key: PAGER_KEY, total: data.total, page: data.page - 1, onPage: (i) => { page = i + 1; load(); window.scrollTo({ top: 0, behavior: "smooth" }); }, onSize: () => { page = 1; load(); } }));
    } catch (e) { if (mine === seq) { results.hidden = true; state.hidden = false; state.replaceChildren(stateBlock("error", "No se pudo cargar la lista", e.message, load)); } }
    finally { if (mine === seq) results.setAttribute("aria-busy", "false"); }
  }

  /* ---------------------------------------------------------------- filtros guardados */
  async function loadSaved() {
    try {
      savedFilters = (await api("GET", "/api/crm/filters?scope=cotizaciones")).items; f.saved.replaceChildren(new Option("Elegir…", ""));
      savedFilters.forEach((s) => f.saved.appendChild(new Option(s.name + (s.mine ? "" : " (compartido)"), String(s.id))));
    } catch (e) { /* los filtros guardados son una ayuda: sin ellos la pantalla sigue */ }
  }
  f.saved.addEventListener("change", () => { const s = savedFilters.find((x) => String(x.id) === f.saved.value); if (!s) return; f.stage.value = s.filters.stage || ""; page = 1; load(); });
  $("quoteSaveFilter").addEventListener("click", async () => {
    if (!f.stage.value) { showToast("Elige una etapa para guardar el filtro. El texto de búsqueda no se guarda.", "warning"); return; }
    const name = await showPrompt("Ponle un nombre al filtro (se guarda la etapa elegida).", { title: "Guardar filtro", confirmLabel: "Guardar" }); if (!name) return;
    try { await api("POST", "/api/crm/filters", { scope: "cotizaciones", name, filters: { stage: f.stage.value } }); showToast("Filtro guardado.", "success"); loadSaved(); } catch (e) { showToast(e.message, "error"); }
  });

  /* ---------------------------------------------------------------- nueva cotización */
  async function newQuote() {
    const search = input("search", 100), found = select([], "Escribe y pulsa «Buscar cuenta»"), title = input("text", 200), err = errorBox();
    const find = el("button", "gw-btn gw-btn--secondary gw-btn--sm", "Buscar cuenta"); find.type = "button";
    const body = el("div", "gw-stack"); body.appendChild(err);
    body.appendChild(field("nqSearch", "Cuenta (nombre o código)", search)); body.appendChild(find); body.appendChild(field("nqFound", "Cuenta elegida", found)); body.appendChild(field("nqTitle", "Título de la cotización", title));
    const d = dialog({ title: "Nueva cotización", bodyHtml: "", onEscape: () => d.close(), buttons: [{ id: "nqCancel", cls: "gw-btn--secondary", label: "Cancelar" }, { id: "nqSave", cls: "gw-btn--primary", label: "Crear" }] });
    d.dlg.querySelector(".gw-modal__body").replaceChildren(body);
    const lookup = async () => { try { const r = await api("GET", "/api/crm/accounts" + qs({ q: search.value.trim(), size: 20 })); found.replaceChildren(new Option(r.items.length ? "Elige una cuenta…" : "Sin resultados", "")); r.items.forEach((a) => found.appendChild(new Option(a.name + " (" + a.code + ")", String(a.id)))); } catch (e) { err.show(e.message); } };
    find.addEventListener("click", lookup); search.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); lookup(); } });
    d.dlg.querySelector("#nqCancel").addEventListener("click", () => d.close());
    d.dlg.querySelector("#nqSave").addEventListener("click", async (e) => {
      err.clear(); if (!found.value || !title.value.trim()) { err.show("Elige la cuenta y escribe un título."); return; }
      try { await busy(e.currentTarget, async () => { const q = await api("POST", "/api/crm/quotes", { account_id: Number(found.value), title: title.value.trim() }); window.location.href = "/crm/cotizaciones/" + q.id; }); } catch (e2) { err.show(e2.message); }
    });
  }

  /* ---------------------------------------------------------------- arranque */
  $("quoteFilters").addEventListener("submit", (e) => { e.preventDefault(); page = 1; load(); });
  $("quoteClear").addEventListener("click", () => { f.q.value = ""; f.stage.value = ""; f.saved.value = ""; if (f.archived) f.archived.checked = false; page = 1; load(); });
  $("quoteNew").addEventListener("click", newQuote);
  const exp = $("quoteExport"); if (exp) exp.addEventListener("click", () => { window.location.href = "/api/crm/export/cotizaciones"; });
  (async () => {
    readUrl();
    try { const m = await api("GET", "/api/crm/quotes/meta"); m.stages.forEach((s) => f.stage.appendChild(new Option(STAGE[s] || s, s))); f.stage.value = f.stage.dataset.want || ""; } catch (e) { /* la lista se intenta igual */ }
    loadSaved(); load();
  })();
})();
