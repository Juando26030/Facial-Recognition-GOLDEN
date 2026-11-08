/* Notificaciones tipo "toast" — reemplazo de alert()/confirm() para dar feedback de acciones
   CRUD sin bloquear la interfaz. Uso: showToast("Evento creado", "success" | "error"). */
(function () {
  let container = null;

  function ensureContainer() {
    if (container) return container;
    container = document.createElement("div");
    container.id = "toastContainer";
    container.style.cssText = `
      position: fixed; top: 20px; right: 20px; z-index: 10002;
      display: flex; flex-direction: column; gap: 10px; pointer-events: none;
    `;
    document.body.appendChild(container);
    return container;
  }

  /* opts.action = { label, onClick }: botón dentro del aviso (p. ej. «Deshacer»); con acción el aviso dura opts.duration (8 s por defecto) en vez de 3,2 s. Devuelve { close() }. */
  window.showToast = function (message, type, opts) {
    opts = opts || {};
    type = type === "error" ? "error" : "success";
    const el = document.createElement("div");
    const colors = type === "success"
      ? { bg: "#e6f6ea", border: "#28a745", text: "#1e7e34" }
      : { bg: "#fbe9ea", border: "#dc3545", text: "#a12631" };
    el.style.cssText = `
      background: ${colors.bg}; border-left: 4px solid ${colors.border}; color: ${colors.text};
      padding: 12px 18px; border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,0.15);
      font-family: var(--font-body, sans-serif); font-weight: 600; font-size: 0.9rem;
      max-width: 320px; opacity: 0; transform: translateX(20px); transition: opacity 0.25s, transform 0.25s;
      pointer-events: auto;
    `;
    el.textContent = (type === "success" ? "✓ " : "✕ ") + message;
    let gone = false;
    const close = () => {
      if (gone) return; gone = true;
      el.style.opacity = "0"; el.style.transform = "translateX(20px)";
      setTimeout(() => el.remove(), 300);
    };
    if (opts.action && opts.action.label) {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = opts.action.label;
      b.style.cssText = "margin-left:12px; padding:4px 12px; border-radius:14px; border:2px solid currentColor; background:transparent; color:inherit; font-weight:700; cursor:pointer;";
      b.addEventListener("click", () => { close(); try { opts.action.onClick(); } catch (e) { /* la acción maneja sus errores */ } });
      el.appendChild(b);
    }
    const box = ensureContainer();
    // Los avisos nunca quedan tapados por la franja de contingencia/sesión (static/js/contingency.js, `data-golden-banner`): van por ENCIMA (z-index) y desplazados bajo ella.
    const banner = document.querySelector && document.querySelector("[data-golden-banner]");
    box.style.top = (banner && banner.getBoundingClientRect ? Math.ceil(banner.getBoundingClientRect().bottom) + 12 : 20) + "px";
    box.appendChild(el);

    requestAnimationFrame(() => {
      el.style.opacity = "1";
      el.style.transform = "translateX(0)";
    });

    setTimeout(close, opts.action ? (opts.duration || 8000) : 3200);
    return { close };
  };

  /* opts.variant: "danger" (default, blanco + botón rojo, para borrar/sobrescribir) o
     "warning" (amarillo pastel, para advertir sin necesariamente ser destructivo — ej. "esta
     persona ya se había registrado, ¿seguro quieres registrarla de nuevo?"). opts.confirmLabel
     permite personalizar el texto del botón de confirmar. */
  /* Confirmación al pasar un evento a «Finalizado» (Fase 0): dice qué pasa, en vez del genérico «¿Cambiar el estado…?». */
  window.FINALIZE_CONFIRM = "¿Finalizar el evento? Desde ese momento nadie podrá registrar ni entrar con su rostro, y empieza el plazo de 7 días para borrar los rostros. Se puede reabrir después.";
  window.confirmStatusChange = function (newStatus, label) {
    if (newStatus === "finalizado") return window.showConfirm(window.FINALIZE_CONFIRM, { confirmLabel: "Sí, finalizar" });
    return window.showConfirm(`¿Cambiar el estado del evento a "${window.escapeHtml(label)}"?`);
  };
  window.escapeHtml = function (v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  };

  /* Cuadros de diálogo con el diseño nuevo (Fase 1.5, Ola 0): .gw-modal de design-system.css. Los tres comparten esta base: foco al abrir y al cerrar,
     Tab que no se sale del cuadro, role="dialog" y animación corta (sin ella con «reducir movimiento»). Se conservan los id de los botones. */
  function openDialog(cfg) {
    const prevFocus = document.activeElement;
    const backdrop = document.createElement("div");
    backdrop.className = "gw-modal-backdrop gw-modal-backdrop--top";
    backdrop.setAttribute("data-open", "true");
    const dlg = document.createElement("div");
    dlg.className = "gw-modal gw-modal--dialog" + (cfg.warning ? " gw-modal--warn" : "");
    dlg.setAttribute("role", "dialog");
    dlg.setAttribute("aria-modal", "true");
    dlg.setAttribute("aria-label", cfg.title);
    dlg.innerHTML =
      '<div class="gw-modal__head"><h2 class="gw-modal__title"></h2></div>' +
      '<div class="gw-modal__body"></div>' +
      '<div class="gw-modal__foot"></div>';
    dlg.querySelector(".gw-modal__title").textContent = cfg.title;
    dlg.querySelector(".gw-modal__body").innerHTML = cfg.bodyHtml;
    const foot = dlg.querySelector(".gw-modal__foot");
    cfg.buttons.forEach((b) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.id = b.id;
      btn.className = "gw-btn " + b.cls;
      btn.textContent = b.label;
      foot.appendChild(btn);
    });
    backdrop.appendChild(dlg);
    document.body.appendChild(backdrop);
    function close() {
      backdrop.remove();
      document.removeEventListener("keydown", onKey, true);
      if (prevFocus && prevFocus.focus && document.contains(prevFocus)) { try { prevFocus.focus(); } catch (e) { /* el elemento ya no existe */ } }
    }
    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); if (cfg.onEscape) cfg.onEscape(); return; }
      if (e.key !== "Tab") return;
      const f = Array.from(dlg.querySelectorAll("button, input, select, textarea, a[href]")).filter((x) => !x.disabled);
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (!dlg.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
      else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", onKey, true);
    if (cfg.onBackdrop) backdrop.addEventListener("click", (e) => { if (e.target === backdrop) cfg.onBackdrop(); });
    return { backdrop, dlg, close };
  }
  window.openGwDialog = openDialog;

  /* showConfirm(message, { variant: "danger" (default: botón rojo, para borrar/sobrescribir) | "warning" (aviso amarillo: «¿seguro?» sin ser destructivo),
     confirmLabel, title, text }). Devuelve Promise<boolean>. Hacer clic afuera o Esc = cancelar (no es un formulario de datos).
     `message` es HTML (solo para texto propio de la app); si el mensaje lleva algo que escribió una persona, pásalo ESCAPADO (window.escapeHtml) o usa `opts.text`: texto plano que se escapa aquí (C1/C2, Fase 3). */
  window.showConfirm = function (message, opts) {
    opts = opts || {};
    const isWarning = opts.variant === "warning";
    return new Promise((resolve) => {
      let d;
      const done = (v) => { d.close(); resolve(v); };
      d = openDialog({
        title: opts.title || (isWarning ? "Ten en cuenta" : "Confirmar"),
        warning: isWarning,
        bodyHtml: '<p class="gw-modal__text">' + (opts.text != null ? window.escapeHtml(opts.text) : message) + "</p>",
        buttons: [
          { id: "toastConfirmCancel", cls: "gw-btn--secondary", label: "Cancelar" },
          { id: "toastConfirmOk", cls: isWarning ? "gw-btn--primary" : "gw-btn--danger", label: opts.confirmLabel || "Confirmar" },
        ],
        onEscape: () => done(false),
        onBackdrop: () => done(false),
      });
      d.dlg.querySelector("#toastConfirmCancel").addEventListener("click", () => done(false));
      d.dlg.querySelector("#toastConfirmOk").addEventListener("click", () => done(true));
      d.dlg.querySelector("#toastConfirmCancel").focus();
    });
  };

  /* Reemplazo de prompt() nativo (bug real de Sprint 2, QA local 2026-09-15: badge_editor.html
     usaba prompt() para "Guardar como plantilla" y el navegador lo rechazaba — "prompt() is not
     supported" — rompiendo la convención del proyecto de no usar diálogos nativos). Mismo patrón
     visual que showConfirm, pero con un campo de texto. Devuelve una Promise<string|null> (null
     si cancela o si el campo queda vacío). opts: { defaultValue, placeholder, confirmLabel }. */
  window.showPrompt = function (message, opts) {
    opts = opts || {};
    return new Promise((resolve) => {
      let d;
      const done = (v) => { d.close(); resolve(v); };
      d = openDialog({
        title: opts.title || "Escribe un dato",
        bodyHtml: '<div class="gw-field"><label class="gw-label" for="toastPromptInput">' + message + '</label>' +
                  '<input id="toastPromptInput" class="gw-input" type="text"></div>',
        buttons: [
          { id: "toastPromptCancel", cls: "gw-btn--secondary", label: "Cancelar" },
          { id: "toastPromptOk", cls: "gw-btn--primary", label: opts.confirmLabel || "Guardar" },
        ],
        onEscape: () => done(null),   // sin onBackdrop a propósito: un campo de texto no se cierra al hacer clic afuera (2026-09-16)
      });
      const input = d.dlg.querySelector("#toastPromptInput");
      input.value = opts.defaultValue || "";
      input.placeholder = opts.placeholder || "";
      const ok = () => done(input.value.trim() || null);
      d.dlg.querySelector("#toastPromptCancel").addEventListener("click", () => done(null));
      d.dlg.querySelector("#toastPromptOk").addEventListener("click", ok);
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); ok(); } });
      input.focus();
      input.select();
    });
  };

  /* Confirmación estándar de "esta persona ya se había registrado" — usada por recognize,
     checkin-cedula y el registro manual (mismo texto/estilo en los tres, para no duplicarlo).
     `times` (2026-09-16, pedido explícito): cuántas veces ya se registró/acreditó en este
     evento, para que el mensaje sea concreto en vez de un genérico "ya está registrada". */
  window.confirmDuplicateRegistration = function (data, times) {
    const name = data ? `${data.first_name || ""} ${data.last_name || ""}`.trim() : "";
    const timesText = times ? ` (ya lo hizo ${times} ${times === 1 ? "vez" : "veces"})` : "";
    return window.showConfirm(
      `${name ? `<strong>${window.escapeHtml(name)}</strong>` : "Esta persona"} ya había sido registrada/acreditada en este evento${timesText}.<br><br>` +
      `¿Seguro que deseas registrarla de nuevo? Hazlo solo si fue un error o realmente necesitas repetir el ingreso.`,
      { variant: "warning", confirmLabel: "Sí, registrar de nuevo" }
    );
  };

  /* Modal para preguntar a qué corresponde cada campo "opcional_N" nuevo (sin límite práctico) —
     usado por kiosk_roster.html (carga de Excel/CSV), 2026-09-22. Devuelve {opcional_1: "Talla de
     camisa", ...} o null si el operador cancela.
     `examples` (2026-09-16, pedido explícito, opcional): {opcional_1: ["Talla M", "Talla L"]} —
     hasta 2 valores reales de ESE campo tal como vienen en el archivo, para no tener que abrirlo
     y ubicar a qué corresponde a simple vista. */
  window.promptOptionalLabels = function (fields, examples) {
    examples = examples || {};
    const esc = window.escapeHtml;
    return new Promise((resolve) => {
      const rowsHtml = fields.map((f) => {
        const n = f.split("_")[1];
        const ex = examples[f] || [];
        const exHtml = ex.length
          ? '<p class="gw-hint">Ejemplo' + (ex.length > 1 ? "s" : "") + " en el archivo: <strong>" + ex.map((v) => esc(v)).join(", ") + "</strong></p>"
          : "";
        return '<div class="gw-field gw-modal__row"><label class="gw-label">¿A qué corresponde "Opcional ' + esc(n) + '"?</label>' +
               '<input class="gw-input" type="text" data-field="' + esc(f) + '" placeholder="Ej. Talla de camisa, Grupo, Restricción alimentaria...">' + exHtml + "</div>";
      }).join("");
      let d;
      const done = (v) => { d.close(); resolve(v); };
      d = openDialog({
        title: "Campos opcionales nuevos",
        bodyHtml: '<p class="gw-modal__text"><strong>Encontramos ' + fields.length + " campo(s) opcional(es) nuevo(s)</strong>. " +
                  "Dinos a qué corresponde cada uno para poder identificarlos más adelante (en reportes, etc.).</p>" + rowsHtml,
        buttons: [
          { id: "optLabelsCancel", cls: "gw-btn--secondary", label: "Cancelar" },
          { id: "optLabelsOk", cls: "gw-btn--primary", label: "Guardar y continuar" },
        ],
        onEscape: () => done(null),
      });
      d.dlg.querySelector("#optLabelsCancel").addEventListener("click", () => done(null));
      d.dlg.querySelector("#optLabelsOk").addEventListener("click", () => {
        const labels = {};
        d.dlg.querySelectorAll("input[data-field]").forEach((input) => {
          const val = input.value.trim();
          if (val) labels[input.dataset.field] = val;
        });
        done(labels);
      });
      const first = d.dlg.querySelector("input[data-field]");
      if (first) first.focus();
    });
  };

  /* Spinner de carga genérico (Sprint 2.2 Fase D, 2026-09-16) — pedido explícito: si algo se
     demora (subir un roster, guardar una plantilla, escanear una foto), mostrar un círculo
     girando en vez de dejar el botón "quieto" sin decir si está funcionando o si se colgó.
     Uso: setButtonLoading(btn, true, "Cargando...") antes del fetch, setButtonLoading(btn, false)
     en el finally — restaura el label/HTML original automáticamente. */
  let spinnerStyleInjected = false;
  function ensureSpinnerStyle() {
    if (spinnerStyleInjected) return;
    spinnerStyleInjected = true;
    const style = document.createElement("style");
    style.textContent = `
      @keyframes goldenSpin { to { transform: rotate(360deg); } }
      .golden-btn-spinner {
        display:inline-block; width:14px; height:14px; border-radius:50%;
        border:2px solid rgba(0,0,0,0.25); border-top-color: currentColor;
        animation: goldenSpin 0.7s linear infinite; margin-right:8px; vertical-align:-2px;
      }
    `;
    document.head.appendChild(style);
  }

  ensureSpinnerStyle();  // inyectado al cargar toast.js, no solo la primera vez que se use un botón — así cualquier otro uso directo de .golden-btn-spinner (ej. badge_editor.html) también lo tiene disponible.

  window.setButtonLoading = function (btn, isLoading, loadingText) {
    if (!btn) return;
    if (isLoading) {
      if (btn.dataset.originalHtml === undefined) btn.dataset.originalHtml = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = `<span class="golden-btn-spinner"></span>${loadingText || "Cargando..."}`;
    } else {
      btn.disabled = false;
      if (btn.dataset.originalHtml !== undefined) {
        btn.innerHTML = btn.dataset.originalHtml;
        delete btn.dataset.originalHtml;
      }
    }
  };
})();

