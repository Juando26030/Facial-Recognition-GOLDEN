/* Exportar e importar eventos entre entornos (docs/18_EXPORTAR_EVENTOS.md). Solo super_admin (los botones solo se pintan para ese rol y el servidor lo exige).
   Dos asistentes paso a paso que usan los endpoints /api/event-transfer/*:
     - Exportar: opciones (biometría opcional con frase de transporte) → generar con avance → descargar (enlace firmado de 5 min; el paquete se borra a las 24 h).
     - Importar: elegir cliente y paquete (subida directa) → revisar → opciones → SIMULACRO → importar de verdad → informe «Origen vs Destino» → confirmar el estado si quedó en espera.
   Se activa por delegación de eventos sobre [data-export-event] y [data-import-event]; usa showToast/showConfirm de toast.js. */
(function () {
  "use strict";
  var TABLE_LABELS = {
    events: "Evento", event_field_configs: "Campos opcionales", event_areas: "Áreas", inventory_items: "Ítems de inventario", badge_templates: "Plantillas de escarapela", web_forms: "Formularios",
    form_discount_codes: "Códigos de descuento", form_invites: "Invitaciones", form_people: "Pre-llenado", form_events: "Embudo de formularios", users: "Personas", event_attendees: "Inscritos",
    form_submissions: "Respuestas de formularios", form_payments: "Pagos (histórico)", form_refunds: "Reembolsos (histórico)", roulette_configs: "Ruleta", roulette_draws: "Sorteos",
    access_logs: "Registros / acreditaciones", area_movements: "Movimientos de áreas", inventory_deliveries: "Entregas de inventario", print_logs: "Impresiones", person_changes: "Cambios de personas",
    audit_consent_logs: "Consentimientos", web_acceptances: "Aceptaciones web", event_documents: "Documentos", event_expenses: "Gastos", biometrics: "Biometría"
  };
  var SMALL_UPLOAD = 24 * 1024 * 1024;     // hasta aquí el paquete sube por la propia aplicación (igual que el límite del servidor)
  var ROLE_LABELS = { badge_asset: "imágenes de diseño", form_file: "archivos de formularios", signature: "firmas", event_doc: "documentos", expense: "comprobantes", logo: "logo", report: "informe PDF", biometric_photo: "fotos de registro" };

  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  function toast(msg, type) { if (window.showToast) window.showToast(msg, type || "info"); }
  function confirmAsk(msg, opts) { return window.showConfirm ? window.showConfirm(msg, opts || {}) : Promise.resolve(true); }

  function injectStyles() {
    if (document.getElementById("gwTransferStyles")) return;
    var st = document.createElement("style");
    st.id = "gwTransferStyles";
    st.textContent =
      ".gwt-overlay{position:fixed;inset:0;background:rgba(10,14,46,.55);z-index:9000;display:flex;align-items:flex-start;justify-content:center;overflow:auto;padding:4vh 12px}" +
      ".gwt-box{background:#fff;border-radius:16px;max-width:760px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.35);font-family:sans-serif;color:#222}" +
      ".gwt-head{position:sticky;top:0;background:#0A0E2E;color:#fff;padding:14px 20px;border-radius:16px 16px 0 0;display:flex;justify-content:space-between;align-items:center;gap:12px}" +
      ".gwt-head h3{margin:0;font-size:1.05rem}.gwt-x{background:transparent;border:0;color:#fff;font-size:1.4rem;cursor:pointer}" +
      ".gwt-body{padding:18px 20px;font-size:.92rem;line-height:1.45}.gwt-foot{padding:12px 20px 18px;display:flex;gap:10px;justify-content:flex-end;flex-wrap:wrap}" +
      ".gwt-btn{border:1px solid #ccc;background:#fff;border-radius:20px;padding:8px 18px;font-weight:700;cursor:pointer;font-size:.88rem;text-decoration:none;color:#222;display:inline-block}" +
      ".gwt-btn.primary{background:#D4AF37;border-color:#D4AF37;color:#1a1200}.gwt-btn:disabled{opacity:.5;cursor:default}" +
      ".gwt-field{display:block;margin:10px 0}.gwt-field span{display:block;font-weight:700;font-size:.8rem;margin-bottom:3px}" +
      ".gwt-field input[type=text],.gwt-field input[type=password],.gwt-field select,.gwt-field input[type=file]{width:100%;padding:8px 10px;border:1px solid #ccc;border-radius:8px;font-size:.9rem;box-sizing:border-box}" +
      ".gwt-box .warn{background:#fff6e0;border:1px solid #e8c36a;border-radius:10px;padding:10px 12px;margin:10px 0}" +
      ".gwt-box .bad{background:#fdecea;border:1px solid #e0a19b;border-radius:10px;padding:10px 12px;margin:10px 0}" +
      ".gwt-box .good{background:#e8f6ec;border:1px solid #9fd4ad;border-radius:10px;padding:10px 12px;margin:10px 0}" +
      ".gwt-bar{height:14px;background:#eee;border-radius:8px;overflow:hidden;margin:10px 0}.gwt-bar i{display:block;height:100%;background:#D4AF37;width:0;transition:width .4s}" +
      ".gwt-table{width:100%;border-collapse:collapse;font-size:.82rem;margin:8px 0}.gwt-table th,.gwt-table td{border-bottom:1px solid #eee;padding:5px 6px;text-align:left}.gwt-table td.n,.gwt-table th.n{text-align:right}" +
      ".gwt-box ul{margin:6px 0 6px 18px;padding:0}.gwt-muted{color:#666;font-size:.82rem}.gwt-box details{margin-top:10px}";
    document.head.appendChild(st);
  }

  function openModal(title) {
    injectStyles();
    var ov = document.createElement("div");
    ov.className = "gwt-overlay";
    ov.innerHTML = '<div class="gwt-box" role="dialog" aria-modal="true"><div class="gwt-head"><h3>' + esc(title) + '</h3><button type="button" class="gwt-x" data-gwt-close aria-label="Cerrar">×</button></div>' +
      '<div class="gwt-body"></div><div class="gwt-foot"></div></div>';
    document.body.appendChild(ov);
    var api = {
      el: ov, body: ov.querySelector(".gwt-body"), foot: ov.querySelector(".gwt-foot"), timer: null,
      close: function () { clearTimeout(api.timer); ov.remove(); },
      set: function (html, buttons) {
        api.body.innerHTML = html;
        api.foot.innerHTML = (buttons || []).map(function (b) {
          return b.href ? '<a class="gwt-btn ' + (b.primary ? "primary" : "") + '" href="' + esc(b.href) + '" ' + (b.id ? 'data-gwt="' + b.id + '"' : "") + ">" + esc(b.label) + "</a>"
            : '<button type="button" class="gwt-btn ' + (b.primary ? "primary" : "") + '" data-gwt="' + b.id + '" ' + (b.disabled ? "disabled" : "") + ">" + esc(b.label) + "</button>";
        }).join("");
      }
    };
    ov.addEventListener("click", function (e) {
      if (e.target.closest("[data-gwt-close]")) api.close();
      var b = e.target.closest("[data-gwt]");
      if (b && api.on && api.on[b.dataset.gwt]) api.on[b.dataset.gwt](b, e);
    });
    return api;
  }

  async function jfetch(url, opts) {
    var r = await fetch(url, opts);
    var data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    if (!r.ok) {
      var d = data && data.detail;
      throw new Error(typeof d === "string" ? d : (d && d.message) || "No se pudo completar la acción (" + r.status + ").");
    }
    return data;
  }
  function post(url, body) { return jfetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) }); }
  function sleep(ms) { return new Promise(function (res) { setTimeout(res, ms); }); }

  /* Sigue un trabajo en segundo plano hasta que termina; pinta la barra en `ui.body` si existe [data-gwt-bar]. */
  async function follow(jobId, ui) {
    for (;;) {
      var j = await jfetch("/api/event-transfer/jobs/" + jobId);
      var bar = ui.body.querySelector("[data-gwt-bar]"), stage = ui.body.querySelector("[data-gwt-stage]");
      if (bar) bar.style.width = (j.progress || 0) + "%";
      if (stage) stage.textContent = (j.stage || "") + " · " + (j.progress || 0) + " %";
      if (j.status !== "running") return j;
      await sleep(1200);
    }
  }
  function progressHtml(text) { return "<p>" + esc(text) + '</p><div class="gwt-bar"><i data-gwt-bar></i></div><p class="gwt-muted" data-gwt-stage>Preparando…</p>'; }
  function fmtBytes(n) { return n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB"; }
  function countsTable(counts) {
    var rows = Object.keys(counts || {}).filter(function (k) { return counts[k] > 0; }).map(function (k) { return "<tr><td>" + esc(TABLE_LABELS[k] || k) + '</td><td class="n">' + counts[k] + "</td></tr>"; }).join("");
    return rows ? '<table class="gwt-table"><thead><tr><th>Qué</th><th class="n">Filas</th></tr></thead><tbody>' + rows + "</tbody></table>" : "";
  }

  // ------------------------------------------------------------------------------------------------ EXPORTAR
  function openExport(eventId, eventName) {
    var ui = openModal("Exportar evento");
    var state = { passphrase: "" };
    function start() {
      ui.on = { gen: generate };
      ui.set(
        "<p><b>" + esc(eventName) + "</b></p>" +
        "<p>Se arma un paquete <b>.zip</b> con TODO el evento: configuración y parámetros, campos, plantilla de escarapela, formularios, ruleta, personas, registros con sus horas, consentimientos y los archivos (imágenes, firmas, documentos). " +
        "Sirve para llevarlo a otro entorno (staging, producción o el servidor local) y crearlo allá <b>igual</b>.</p>" +
        '<div class="warn">El paquete lleva <b>datos personales</b>: se descarga con un enlace que dura 5 minutos y se <b>borra solo del servidor a las 24 horas</b>. Guárdalo con cuidado y bórralo de tu computador cuando termines.</div>' +
        '<label class="gwt-field"><span><input type="checkbox" id="gwtBio"> Incluir biometría (rostros y fotos de registro)</span></label>' +
        '<div id="gwtBioBox" style="display:none"><div class="bad"><b>Datos biométricos.</b> Solo lo puede hacer un super_admin. Por defecto NO se exportan. Los vectores y las fotos viajan <b>cifrados</b> con la frase que escribas aquí; ' +
        "<b>la frase no se guarda</b>: sin ella el paquete no se puede importar. En el destino solo entran personas mayores de edad con consentimiento aceptado registrado.</div>" +
        '<label class="gwt-field"><span>Frase de transporte (mínimo 8 caracteres)</span><input type="password" id="gwtPass" autocomplete="new-password"></label>' +
        '<label class="gwt-field"><span>Repite la frase</span><input type="password" id="gwtPass2" autocomplete="new-password"></label></div>',
        [{ id: "cancel", label: "Cancelar" }, { id: "gen", label: "Generar paquete", primary: true }]
      );
      ui.on.cancel = ui.close;
      ui.body.querySelector("#gwtBio").addEventListener("change", function (e) { ui.body.querySelector("#gwtBioBox").style.display = e.target.checked ? "" : "none"; });
    }
    async function generate() {
      var bio = ui.body.querySelector("#gwtBio").checked, p1 = bio ? ui.body.querySelector("#gwtPass").value : "", p2 = bio ? ui.body.querySelector("#gwtPass2").value : "";
      if (bio) {
        if (p1.length < 8) { toast("La frase de transporte debe tener al menos 8 caracteres.", "error"); return; }
        if (p1 !== p2) { toast("Las dos frases no coinciden.", "error"); return; }
        var ok = await confirmAsk("Vas a exportar <b>datos biométricos</b> (rostros y fotos de registro), cifrados con tu frase. ¿Confirmas?", { variant: "warning", confirmLabel: "Sí, incluir biometría" });
        if (!ok) return;
      }
      state.passphrase = "";
      ui.set(progressHtml("Generando el paquete…"), []);
      try {
        var job = await post("/api/event-transfer/export/start", { event_id: eventId, include_biometrics: bio, passphrase: bio ? p1 : null });
        if (job.status === "running") job = await follow(job.id, ui);
        if (job.status !== "done") throw new Error((job.result && job.result.error) || "No se pudo generar el paquete.");
        done(job);
      } catch (e) { fail(e.message); }
    }
    function done(job) {
      var r = job.result || {}, total = Object.keys(r.counts || {}).reduce(function (s, k) { return s + r.counts[k]; }, 0);
      ui.on = { cerrar: ui.close, refresh: async function () { try { var j = await jfetch("/api/event-transfer/jobs/" + job.id); done(j); } catch (e) { toast(e.message, "error"); } } };
      ui.set(
        '<div class="good"><b>Paquete listo.</b> ' + total + " filas · " + (r.files || 0) + " archivo(s) · " + fmtBytes(r.size || 0) + (r.biometrics ? " · <b>con biometría cifrada</b>" : " · sin biometría") + "</div>" +
        countsTable(r.counts) + (r.warnings && r.warnings.length ? '<div class="warn"><b>Avisos</b><ul>' + r.warnings.map(function (w) { return "<li>" + esc(w) + "</li>"; }).join("") + "</ul></div>" : "") +
        '<p class="gwt-muted">El enlace de descarga dura 5 minutos; si vence, pide uno nuevo. El paquete se borra solo del servidor a las 24 horas.</p>',
        [{ id: "refresh", label: "Pedir enlace nuevo" }, job.download_url ? { id: "dl", label: "⬇ Descargar paquete (.zip)", primary: true, href: job.download_url } : { id: "cerrar", label: "Cerrar" }, { id: "cerrar", label: "Cerrar" }]
      );
    }
    function fail(msg) { ui.on = { cerrar: ui.close, again: start }; ui.set('<div class="bad">' + esc(msg) + "</div>", [{ id: "again", label: "Volver" }, { id: "cerrar", label: "Cerrar" }]); }
    start();
  }

  // ------------------------------------------------------------------------------------------------ IMPORTAR
  async function openImport(tenantId, tenantName) {
    var ui = openModal("Importar evento" + (tenantName ? " — " + tenantName : ""));
    var S = { tenants: [], tenantId: tenantId || "", token: null, info: null, report: null, filename: "" };
    try { S.tenants = await jfetch("/api/tenants"); } catch (e) { S.tenants = []; }

    function tenantSelect() {
      return '<label class="gwt-field"><span>Cliente donde se creará el evento</span><select id="gwtTenant">' +
        S.tenants.map(function (t) { return '<option value="' + esc(t.id) + '"' + (t.id === S.tenantId ? " selected" : "") + ">" + esc(t.name) + " (#" + esc(t.client_code) + ")</option>"; }).join("") + "</select></label>";
    }
    function stepFile() {
      ui.on = { cancel: ui.close, upload: upload };
      ui.set(
        "<p>Crea un evento <b>NUEVO</b> a partir de un paquete exportado de otro entorno. <b>Nunca sobrescribe</b> un evento que ya existe, y primero hace un <b>simulacro</b> para que veas qué entraría.</p>" +
        tenantSelect() +
        '<label class="gwt-field"><span>Paquete del evento (.zip)</span><input type="file" id="gwtFile" accept=".zip"></label>' +
        '<details><summary>Historial de exportaciones e importaciones</summary><div id="gwtLog" class="gwt-muted">Cargando…</div></details>',
        [{ id: "cancel", label: "Cancelar" }, { id: "upload", label: "Subir y revisar", primary: true }]
      );
      jfetch("/api/event-transfer/log").then(function (rows) {
        var el = ui.body.querySelector("#gwtLog");
        if (!el) return;
        el.innerHTML = rows.length ? '<table class="gwt-table"><thead><tr><th>Cuándo</th><th>Qué</th><th>Quién</th><th>Evento</th><th class="n">Filas</th></tr></thead><tbody>' + rows.map(function (r) {
          return "<tr><td>" + esc(r.at.replace("T", " ").slice(0, 16)) + "</td><td>" + (r.kind === "export" ? "Exportó" : "Importó") + (r.pending_confirm ? " (en espera)" : "") + "</td><td>" + esc(r.by) + "</td><td>" + esc(r.event_code) + '</td><td class="n">' + (r.rows == null ? "" : r.rows) + "</td></tr>";
        }).join("") + "</tbody></table>" : "Todavía no hay movimientos.";
      }).catch(function () { var el = ui.body.querySelector("#gwtLog"); if (el) el.textContent = "No se pudo cargar el historial."; });
    }
    async function upload() {
      var f = ui.body.querySelector("#gwtFile").files[0];
      S.tenantId = ui.body.querySelector("#gwtTenant").value;
      if (!f) { toast("Elige el archivo .zip del paquete.", "error"); return; }
      S.filename = f.name;
      ui.set(progressHtml("Subiendo y revisando el paquete…"), []);
      try {
        if (f.size <= SMALL_UPLOAD) {                       // chico: sube POR la aplicación (no depende del CORS del bucket)
          var fd = new FormData();
          fd.append("file", f, f.name);
          S.token = (await jfetch("/api/event-transfer/upload", { method: "POST", body: fd })).token;
        } else {                                            // grande: subida directa al almacenamiento (URL firmada)
          var up = await post("/api/event-transfer/upload-url", { filename: f.name, size: f.size });
          var put;
          try { put = await fetch(up.url, { method: up.method || "PUT", headers: up.headers || {}, body: f }); }
          catch (netErr) { throw new Error("No se pudo subir el paquete directo al almacenamiento (el navegador lo bloqueó: falta autorizar este sitio en el CORS del bucket). Los paquetes de hasta 24 MB suben por la aplicación sin ese permiso."); }
          if (!put.ok) throw new Error("No se pudo subir el archivo (" + put.status + ").");
          S.token = up.token;
        }
        S.info = await post("/api/event-transfer/import/inspect", { token: S.token });
        stepOptions();
      } catch (e) { fail(e.message, stepFile); }
    }
    function stepOptions(conflicts) {
      var i = S.info, sameTenant = !S.tenantId || (i.tenant && i.tenant.id === S.tenantId);
      ui.on = { back: stepFile, dry: function () { dryRun(); } };
      ui.set(
        '<div class="good"><b>Paquete válido.</b> Evento <b>' + esc(i.name) + "</b> (" + esc(i.event_code) + ") · estado de origen: " + esc(i.status) + " · de «" + esc(i.source_env) + "» · " + (i.files || 0) + " archivo(s)</div>" +
        countsTable(i.counts) + (i.warnings && i.warnings.length ? '<div class="warn"><b>Avisos del paquete</b><ul>' + i.warnings.map(function (w) { return "<li>" + esc(w) + "</li>"; }).join("") + "</ul></div>" : "") +
        (conflicts && conflicts.length ? '<div class="bad"><b>Hay que cambiar algo:</b><ul>' + conflicts.map(function (c) { return "<li>" + esc(c) + "</li>"; }).join("") + "</ul></div>" : "") +
        '<label class="gwt-field"><span>Código del evento nuevo</span><input type="text" id="gwtCode" value="' + esc(S.code || i.event_code) + '"></label>' +
        '<label class="gwt-field"><span>Nombre del evento nuevo</span><input type="text" id="gwtName" value="' + esc(S.name || i.name) + '"></label>' +
        (sameTenant ? "" : '<div class="warn">El paquete es de otro cliente (' + esc(i.tenant && i.tenant.name) + "): todo el evento pasará al cliente que elegiste.</div>") +
        '<label class="gwt-field"><span><input type="checkbox" id="gwtKeep"' + (S.keep ? " checked" : "") + '> Conservar el estado original (formularios activos y calendario)</span></label>' +
        '<div class="warn" style="margin-top:-4px">Por defecto los formularios entran en «pruebas» y un evento «en proceso» queda en espera hasta que lo confirmes, para no activar nada por accidente. ' +
        "Marca esta casilla solo si estás clonando un evento completo a propósito.</div>" +
        (i.has_biometrics ? '<div class="bad"><b>Este paquete trae biometría cifrada.</b> Escribe la frase de transporte para importarla (solo entran personas nuevas, mayores de edad y con consentimiento aceptado); o deja la casilla apagada para ignorarla.</div>' +
          '<label class="gwt-field"><span><input type="checkbox" id="gwtBio" checked> Importar la biometría</span></label>' +
          '<label class="gwt-field"><span>Frase de transporte</span><input type="password" id="gwtPass" autocomplete="off"></label>' : ""),
        [{ id: "back", label: "Volver" }, { id: "dry", label: "Hacer el simulacro (no escribe nada)", primary: true }]
      );
    }
    function readOptions() {
      S.code = ui.body.querySelector("#gwtCode").value.trim();
      S.name = ui.body.querySelector("#gwtName").value.trim();
      S.keep = ui.body.querySelector("#gwtKeep").checked;
      var bio = ui.body.querySelector("#gwtBio");
      S.bio = bio ? bio.checked : false;
      var pass = ui.body.querySelector("#gwtPass");
      S.pass = pass ? pass.value : "";
    }
    async function dryRun() {
      readOptions();
      if (S.info.has_biometrics && S.bio && !S.pass) { toast("Escribe la frase de transporte o desmarca «Importar la biometría».", "error"); return; }
      await run(true);
    }
    async function run(dry) {
      ui.set(progressHtml(dry ? "Haciendo el simulacro…" : "Importando el evento…"), []);
      try {
        var job = await post("/api/event-transfer/import/start", { token: S.token, dry_run: dry, new_event_code: S.code, new_name: S.name, target_tenant_id: S.tenantId || null,
          keep_original_state: !!S.keep, import_biometrics: S.info.has_biometrics ? !!S.bio : true, passphrase: S.pass || null });
        if (job.status === "running") job = await follow(job.id, ui);
        var r = job.result || {};
        if (job.status !== "done") {
          if (r.conflicts && r.conflicts.length) { stepOptions(r.conflicts); return; }
          throw new Error(r.error || "No se pudo completar.");
        }
        if (dry) stepReport(r); else stepDone(job);
      } catch (e) { fail(e.message, stepOptions); }
    }
    function skippedList(r) {
      var out = [];
      Object.keys(r.skipped || {}).forEach(function (t) { Object.keys(r.skipped[t]).forEach(function (why) { out.push((TABLE_LABELS[t] || t) + ": " + r.skipped[t][why] + " omitida(s) — " + why); }); });
      return out;
    }
    function stepReport(r) {
      S.report = r;
      var rows = Object.keys(r.tables).filter(function (k) { return r.tables[k].source > 0; }).map(function (k) {
        var t = r.tables[k];
        return "<tr><td>" + esc(TABLE_LABELS[k] || k) + '</td><td class="n">' + t.source + '</td><td class="n">' + t.imported + "</td></tr>";
      }).join("");
      var p = r.persons || {}, files = r.files || {};
      ui.on = { back: function () { stepOptions(); }, go: realImport };
      ui.set(
        '<div class="good"><b>Simulacro hecho: no se escribió nada.</b> Así quedaría el evento <b>' + esc(r.name) + "</b> (" + esc(r.event_code) + ").</div>" +
        '<table class="gwt-table"><thead><tr><th>Qué</th><th class="n">En el paquete</th><th class="n">Entrarían</th></tr></thead><tbody>' + rows + "</tbody></table>" +
        "<p>Personas: <b>" + (p.new || 0) + "</b> nuevas · " + (p.existing_kept || 0) + " ya existían (se conservan como están" + (p.existing_different ? ", " + p.existing_different + " con datos distintos" : "") + ") · " + (p.suppressed_skipped || 0) + " suprimidas (no se importan).</p>" +
        "<p>Archivos: <b>" + (files.planned || 0) + "</b> por copiar" + (files.by_role ? " (" + Object.keys(files.by_role).map(function (k) { return files.by_role[k] + " " + (ROLE_LABELS[k] || k); }).join(", ") + ")" : "") + ".</p>" +
        (r.biometrics && r.biometrics.in_package ? "<p>Biometría: <b>" + r.biometrics.imported + "</b> de " + r.biometrics.in_package + " personas entrarían" + (Object.keys(r.biometrics.skipped || {}).length ? " (omitidas: " + Object.keys(r.biometrics.skipped).map(function (k) { return r.biometrics.skipped[k] + " " + k; }).join(", ") + ")" : "") + ".</p>" : "") +
        (skippedList(r).length ? '<div class="warn"><b>Se omitirían</b><ul>' + skippedList(r).map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul></div>" : "") +
        (r.staff_without_link && r.staff_without_link.length ? '<div class="warn">Estos usuarios del personal no existen aquí; sus registros se conservan con el nombre como texto, sin enlace: <b>' + r.staff_without_link.map(esc).join(", ") + "</b>.</div>" : "") +
        (r.warnings && r.warnings.length ? '<div class="warn"><b>Avisos</b><ul>' + r.warnings.slice(0, 12).map(function (w) { return "<li>" + esc(w) + "</li>"; }).join("") + "</ul></div>" : "") +
        (r.pending_confirm ? '<div class="warn">El evento entrará en espera (estado «Creado») y los formularios en «pruebas» hasta que lo confirmes: así no se activa nada ni se congelan los despliegues por accidente.</div>' : ""),
        [{ id: "back", label: "Cambiar opciones" }, { id: "go", label: "Importar de verdad", primary: true }]
      );
    }
    async function realImport() {
      var ok = await confirmAsk("Se creará un evento <b>NUEVO</b> («" + esc(S.name) + "») con todo lo del paquete. No se modifica ningún evento existente. ¿Importar de verdad?", { confirmLabel: "Sí, importar" });
      if (ok) await run(false);
    }
    function stepDone(job) {
      var r = job.result || {}, fid = r.fidelity || { tables: {}, different_tables: [], all_equal: true };
      var rows = Object.keys(fid.tables).filter(function (k) { return fid.tables[k].source > 0 || fid.tables[k].destination > 0; }).map(function (k) {
        var t = fid.tables[k];
        return "<tr><td>" + esc(TABLE_LABELS[k] || k) + '</td><td class="n">' + t.source + '</td><td class="n">' + t.destination + "</td><td>" + (t.equal ? "✅ iguales" : "⚠️ diferentes") + (t.note ? '<div class="gwt-muted">' + esc(t.note) + "</div>" : "") + "</td></tr>";
      }).join("");
      var buttons = [{ id: "cerrar", label: "Cerrar" }];
      ui.on = { cerrar: function () { ui.close(); }, confirm: async function () {
        var ok = await confirmAsk("Esto pone el evento y sus formularios en el estado que tenían en el origen. Si el evento queda «en proceso», se activará el congelamiento de despliegues. ¿Confirmar?", { variant: "warning", confirmLabel: "Sí, confirmar" });
        if (!ok) return;
        try { await post("/api/event-transfer/imports/" + r.import_id + "/confirm"); toast("Estado original aplicado.", "success"); stepDone(Object.assign({}, job, { result: Object.assign({}, r, { pending_confirm: false }) })); } catch (e) { toast(e.message, "error"); }
      } };
      if (job.event_id) buttons.unshift({ id: "open", label: "Abrir el evento →", primary: !r.pending_confirm, href: "/kiosk/" + job.event_id });
      if (r.pending_confirm) buttons.unshift({ id: "confirm", label: "Confirmar y aplicar el estado original", primary: true });
      ui.set(
        '<div class="' + (fid.all_equal ? "good" : "warn") + '"><b>Evento importado.</b> ' + esc(r.name) + " (" + esc(r.event_code) + ")" + (fid.all_equal ? " — origen y destino son <b>iguales</b>." : " — hay diferencias esperadas (abajo).") + "</div>" +
        "<p><b>Origen vs Destino</b></p>" + '<table class="gwt-table"><thead><tr><th>Qué</th><th class="n">Origen</th><th class="n">Destino</th><th>Resultado</th></tr></thead><tbody>' + rows + "</tbody></table>" +
        (r.pending_confirm ? '<div class="warn"><b>Está en espera.</b> El evento quedó en «Creado» y los formularios en «pruebas». Revísalo y, cuando quieras, confirma para aplicar el estado original.</div>' : "") +
        '<p class="gwt-muted">Quedó registrado en el historial (quién, cuándo y cuántas filas; sin datos personales). El paquete subido ya se borró del servidor.</p>',
        buttons
      );
    }
    function fail(msg, back) { ui.on = { cerrar: ui.close, back: back || stepFile }; ui.set('<div class="bad">' + esc(msg) + "</div>", [{ id: "back", label: "Volver" }, { id: "cerrar", label: "Cerrar" }]); }
    stepFile();
  }

  document.addEventListener("click", function (e) {
    var ex = e.target.closest("[data-export-event]");
    if (ex) { e.preventDefault(); e.stopPropagation(); openExport(Number(ex.dataset.exportEvent), ex.dataset.eventName || ""); return; }
    var im = e.target.closest("[data-import-event]");
    if (im) { e.preventDefault(); e.stopPropagation(); openImport(im.dataset.tenantId || "", im.dataset.tenantName || ""); }
  }, true);
  window.GoldenEventTransfer = { openExport: openExport, openImport: openImport };
})();
