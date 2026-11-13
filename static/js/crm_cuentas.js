/* CRM - Cuentas (C1b-2): lista con buscador, filtros y paginación. El estado vive en la dirección de la página (history.replaceState).
   Todo lo que escribió una persona se pinta con textContent (nunca con HTML armado a mano). Sin onclick en línea; los clics se resuelven por delegación. */
(function () {
  "use strict";
  const PAGER_KEY = "crm_cuentas";
  const $ = (id) => document.getElementById(id);
  const root = $("crmRoot");
  if (!root) return;
  const body = $("crmBody"), pager = $("crmPager"), stateBox = $("crmState"), results = $("crmResults");
  const fields = { q: $("crmSearch"), status: $("crmStatus"), owner: $("crmOwner"), city: $("crmCity"), archived: $("crmArchived") };
  let owners = {}, seq = 0, timer = null, page = 1;

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function icon(name, cls) {
    const ns = "http://www.w3.org/2000/svg", s = document.createElementNS(ns, "svg"), u = document.createElementNS(ns, "use");
    s.setAttribute("class", "gw-icon " + (cls || "")); s.setAttribute("aria-hidden", "true");
    u.setAttribute("href", "/static/img/icons.svg#i-" + name); s.appendChild(u);
    return s;
  }

  /* ---------------------------------------------------------------- estado en la dirección */
  function readUrl() {
    const p = new URLSearchParams(window.location.search);
    if (fields.q) fields.q.value = p.get("q") || "";
    if (fields.status) fields.status.dataset.want = p.get("status") || "";
    if (fields.owner) fields.owner.dataset.want = p.get("owner") || "";
    if (fields.city) fields.city.dataset.want = p.get("city") || "";
    if (fields.archived) fields.archived.checked = p.get("archived") === "1";
    page = Math.max(1, parseInt(p.get("page") || "1", 10) || 1);
  }
  function writeUrl() {
    const p = new URLSearchParams();
    const set = (k, v) => { if (v) p.set(k, v); };
    set("q", fields.q.value.trim()); set("status", fields.status.value); set("owner", fields.owner.value); set("city", fields.city.value);
    if (fields.archived && fields.archived.checked) p.set("archived", "1");
    if (page > 1) p.set("page", String(page));
    const qs = p.toString();
    try { window.history.replaceState(null, "", window.location.pathname + (qs ? "?" + qs : "")); } catch (e) { /* sin historial: no pasa nada */ }
    return p;
  }

  /* ---------------------------------------------------------------- estados */
  function showState(kind, title, text, action) {
    results.hidden = true; stateBox.hidden = false; stateBox.replaceChildren();
    const box = el("div", "gw-state" + (kind === "error" ? " gw-state--error" : ""));
    const ic = el("div", "gw-state__icon"); ic.appendChild(icon(kind === "error" ? "error" : "building")); box.appendChild(ic);
    box.appendChild(el("p", "gw-state__title", title)); box.appendChild(el("p", "gw-state__text", text));
    if (action) {
      const b = el("button", "gw-btn gw-btn--primary", action.label); b.type = "button"; b.addEventListener("click", action.run); box.appendChild(b);
    }
    stateBox.appendChild(box);
  }
  function hideState() { stateBox.hidden = true; stateBox.replaceChildren(); results.hidden = false; }
  function skeletonRows() {
    if (window.GW && GW.skeleton && GW.skeleton.html) body.innerHTML = GW.skeleton.html({ kind: "table", rows: 6, cols: 6 });
  }

  /* ---------------------------------------------------------------- filas */
  function cell(label, content) {
    const td = document.createElement("td"); td.dataset.label = label;
    if (content instanceof Node) td.appendChild(content); else td.textContent = content == null || content === "" ? "—" : content;
    return td;
  }
  function row(a) {
    const tr = document.createElement("tr");
    if (a.archived) tr.className = "crm-row--archived";
    tr.appendChild(cell("Código", String(a.code)));
    const name = el("a", "crm-name", a.name); name.href = "/crm/cuentas/" + a.id;
    const wrap = el("div", "crm-name-wrap"); wrap.appendChild(name);
    if (a.is_client) wrap.appendChild(el("span", "gw-badge gw-badge--info", "Cliente de la plataforma"));
    if (a.archived) wrap.appendChild(el("span", "gw-badge", "Archivada"));
    tr.appendChild(cell("Cuenta", wrap));
    const st = el("span", "gw-badge " + (a.status === "activo" ? "gw-badge--ok" : a.status === "masivo" ? "gw-badge--info" : "gw-badge--warn"), a.status);
    tr.appendChild(cell("Estado", st));
    tr.appendChild(cell("Ciudad", a.city));
    tr.appendChild(cell("Responsable", a.owner_staff_id ? (owners[a.owner_staff_id] || "Responsable anterior") : "Sin responsable"));
    tr.appendChild(cell("Contacto principal", a.primary_contact));
    return tr;
  }

  function draw(data) {
    hideState();
    body.replaceChildren();
    data.items.forEach((a) => body.appendChild(row(a)));
    pager.replaceChildren();
    if (window.GW && GW.pagerBar) {
      pager.appendChild(GW.pagerBar({ key: PAGER_KEY, total: data.total, page: data.page - 1,
        onPage: (i) => { page = i + 1; load(); window.scrollTo({ top: 0, behavior: "smooth" }); },
        onSize: () => { page = 1; load(); } }));
    }
  }

  function filtered() { return fields.q.value.trim() || fields.status.value || fields.owner.value || fields.city.value; }

  /* ---------------------------------------------------------------- carga */
  async function load() {
    const mine = ++seq;
    const p = writeUrl();
    const api = new URLSearchParams();
    if (p.get("q")) api.set("q", p.get("q"));
    ["status", "city"].forEach((k) => { if (p.get(k)) api.set(k, p.get(k)); });
    if (p.get("owner")) api.set("owner_id", p.get("owner"));
    if (p.get("archived")) api.set("archived", "true");
    api.set("page", String(page)); api.set("size", String(window.GW && GW.pageSize ? GW.pageSize(PAGER_KEY) : 20));
    results.setAttribute("aria-busy", "true");
    if (!body.querySelector("tr:not(.gw-sk)")) skeletonRows();
    try {
      const r = await fetch("/api/crm/accounts?" + api.toString(), { headers: { Accept: "application/json" } });
      if (mine !== seq) return;
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || "No se pudo cargar la lista.");
      if (!data.items.length && data.total > 0 && page > 1) { page = 1; return load(); }
      if (!data.total) {
        pager.replaceChildren();
        showState("empty", filtered() ? "Ninguna cuenta coincide" : "Todavía no hay cuentas",
          filtered() ? "Prueba con otra palabra o quita algún filtro." : "Crea la primera cuenta o espera a que se importe la base de SuiteCRM.",
          filtered() ? { label: "Quitar filtros", run: clearFilters } : { label: "Nueva cuenta", run: () => { window.location.href = "/crm/cuentas/nueva"; } });
      } else draw(data);
    } catch (e) {
      if (mine !== seq) return;
      showState("error", "No se pudo cargar la lista", (e && e.message) || "Revisa tu conexión e intenta de nuevo.", { label: "Reintentar", run: load });
    } finally {
      if (mine === seq) results.setAttribute("aria-busy", "false");
    }
  }

  function clearFilters() {
    fields.q.value = ""; fields.status.value = ""; fields.owner.value = ""; fields.city.value = "";
    if (fields.archived) fields.archived.checked = false;
    page = 1; load();
  }

  function fillSelect(select, items, first) {
    const want = select.dataset.want || select.value;
    select.replaceChildren(new Option(first, ""));
    items.forEach((it) => select.appendChild(new Option(it.label, it.value)));
    if (want && items.some((it) => String(it.value) === want)) select.value = want;
    else if (want) select.appendChild(new Option(want, want)), select.value = want;
  }

  async function init() {
    readUrl();
    skeletonRows();
    try {
      const r = await fetch("/api/crm/meta", { headers: { Accept: "application/json" } });
      const m = await r.json();
      if (!r.ok) throw new Error(m.detail || "");
      m.owners.forEach((o) => { owners[o.id] = o.name; });
      fillSelect(fields.status, m.statuses.map((s) => ({ value: s, label: s.charAt(0).toUpperCase() + s.slice(1) })), "Todos");
      fillSelect(fields.owner, m.owners.map((o) => ({ value: o.id, label: o.name })), "Todos");
      fillSelect(fields.city, m.cities.map((c) => ({ value: c, label: c })), "Todas");
    } catch (e) { /* los filtros quedan con «Todos»; la lista igual intenta cargar */ }
    load();
  }

  fields.q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { page = 1; load(); }, 300); });
  fields.q.addEventListener("keydown", (e) => { if (e.key === "Enter") { clearTimeout(timer); page = 1; load(); } });
  [fields.status, fields.owner, fields.city, fields.archived].forEach((f) => { if (f) f.addEventListener("change", () => { page = 1; load(); }); });
  init();
})();