/* Cierre de sesión y copia local del modo contingencia (Fase 3, docs/15): al enviar CUALQUIER formulario «/logout» de la aplicación se borra el roster local de este dispositivo
   (todos los `golden-contingency-*`), se avisa cuántos ingresos hechos sin red siguen sin sincronizar y se CONSERVA la cola hasta sincronizar (la sincroniza la próxima sesión que abra
   el registro de ese evento). Si la página tiene el cliente de contingencia, antes intenta sincronizar. Nunca impide salir por un fallo técnico: sin IndexedDB, sigue el cierre normal. */
(function () {
  const PREFIX = "golden-contingency-";
  const req = (r) => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
  const open = (name) => new Promise((res, rej) => { const r = indexedDB.open(name); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); r.onblocked = () => rej(new Error("blocked")); });

  async function pendingIn(name) {
    const db = await open(name);
    try { return db.objectStoreNames.contains("queue") ? await req(db.transaction(["queue"], "readonly").objectStore("queue").count()) : 0; } finally { db.close(); }
  }
  async function wipeRoster(name) {
    const db = await open(name);
    try {
      const stores = ["roster", "meta"].filter((s) => db.objectStoreNames.contains(s));
      if (!stores.length) return;
      await new Promise((res, rej) => { const t = db.transaction(stores, "readwrite"); stores.forEach((s) => t.objectStore(s).clear()); t.oncomplete = res; t.onerror = () => rej(t.error); });
    } finally { db.close(); }
  }
  window.GoldenLogoutCleanup = async function () {
    const GC = window.GoldenContingency && window.GoldenContingency.instance;
    if (GC && GC.beforeLogout) { try { await GC.beforeLogout(); } catch (e) { /* seguir con el cierre */ } }
    const names = ((await indexedDB.databases()) || []).map((d) => d.name).filter((n) => n && n.startsWith(PREFIX));
    let pending = 0;
    for (const n of names) pending += await pendingIn(n);
    // Bandeja de salida (B8): altas hechas sin red que aún no se enviaron (el estado va en claro; los datos personales, cifrados). Se conservan hasta enviarlas o hasta que caduquen (7 días).
    const outboxNames = ((await indexedDB.databases()) || []).map((d) => d.name).filter((n) => n && n.startsWith("golden-outbox-"));
    let outboxPending = 0;
    for (const n of outboxNames) {
      try {
        const db = await open(n);
        try { if (db.objectStoreNames.contains("ops")) outboxPending += (await req(db.transaction(["ops"], "readonly").objectStore("ops").getAll())).filter((o) => o.status !== "ok").length; } finally { db.close(); }
      } catch (e) { /* sin acceso: no se cuenta */ }
    }
    if (outboxPending > 0 && window.showConfirm) {
      const ok = await window.showConfirm(`Quedan <strong>${outboxPending}</strong> persona(s) nueva(s) sin enviar en este dispositivo (se registraron sin conexión). Se conservan, cifradas, y se enviarán cuando vuelvas a iniciar sesión y abras el registro de ese evento; si no se envían en 7 días caducan. ¿Cerrar sesión de todos modos?`);
      if (!ok) return false;
    }
    if (pending > 0 && window.showConfirm) {
      const ok = await window.showConfirm(`Quedan <strong>${pending}</strong> ingreso(s) sin sincronizar en este dispositivo (se hicieron sin conexión). Se conservarán y se enviarán cuando vuelvas a iniciar sesión y abras el registro de ese evento.<br><br>¿Cerrar sesión de todos modos?`, { variant: "warning", confirmLabel: "Cerrar sesión" });
      if (!ok) return false;
    }
    for (const n of names) await wipeRoster(n);
    return true;
  };
  document.addEventListener("submit", function (e) {
    const f = e.target;
    if (!f || !f.getAttribute || f.__loggingOut || !/\/logout$/.test(f.getAttribute("action") || "")) return;
    if (!window.indexedDB || typeof indexedDB.databases !== "function") return;      // sin soporte: cierre normal
    e.preventDefault();
    window.GoldenLogoutCleanup().then((go) => go, () => true).then((go) => { if (go) { f.__loggingOut = true; f.submit(); } });
  });
})();

