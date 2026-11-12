/* CRM - Ficha de cuenta: pestañas Contactos, Notas e Historial y la supresión de datos de un contacto (Ley 1581), con adelanto de lo que se borrará y aviso persistente
   de lo que hay que revisar a mano después. Usa window.CRM (crm_cuenta.js). Todo texto de personas se pinta con textContent/.value. Sin onclick en línea. */
(function () {
  "use strict";
  const C = window.CRM;
  if (!C) return;
  const { api, el, icon } = C;
  const $ = (id) => document.getElementById(id);
  const busy = (btn, work) => (window.GW && GW.busy ? GW.busy(btn, work) : Promise.resolve(work()));
  const TABS = ["datos", "contactos", "notas", "historial"];
  const loaded = {};
  let contactsActive = [], contactsAll = {};

  /* ---------------------------------------------------------------- pestañas */
  function select(name, focus) {
    if (TABS.indexOf(name) < 0) name = "datos";
    TABS.forEach((t) => {
      const b = $("tab_" + t), on = t === name;
      b.setAttribute("aria-selected", on ? "true" : "false"); b.tabIndex = on ? 0 : -1;
      $("panel_" + t).hidden = !on;
      if (on && focus) b.focus();
    });
    try { window.history.replaceState(null, "", window.location.pathname + window.location.search + (name === "datos" ? "" : "#" + name)); } catch (e) { /* sin historial */ }
    const loader = { contactos: loadContacts, notas: loadNotes, historial: loadHistory }[name];
    if (loader && !loaded[name]) { loaded[name] = true; loader(); }
  }
  document.querySelector(".crm-tablist").addEventListener("click", (e) => { const b = e.target.closest("[data-tab]"); if (b) select(b.dataset.tab); });
  document.querySelector(".crm-tablist").addEventListener("keydown", (e) => {
    const i = TABS.indexOf((e.target.closest("[data-tab]") || {}).dataset ? e.target.closest("[data-tab]").dataset.tab : "");
    if (i < 0 || (e.key !== "ArrowRight" && e.key !== "ArrowLeft")) return;
    e.preventDefault(); select(TABS[(i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length], true);
  });

  /* ---------------------------------------------------------------- utilidades */
  function stateBlock(kind, title, text, retry) {
    const box = el("div", "gw-state" + (kind === "error" ? " gw-state--error" : "")), ic = el("div", "gw-state__icon"); ic.appendChild(icon(kind === "error" ? "error" : "users")); box.appendChild(ic);
    box.appendChild(el("p", "gw-state__title", title)); if (text) box.appendChild(el("p", "gw-state__text", text));
    if (retry) { const b = el("button", "gw-btn gw-btn--primary", "Reintentar"); b.type = "button"; b.addEventListener("click", retry); box.appendChild(b); }
    return box;
  }
  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso + (/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? "" : "Z"));
    return d.toLocaleString("es-CO", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  }
  function dialog(cfg) { const d = window.openGwDialog(cfg); d.dlg.classList.add("crm-dialog"); return d; }

  /* ---------------------------------------------------------------- contactos */
  async function fetchContacts(archived) { return api("GET", "/api/crm/accounts/" + C.id + "/contacts" + (archived ? "?archived=true" : "")); }
  async function loadContacts() {
    const box = $("crmContacts"), archived = $("crmContactsArchived").checked;
    try {
      const list = await fetchContacts(archived);
      if (!archived) contactsActive = list;
      list.forEach((c) => { contactsAll[c.id] = c.full_name; });
      box.replaceChildren();
      if (!list.length) { box.appendChild(stateBlock("empty", archived ? "No hay contactos archivados" : "Esta cuenta todavía no tiene contactos", archived ? "" : "Agrega la primera persona: quedará como contacto principal.")); return; }
      const wrap = el("div", "crm-cards"); list.forEach((c) => wrap.appendChild(contactCard(c, archived))); box.appendChild(wrap);
    } catch (e) { box.replaceChildren(stateBlock("error", "No se pudieron cargar los contactos", e.message, loadContacts)); }
  }
  function line(label, value) { if (!value) return null; const p = el("p", "crm-card__line"); p.appendChild(el("span", "crm-card__label", label + ": ")); p.appendChild(document.createTextNode(value)); return p; }
  function contactCard(c, archivedView) {
    const card = el("article", "gw-card crm-card"); card.dataset.contactId = c.id;
    const head = el("div", "crm-card__head"), name = el("h3", "crm-card__name", c.full_name); head.appendChild(name);
    if (c.is_primary) head.appendChild(el("span", "gw-badge gw-badge--ok", "Principal"));
    if (c.archived) head.appendChild(el("span", "gw-badge", "Archivado"));
    card.appendChild(head);
    [line("Cargo", c.job_title), line("Celular", c.mobile), line("Teléfono", c.phone), line("Correo", c.email)].forEach((n) => { if (n) card.appendChild(n); });
    if (c.notes) card.appendChild(line("Notas", c.notes));
    const acts = el("div", "crm-card__actions");
    const edit = el("button", "gw-btn gw-btn--secondary gw-btn--sm", "Editar"); edit.type = "button"; edit.dataset.act = "edit"; acts.appendChild(edit);
    const menu = el("div", "gw-menu"), toggle = el("button", "gw-btn gw-btn--secondary gw-btn--sm", "Más"); toggle.type = "button"; toggle.dataset.menuToggle = ""; toggle.setAttribute("aria-haspopup", "true"); toggle.setAttribute("aria-expanded", "false"); toggle.setAttribute("aria-label", "Más acciones de " + c.full_name);
    toggle.insertBefore(icon("more"), toggle.firstChild); menu.appendChild(toggle);
    const panel = el("div", "gw-menu__panel"); panel.hidden = true; panel.setAttribute("role", "group");
    const item = (label, act) => { const b = el("button", "gw-menu__item", label); b.type = "button"; b.dataset.act = act; panel.appendChild(b); };
    if (!c.archived && !c.is_primary) item("Hacer principal", "primary");
    item(c.archived ? "Restaurar" : "Archivar", c.archived ? "restore" : "archive");
    if (C.canAdmin) item("Suprimir sus datos…", "erase");
    menu.appendChild(panel); acts.appendChild(menu); card.appendChild(acts);
    card._contact = c;
    return card;
  }
  function closeMenus() { document.querySelectorAll("#panel_contactos .gw-menu").forEach((m) => { const p = m.querySelector(".gw-menu__panel"); if (p) p.hidden = true; const t = m.querySelector("[data-menu-toggle]"); if (t) t.setAttribute("aria-expanded", "false"); }); }
  $("crmContacts").addEventListener("click", async (e) => {
    const t = e.target.closest("[data-menu-toggle]");
    if (t) { const wrap = t.closest(".gw-menu"), panel = wrap.querySelector(".gw-menu__panel"), open = panel.hidden; closeMenus(); panel.hidden = !open; t.setAttribute("aria-expanded", open ? "true" : "false"); return; }
    const b = e.target.closest("[data-act]"); if (!b) return;
    const card = b.closest(".crm-card"), c = card._contact; closeMenus();
    if (b.dataset.act === "edit") return contactForm(c);
    if (b.dataset.act === "erase") return eraseFlow(c);
    const url = "/api/crm/contacts/" + c.id + "/" + (b.dataset.act === "primary" ? "make-primary" : b.dataset.act);
    if (b.dataset.act === "archive" && !await showConfirm("", { variant: "warning", title: "Archivar contacto", text: "El contacto deja de salir en la lista normal, pero no se borra. Si era el principal, el siguiente activo pasa a serlo.", confirmLabel: "Archivar" })) return;
    try { await api("POST", url); showToast("Listo.", "success"); await loadContacts(); C.refreshPrimary(); } catch (err) { showToast(err.message, "error"); }
  });
  document.addEventListener("click", (e) => { if (!e.target.closest || !e.target.closest("#panel_contactos .gw-menu")) closeMenus(); });
  $("crmContactsArchived").addEventListener("change", loadContacts);
  $("crmNewContact").addEventListener("click", () => contactForm(null));

  const FIELDS = [["first_name", "Nombres", "text", 120], ["last_name", "Apellidos", "text", 120], ["job_title", "Cargo", "text", 120], ["email", "Correo", "email", 200], ["mobile", "Celular", "tel", 60], ["phone", "Teléfono fijo", "tel", 60]];
  function contactForm(c) {
    const isNew = !c;
    let html = '<form id="crmContactForm" class="gw-stack" novalidate><div class="gw-alert gw-alert--err" id="crmContactErr" role="alert" hidden><div class="gw-alert__body"></div></div><div class="gw-fields-row gw-fields-row--2">';
    FIELDS.forEach((f, i) => { html += '<div class="gw-field"><label class="gw-label" for="cf_' + f[0] + '">' + f[1] + '</label><input class="gw-input" id="cf_' + f[0] + '" type="' + f[2] + '" maxlength="' + f[3] + '" autocomplete="off"></div>'; });
    html += '</div><div class="gw-field"><label class="gw-label" for="cf_notes">Notas del contacto</label><textarea class="gw-textarea" id="cf_notes" rows="3" maxlength="20000"></textarea></div>';
    if (isNew) html += '<label class="gw-check"><input type="checkbox" id="cf_primary"> Hacer principal</label>';
    html += "</form>";
    const d = dialog({ title: isNew ? "Nuevo contacto" : "Editar contacto", bodyHtml: html, onEscape: () => d.close(),
      buttons: [{ id: "cfCancel", cls: "gw-btn--secondary", label: "Cancelar" }, { id: "cfSave", cls: "gw-btn--primary", label: isNew ? "Crear contacto" : "Guardar" }] });
    FIELDS.forEach((f) => { d.dlg.querySelector("#cf_" + f[0]).value = c && c[f[0]] ? c[f[0]] : ""; });
    d.dlg.querySelector("#cf_notes").value = c && c.notes ? c.notes : "";
    d.dlg.querySelector("#cfCancel").addEventListener("click", () => d.close());
    d.dlg.querySelector("#cf_first_name").focus();
    const err = d.dlg.querySelector("#crmContactErr");
    const save = async () => {
      const body = {}; FIELDS.forEach((f) => { body[f[0]] = d.dlg.querySelector("#cf_" + f[0]).value.trim(); }); body.notes = d.dlg.querySelector("#cf_notes").value.trim();
      if (!body.first_name && !body.last_name) { err.hidden = false; err.querySelector(".gw-alert__body").textContent = "Escribe al menos el nombre o el apellido."; return; }
      err.hidden = true;
      await busy(d.dlg.querySelector("#cfSave"), async () => {
        try {
          if (isNew) { body.make_primary = d.dlg.querySelector("#cf_primary").checked; await api("POST", "/api/crm/accounts/" + C.id + "/contacts", body); }
          else { body.updated_at = c.updated_at; await api("PUT", "/api/crm/contacts/" + c.id, body); }
          d.close(); showToast(isNew ? "Contacto creado." : "Cambios guardados.", "success"); await loadContacts(); C.refreshPrimary(); loaded.notas = false; loaded.historial = false;
        } catch (e2) { err.hidden = false; err.querySelector(".gw-alert__body").textContent = e2.message; }
      });
    };
    d.dlg.querySelector("#cfSave").addEventListener("click", save);
    d.dlg.querySelector("#crmContactForm").addEventListener("submit", (ev) => { ev.preventDefault(); save(); });
  }

  /* ---------------------------------------------------------------- supresión de datos (Ley 1581) */
  const PLURAL = (n, one, many) => n + " " + (n === 1 ? one : many);
  function eraseLines(k, done) {
    const out = ["su ficha de contacto"];
    if (k.notes) out.push(PLURAL(k.notes, "nota suya", "notas suyas"));
    if (k.changes) out.push(PLURAL(k.changes, "cambio de su historial", "cambios de su historial"));
    if (k.account_history) out.push(PLURAL(k.account_history, "cambio del historial de la cuenta que trae sus datos", "cambios del historial de la cuenta que traen sus datos"));
    if (k.account_fields) out.push(done ? PLURAL(k.account_fields, "dato de la cuenta vaciado (correo, teléfono o contacto de facturación)", "datos de la cuenta vaciados (correo, teléfono o contacto de facturación)")
      : PLURAL(k.account_fields, "dato de la cuenta que se vaciará (correo, teléfono o contacto de facturación)", "datos de la cuenta que se vaciarán (correo, teléfono o contacto de facturación)"));
    if (k.tenant_fields) out.push(PLURAL(k.tenant_fields, "dato copiado al cliente de la plataforma", "datos copiados al cliente de la plataforma"));
    return out;
  }
  function reviewLines(r) {
    const out = [];
    if (r && r.description) out.push("La descripción de la cuenta parece mencionar a esta persona.");
    if (r && r.general_notes) out.push(r.general_notes === 1 ? "1 nota general parece mencionarla." : r.general_notes + " notas generales parecen mencionarla.");
    return out;
  }
  async function eraseFlow(c) {
    let counts;
    try { counts = (await api("GET", "/api/crm/contacts/" + c.id + "/erase-preview")).counts; } catch (e) { showToast(e.message, "error"); return; }
    const body = el("div", "gw-stack");
    body.appendChild(el("p", "gw-modal__text", "Esto borra para siempre los datos de " + c.full_name + " en el CRM y no se puede deshacer. Se quitará:"));
    const ul = el("ul", "crm-erase__list"); eraseLines(counts).forEach((t) => ul.appendChild(el("li", null, t))); body.appendChild(ul);
    const rv = reviewLines(counts.review);
    if (rv.length) {
      const warn = el("div", "gw-alert gw-alert--warn"); warn.appendChild(icon("alert"));
      const inner = el("div"); inner.appendChild(el("p", "gw-alert__title", "Después tendrás que revisar a mano"));
      rv.forEach((t) => inner.appendChild(el("p", "gw-alert__body", t))); inner.appendChild(el("p", "gw-alert__body", "Ese texto libre no se borra solo: te lo mostramos al terminar."));
      warn.appendChild(inner); body.appendChild(warn);
    } else body.appendChild(el("p", "gw-hint", "No encontramos texto libre que parezca mencionarla."));
    body.insertAdjacentHTML("beforeend", '<div class="gw-alert gw-alert--err" id="crmEraseErr" role="alert" hidden><div class="gw-alert__body"></div></div>' +
      '<div class="gw-field"><label class="gw-label" for="er_reason">Motivo de la supresión</label><input class="gw-input" id="er_reason" maxlength="200" autocomplete="off"></div>' +
      '<div class="gw-field"><label class="gw-label" for="er_name">Escribe su nombre completo para confirmar</label><input class="gw-input" id="er_name" autocomplete="off"></div>');
    const d = dialog({ title: "Suprimir los datos de un contacto", warning: true, bodyHtml: "", onEscape: () => d.close(),
      buttons: [{ id: "erCancel", cls: "gw-btn--secondary", label: "Cancelar" }, { id: "erGo", cls: "gw-btn--danger", label: "Suprimir definitivamente" }] });
    d.dlg.querySelector(".gw-modal__body").replaceChildren(body);
    const go = d.dlg.querySelector("#erGo"), reason = d.dlg.querySelector("#er_reason"), nm = d.dlg.querySelector("#er_name"), err = d.dlg.querySelector("#crmEraseErr");
    const ready = () => { go.disabled = !(reason.value.trim() && nm.value.trim().toLowerCase() === c.full_name.trim().toLowerCase()); };
    go.disabled = true; reason.addEventListener("input", ready); nm.addEventListener("input", ready);
    d.dlg.querySelector("#erCancel").addEventListener("click", () => d.close());
    reason.focus();
    go.addEventListener("click", () => busy(go, async () => {
      try {
        const r = await api("POST", "/api/crm/contacts/" + c.id + "/erase", { reason: reason.value.trim(), confirm_name: nm.value.trim() });
        d.close(); showReview(r.counts); await loadContacts(); C.refreshPrimary(); loaded.notas = false; loaded.historial = false;
      } catch (e) { err.hidden = false; err.querySelector(".gw-alert__body").textContent = e.message; }
    }));
  }

  /* Resultado de la supresión: se queda a la vista (no es un aviso que desaparece) hasta que la persona dice que ya revisó. */
  function showReview(k) {
    const box = $("crmReview"), rv = reviewLines(k.review), pending = rv.length > 0;
    box.hidden = false; box.replaceChildren();
    const alert = el("div", "gw-alert " + (pending ? "gw-alert--warn" : "gw-alert--ok")); alert.appendChild(icon(pending ? "alert" : "check"));
    const inner = el("div", "gw-stack");
    inner.appendChild(el("p", "gw-alert__title", pending ? "Datos suprimidos. Falta revisar texto libre" : "Datos suprimidos"));
    inner.appendChild(el("p", "gw-alert__body", "Se quitó: " + eraseLines(k, true).join(", ") + "."));
    if (pending) {
      rv.forEach((t) => inner.appendChild(el("p", "gw-alert__body", t)));
      inner.appendChild(el("p", "gw-alert__body", "Ábrelos, quita lo que la identifique y guarda. Este aviso se queda aquí hasta que lo cierres."));
    } else inner.appendChild(el("p", "gw-alert__body", "No encontramos más menciones en la descripción ni en las notas generales."));
    const row = el("div", "crm-review__actions");
    if (k.review && k.review.description) { const b = el("button", "gw-btn gw-btn--secondary gw-btn--sm", "Abrir la descripción"); b.type = "button"; b.dataset.go = "description"; row.appendChild(b); }
    if (k.review && k.review.general_notes) { const b = el("button", "gw-btn gw-btn--secondary gw-btn--sm", "Ver las notas"); b.type = "button"; b.dataset.go = "notes"; row.appendChild(b); }
    const ok = el("button", "gw-btn gw-btn--secondary gw-btn--sm", pending ? "Ya lo revisé" : "Cerrar"); ok.type = "button"; ok.dataset.go = "close"; row.appendChild(ok);
    inner.appendChild(row); alert.appendChild(inner); box.appendChild(alert);
    box.scrollIntoView({ block: "center" });
  }
  $("crmReview").addEventListener("click", (e) => {
    const b = e.target.closest("[data-go]"); if (!b) return;
    if (b.dataset.go === "close") { $("crmReview").hidden = true; $("crmReview").replaceChildren(); return; }
    if (b.dataset.go === "notes") { select("notas"); $("panel_notas").scrollIntoView({ block: "start" }); return; }
    select("datos");
    const ta = $("description"); if (ta) { const g = ta.closest("details"); if (g) g.open = true; ta.focus(); ta.scrollIntoView({ block: "center" }); }
  });

  /* ---------------------------------------------------------------- notas */
  async function loadNotes() {
    const box = $("crmNotes");
    try {
      const [notes] = await Promise.all([api("GET", "/api/crm/accounts/" + C.id + "/notes"), loadContactNames()]);
      box.replaceChildren();
      const sel = $("crmNoteContact"), keep = sel.value; sel.replaceChildren(new Option("Toda la cuenta", ""));
      contactsActive.forEach((c) => sel.appendChild(new Option(c.full_name, String(c.id)))); if (keep) sel.value = keep;
      if (!notes.length) { box.appendChild(stateBlock("empty", "Todavía no hay notas", "Escribe la primera arriba.")); return; }
      const list = el("ul", "crm-notes");
      notes.forEach((n) => {
        const li = el("li", "gw-card crm-note"); li.dataset.noteId = n.id;
        const meta = el("p", "crm-note__meta"); meta.appendChild(el("strong", null, n.author || "Alguien del equipo")); meta.appendChild(document.createTextNode(" · " + fmtDate(n.created_at)));
        if (n.contact_id) meta.appendChild(el("span", "gw-badge", "Sobre " + (contactsAll[n.contact_id] || "un contacto")));
        li.appendChild(meta); li.appendChild(el("p", "crm-note__body", n.body));
        const del = el("button", "gw-btn gw-btn--secondary gw-btn--sm", "Borrar"); del.type = "button"; del.dataset.del = n.id; li.appendChild(del);
        list.appendChild(li);
      });
      box.appendChild(list);
    } catch (e) { box.replaceChildren(stateBlock("error", "No se pudieron cargar las notas", e.message, loadNotes)); }
  }
  async function loadContactNames() {
    const [a, b] = await Promise.all([fetchContacts(false), fetchContacts(true)]);
    contactsActive = a; [...a, ...b].forEach((c) => { contactsAll[c.id] = c.full_name; });
  }
  $("crmNoteForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = $("crmNoteBody").value.trim();
    if (!body) { $("crmNoteBody").setAttribute("aria-invalid", "true"); $("crmNoteBody").focus(); showToast("Escribe la nota.", "error"); return; }
    $("crmNoteBody").removeAttribute("aria-invalid");
    await busy($("crmNoteSave"), async () => {
      try { await api("POST", "/api/crm/accounts/" + C.id + "/notes", { body, contact_id: $("crmNoteContact").value ? Number($("crmNoteContact").value) : null }); $("crmNoteBody").value = ""; showToast("Nota agregada.", "success"); await loadNotes(); }
      catch (err) { showToast(err.message, "error"); }
    });
  });
  $("crmNotes").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-del]"); if (!b) return;
    if (!await showConfirm("", { title: "Borrar nota", text: "La nota se borra para siempre.", confirmLabel: "Borrar" })) return;
    try { await api("DELETE", "/api/crm/notes/" + b.dataset.del); showToast("Nota borrada.", "success"); await loadNotes(); } catch (err) { showToast(err.message, "error"); }
  });

  /* ---------------------------------------------------------------- historial */
  const LABELS = { name: "Nombre", status: "Estado", nit: "NIT", email: "Correo", phone: "Teléfono", billing_address: "Dirección de facturación", billing_city: "Ciudad de facturación", billing_state: "Departamento de facturación",
    billing_country: "País de facturación", shipping_address: "Dirección de envío", shipping_city: "Ciudad de envío", shipping_country: "País de envío", billing_contact_name: "Contacto de facturación",
    billing_contact_phone: "Teléfono de facturación", payment_term: "Condición de pago", payment_days: "Días de plazo", billing_close: "Cierre de facturación", agency_percent: "Porcentaje de agencia",
    owner_staff_id: "Responsable", description: "Descripción", archived_at: "Archivada", first_name: "Nombres", last_name: "Apellidos", job_title: "Cargo", mobile: "Celular", is_primary: "Contacto principal", notes: "Notas del contacto" };
  function val(field, v) {
    if (v == null || v === "") return "—";
    if (field === "is_primary") return v === "True" ? "Sí" : "No";
    if (field === "archived_at") return "Sí";
    if (field === "owner_staff_id") return "Responsable #" + v;
    return v;
  }
  async function loadHistory() {
    const box = $("crmHistory"), pager = $("crmHistoryPager"); pager.replaceChildren();
    try {
      const rows = await api("GET", "/api/crm/accounts/" + C.id + "/history");
      if (!rows.length) { box.replaceChildren(stateBlock("empty", "Todavía no hay cambios", "Aquí aparecerá cada cambio que se haga a la cuenta y a sus contactos.")); return; }
      let page = 0;
      const draw = () => {
        const s = GW.pageSlice("crm_historial", rows, page); page = s.page;
        const wrap = el("div", "gw-table-wrap"), t = el("table", "gw-table gw-table-cards crm-history"), th = el("thead"), hr = el("tr");
        ["Cuándo", "Quién", "Sobre", "Qué cambió", "Antes → Después"].forEach((h) => { const x = el("th", null, h); x.scope = "col"; hr.appendChild(x); }); th.appendChild(hr); t.appendChild(th);
        const tb = el("tbody");
        s.items.forEach((r) => {
          const tr = el("tr"), td = (label, content) => { const c = el("td"); c.dataset.label = label; if (content instanceof Node) c.appendChild(content); else c.textContent = content; tr.appendChild(c); };
          td("Cuándo", fmtDate(r.at)); td("Quién", (r.by || "Sistema") + (r.source === "import" ? " (importado)" : ""));
          td("Sobre", r.entity === "contact" ? "Contacto: " + (r.contact || "contacto") : "La cuenta"); td("Qué cambió", LABELS[r.field] || r.field);
          const ch = el("span", "crm-history__change"); ch.appendChild(document.createTextNode(val(r.field, r.old) + " → " + val(r.field, r.new))); td("Antes → Después", ch);
          tb.appendChild(tr);
        });
        t.appendChild(tb); wrap.appendChild(t); box.replaceChildren(wrap);
        pager.replaceChildren(GW.pagerBar({ key: "crm_historial", total: rows.length, page, onPage: (i) => { page = i; draw(); }, onSize: () => { page = 0; draw(); } }));
      };
      draw();
    } catch (e) { box.replaceChildren(stateBlock("error", "No se pudo cargar el historial", e.message, loadHistory)); }
  }

  /* ---------------------------------------------------------------- arranque */
  const want = (window.location.hash || "").slice(1);
  if (TABS.indexOf(want) > 0) select(want);
})();
