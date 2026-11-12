/* CRM - Ficha de cuenta y cuenta nueva (C1b-2). Guarda con la versión (`updated_at`) que la persona vio: si alguien más la cambió, el servidor responde 409 y se muestra el aviso de recarga.
   Lo escrito por personas se pinta solo con textContent / .value. Sin onclick en línea; avisos con showToast/showConfirm. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const root = $("crmCuenta");
  if (!root) return;
  const isNew = root.dataset.accountId === "";
  const accountId = isNew ? null : root.dataset.accountId;
  const canAdmin = root.dataset.canAdmin === "1";
  const form = $("crmForm"), saveBtn = $("crmSave"), stateBox = $("crmState"), conflict = $("crmConflict"), loading = $("crmLoading");
  const busy = (btn, work) => (window.GW && GW.busy ? GW.busy(btn, work) : Promise.resolve(work()));
  let account = null, dirty = false, meta = null;

  function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function icon(name) {
    const ns = "http://www.w3.org/2000/svg", s = document.createElementNS(ns, "svg"), u = document.createElementNS(ns, "use");
    s.setAttribute("class", "gw-icon"); s.setAttribute("aria-hidden", "true"); u.setAttribute("href", "/static/img/icons.svg#i-" + name); s.appendChild(u); return s;
  }
  async function api(method, url, body) {
    const r = await fetch(url, { method, headers: { Accept: "application/json", "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const err = new Error(typeof data.detail === "string" ? data.detail : "No se pudo completar la acción."); err.status = r.status; throw err; }
    return data;
  }
  function fieldInputs() { return Array.from(form.querySelectorAll("[data-field]")); }

  /* ---------------------------------------------------------------- estados de la pantalla */
  function showError(title, text, retry) {
    loading.hidden = true; form.hidden = true; stateBox.hidden = false; stateBox.replaceChildren();
    const box = el("div", "gw-state gw-state--error"), ic = el("div", "gw-state__icon"); ic.appendChild(icon("error")); box.appendChild(ic);
    box.appendChild(el("p", "gw-state__title", title)); box.appendChild(el("p", "gw-state__text", text));
    if (retry) { const b = el("button", "gw-btn gw-btn--primary", "Reintentar"); b.type = "button"; b.addEventListener("click", retry); box.appendChild(b); }
    else { const a = el("a", "gw-btn gw-btn--secondary", "Volver a las cuentas"); a.href = "/crm"; box.appendChild(a); }
    stateBox.appendChild(box);
  }

  /* ---------------------------------------------------------------- pintar */
  function fill(a) {
    fieldInputs().forEach((i) => { const v = a[i.name]; i.value = v == null ? "" : String(v); });
    $("crmTitle").textContent = a.name;
    $("crmEyebrow").textContent = "CRM · Cuenta " + a.code;
    document.title = a.name + " | CRM | GoldenWeb 2.0";
    const badges = $("crmBadges"); badges.replaceChildren();
    badges.appendChild(el("span", "gw-badge " + (a.status === "activo" ? "gw-badge--ok" : a.status === "masivo" ? "gw-badge--info" : "gw-badge--warn"), a.status));
    if (a.is_client) badges.appendChild(el("span", "gw-badge gw-badge--info", "Cliente de la plataforma"));
    if (a.archived) badges.appendChild(el("span", "gw-badge", "Archivada"));
    const prim = $("crmPrimary");
    prim.hidden = false; prim.replaceChildren(el("strong", null, "Contacto principal: "), document.createTextNode(a.primary_contact || "todavía no tiene"));
    const m = $("crmMeta"); m.hidden = false;
    m.textContent = "Creada el " + new Date(a.created_at + (/[zZ]|[+-]\d\d:?\d\d$/.test(a.created_at) ? "" : "Z")).toLocaleDateString("es-CO") + " · código " + a.code;
    $("crmMakeClient").hidden = !!(a.is_client || a.archived);
    const lbl = $("crmArchiveLabel"); if (lbl) lbl.textContent = a.archived ? "Restaurar cuenta" : "Archivar cuenta";
    $("crmActions").hidden = false;
    saveBtn.disabled = !!a.archived;
    dirty = false;
  }
  function fillOwners(select, owners) {
    const want = select.value;
    select.replaceChildren(new Option("Sin responsable", ""));
    owners.forEach((o) => select.appendChild(new Option(o.name, String(o.id))));
    if (want) select.value = want;
  }

  /* ---------------------------------------------------------------- carga */
  async function loadMeta() {
    try {
      meta = await api("GET", "/api/crm/meta");
      fillOwners($("owner_staff_id"), meta.owners);
      const dl = $("crmTerms");
      if (dl) meta.payment_terms.forEach((t) => { const o = document.createElement("option"); o.value = t; dl.appendChild(o); });
    } catch (e) { /* sin listas: el formulario igual sirve */ }
  }
  async function loadAccount() {
    stateBox.hidden = true; conflict.hidden = true; loading.hidden = false; form.hidden = true;
    try {
      account = await api("GET", "/api/crm/accounts/" + encodeURIComponent(accountId));
      if (meta) fillOwners($("owner_staff_id"), meta.owners);
      if (account.owner_staff_id && meta && !meta.owners.some((o) => o.id === account.owner_staff_id)) $("owner_staff_id").appendChild(new Option("Responsable anterior", String(account.owner_staff_id)));
      fill(account);
      loading.hidden = true; form.hidden = false;
    } catch (e) {
      if (e.status === 404) showError("No encontramos esta cuenta", "Puede que el enlace esté mal escrito o que la hayan eliminado.");
      else showError("No se pudo cargar la ficha", e.message || "Revisa tu conexión e intenta de nuevo.", loadAccount);
    }
  }

  /* ---------------------------------------------------------------- guardar */
  function payload() {
    const out = {};
    fieldInputs().forEach((i) => { out[i.name] = i.value.trim(); });
    if ("owner_staff_id" in out) out.owner_staff_id = out.owner_staff_id || null;
    return out;
  }
  async function save(e) {
    e.preventDefault();
    const data = payload();
    if (!data.name) { const n = $("name"); n.setAttribute("aria-invalid", "true"); n.focus(); showToast("Escribe el nombre de la cuenta.", "error"); return; }
    $("name").removeAttribute("aria-invalid");
    await busy(saveBtn, async () => {
      try {
        if (isNew) {
          let created;
          try { created = await api("POST", "/api/crm/accounts", data); }
          catch (err) {
            if (err.status !== 409) throw err;
            const ok = await showConfirm("", { variant: "warning", title: "Ya hay una cuenta parecida", text: err.message, confirmLabel: "Crear de todos modos" });
            if (!ok) return;
            created = await api("POST", "/api/crm/accounts", Object.assign({}, data, { confirm_duplicate: true }));
          }
          dirty = false;
          showToast("Cuenta creada.", "success");
          window.location.href = "/crm/cuentas/" + created.id;
          return;
        }
        data.updated_at = account.updated_at;
        account = await api("PUT", "/api/crm/accounts/" + encodeURIComponent(accountId), data);
        if (meta && account.owner_staff_id && !meta.owners.some((o) => o.id === account.owner_staff_id) && !$("owner_staff_id").querySelector('option[value="' + account.owner_staff_id + '"]')) $("owner_staff_id").appendChild(new Option("Responsable anterior", String(account.owner_staff_id)));
        fill(account);
        conflict.hidden = true;
        showToast("Cambios guardados.", "success");
      } catch (err) {
        if (err.status === 409 && !isNew) { conflict.hidden = false; conflict.scrollIntoView({ block: "center" }); }
        else showToast(err.message || "No se pudo guardar.", "error");
      }
    });
  }

  /* ---------------------------------------------------------------- acciones de la cabecera */
  async function makeClient() {
    const ok = await showConfirm("", { variant: "warning", title: "Convertir en cliente de la plataforma", text: "Se crea el cliente de la plataforma con el mismo número de la cuenta y los datos de su contacto principal. Después podrás crearle eventos.", confirmLabel: "Convertir" });
    if (!ok) return;
    await busy($("crmMakeClient"), async () => {
      try { await api("POST", "/api/crm/accounts/" + encodeURIComponent(accountId) + "/make-client"); showToast("La cuenta ya es cliente de la plataforma.", "success"); await loadAccount(); }
      catch (err) { showToast(err.message || "No se pudo convertir la cuenta.", "error"); }
    });
  }
  async function toggleArchive() {
    if (!canAdmin || !account) return;
    const archiving = !account.archived;
    const ok = await showConfirm("", { variant: "warning", title: archiving ? "Archivar cuenta" : "Restaurar cuenta", confirmLabel: archiving ? "Archivar" : "Restaurar",
      text: archiving ? "La cuenta deja de salir en la lista normal, pero no se borra. Podrás restaurarla cuando quieras." : "La cuenta vuelve a la lista normal." });
    if (!ok) return;
    try { await api("POST", "/api/crm/accounts/" + encodeURIComponent(accountId) + (archiving ? "/archive" : "/restore")); showToast(archiving ? "Cuenta archivada." : "Cuenta restaurada.", "success"); await loadAccount(); }
    catch (err) { showToast(err.message || "No se pudo completar la acción.", "error"); }
  }

  /* ---------------------------------------------------------------- menú «Más» */
  function closeMenus() { document.querySelectorAll(".gw-menu").forEach((m) => { const p = m.querySelector(".gw-menu__panel"); if (p) p.hidden = true; const t = m.querySelector("[data-menu-toggle]"); if (t) t.setAttribute("aria-expanded", "false"); }); }
  document.addEventListener("click", (e) => {
    const t = e.target.closest && e.target.closest("[data-menu-toggle]");
    if (t) { const wrap = t.closest(".gw-menu"), panel = wrap.querySelector(".gw-menu__panel"), open = panel.hidden; closeMenus(); panel.hidden = !open; t.setAttribute("aria-expanded", open ? "true" : "false"); return; }
    closeMenus();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenus(); });

  /* ---------------------------------------------------------------- arranque */
  form.addEventListener("submit", save);
  form.addEventListener("input", () => { dirty = true; });
  window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
  $("crmReload").addEventListener("click", () => { dirty = false; if (isNew) window.location.reload(); else loadAccount(); });
  if (!isNew) {
    $("crmMakeClient").addEventListener("click", makeClient);
    const arch = $("crmArchive"); if (arch) arch.addEventListener("click", toggleArchive);
  }
  (async function init() { await loadMeta(); if (isNew) { loading.hidden = true; form.hidden = false; $("name").focus(); } else loadAccount(); })();
})();