/* Puerta central de inactividad de la pestaña (3-nov-2026, docs/22): con la pestaña abierta y VISIBLE pero sin que nadie toque nada, la base de datos debe poder dormirse (Neon, 5 min sin consultas).
   `GW.idle` es true cuando no hubo clic, tecla, toque, scroll ni movimiento del ratón en los últimos 60 s (`window.GW_IDLE_PAUSE_MS` lo cambia); al volver cualquier actividad pasa a false y se ejecutan
   AL INSTANTE los refrescos registrados (el ping de sesión incluido: si la sesión se reemplazó o venció, se entera ahí). `GW.poll(fn, ms)` es un setInterval que NO corre mientras `GW.idle`, y `GW.onResume(fn, once)`
   registra algo para el regreso. Solo se pausa lo que consulta la base: el chequeo de /health (sin base) y el vaciado de la cola sin conexión NO usan esta puerta. Distinto del cierre de sesión (app/idle.py):
   la sesión sigue contando desde la última actividad REAL. No se usa en pantallas de exhibición ni en páginas públicas. */
(function () {
  if (window.GW && window.GW.createIdleGate) return;
  function createGate(d) {
    const g = { idle: false, idleMs: d.idleMs || 60000, last: d.now(), resume: [], once: [] };
    const emit = (name) => { try { if (d.emit) d.emit(name); } catch (e) { /* sin eventos */ } };
    g.activity = function () {
      g.last = d.now();
      if (!g.idle) return;
      g.idle = false; emit("gw:resume");
      const once = g.once; g.once = [];
      g.resume.concat(once).forEach((fn) => { try { fn(); } catch (e) { /* un refresco que falla no frena a los demás */ } });
    };
    g.check = function () { if (!g.idle && d.now() - g.last >= g.idleMs) { g.idle = true; emit("gw:idle"); } };
    g.onResume = function (fn, once) { (once ? g.once : g.resume).push(fn); };
    g.poll = function (fn, ms) { g.resume.push(fn); return d.setInterval(function () { if (!g.idle) fn(); }, ms); };
    return g;
  }
  const hasDom = typeof document !== "undefined" && document && typeof document.addEventListener === "function";
  const gate = createGate({
    idleMs: Number(window.GW_IDLE_PAUSE_MS) || 60000,
    now: () => Date.now(),
    setInterval: (fn, ms) => setInterval(fn, ms),
    emit: (name) => { if (typeof window.dispatchEvent === "function" && typeof Event === "function") window.dispatchEvent(new Event(name)); },
  });
  gate.createIdleGate = createGate;
  window.GW = gate;
  if (hasDom) {
    ["click", "keydown", "pointerdown", "touchstart", "wheel", "scroll", "mousemove"].forEach((ev) => document.addEventListener(ev, () => gate.activity(), { capture: true, passive: true }));
    const t = setInterval(() => gate.check(), 5000);
    if (t && t.unref) t.unref();
  }
})();

/* Sesión única (26-oct-2026, app/sessions.py): si esta cuenta entró en otro dispositivo, el servidor responde 401 «session_replaced» a las peticiones de esta sesión. Aquí se detecta en CUALQUIER
   petición de la página: se avisa el evento `gw:session-replaced` (los sondeos y latidos se detienen), se muestra el motivo y se lleva al inicio de sesión en pocos segundos. Los ingresos hechos sin
   red (outbox / contingencia) NO se descartan: siguen guardados y se envían al volver a iniciar sesión. Las pantallas operativas piden `window.GW_SESSION_PING = true` para enterarse en
   menos de 10 s aunque estén quietas (una consulta mínima cada 8 s). */
(function () {
  if (window.__gwSessionGuard || typeof window.fetch !== "function") return;
  window.__gwSessionGuard = true;
  let replaced = false;
  window.addEventListener("gw:session-expired", () => { replaced = true; });      // sesión vencida por inactividad (static/js/idle-session.js): se detienen el sondeo y los latidos
  function onReplaced() {
    if (replaced) return;
    replaced = true;
    try { window.dispatchEvent(new Event("gw:session-replaced")); } catch (e) { /* sin eventos */ }
    const box = document.createElement("div");
    box.setAttribute("role", "alertdialog");
    box.style.cssText = "position:fixed;inset:0;z-index:99999;display:flex;align-items:center;justify-content:center;background:rgba(10,14,46,.82);padding:24px";
    box.innerHTML = '<div style="background:#fff;border-radius:16px;padding:24px 28px;max-width:440px;text-align:center;font:600 1.05rem system-ui,sans-serif;color:#0a0e2e"><div style="font-size:2rem">🔒</div><p style="margin:8px 0">Tu sesión se cerró porque entraste con esta cuenta en otro dispositivo.</p><p style="margin:8px 0;font-weight:400;font-size:.95rem">Te llevamos al inicio de sesión…</p></div>';
    (document.body || document.documentElement).appendChild(box);
    setTimeout(() => { window.location.href = "/login"; }, 3000);
  }
  const original = window.fetch;
  window.fetch = function () {
    return original.apply(this, arguments).then((res) => {
      if (res && res.status === 401 && !replaced) res.clone().json().then((d) => { if (d && d.detail === "session_replaced") onReplaced(); }, () => {});
      return res;
    });
  };
  if (window.GW_SESSION_PING) {
    const pingNow = () => { if (!replaced && document.visibilityState === "visible") original("/api/session/ping", { cache: "no-store", headers: { "X-Gw-Passive": "1" } }).then((res) => { if (res.status === 401) window.fetch("/api/session/ping"); }, () => {}); };
    if (window.GW && window.GW.poll) window.GW.poll(pingNow, 8000); else setInterval(pingNow, 8000);      // pestaña sin uso 60 s: no consulta la base; al volver, ping inmediato
  }
})();
