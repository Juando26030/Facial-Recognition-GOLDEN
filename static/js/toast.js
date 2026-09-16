/* Notificaciones tipo "toast" — reemplazo de alert()/confirm() para dar feedback de acciones
   CRUD sin bloquear la interfaz. Uso: showToast("Evento creado", "success" | "error"). */
(function () {
  let container = null;

  function ensureContainer() {
    if (container) return container;
    container = document.createElement("div");
    container.id = "toastContainer";
    container.style.cssText = `
      position: fixed; top: 20px; right: 20px; z-index: 9999;
      display: flex; flex-direction: column; gap: 10px; pointer-events: none;
    `;
    document.body.appendChild(container);
    return container;
  }

  window.showToast = function (message, type) {
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
    ensureContainer().appendChild(el);

    requestAnimationFrame(() => {
      el.style.opacity = "1";
      el.style.transform = "translateX(0)";
    });

    setTimeout(() => {
      el.style.opacity = "0";
      el.style.transform = "translateX(20px)";
      setTimeout(() => el.remove(), 300);
    }, 3200);
  };

  /* opts.variant: "danger" (default, blanco + botón rojo, para borrar/sobrescribir) o
     "warning" (amarillo pastel, para advertir sin necesariamente ser destructivo — ej. "esta
     persona ya se había registrado, ¿seguro quieres registrarla de nuevo?"). opts.confirmLabel
     permite personalizar el texto del botón de confirmar. */
  window.showConfirm = function (message, opts) {
    opts = opts || {};
    const isWarning = opts.variant === "warning";
    const palette = isWarning
      ? { boxBg: "#fff8e1", border: "3px solid #f0ad4e", text: "#7a5b00", btnBg: "#f0ad4e", btnText: "#3a2a00" }
      : { boxBg: "white", border: "none", text: "#333", btnBg: "#dc3545", btnText: "white" };
    const confirmLabel = opts.confirmLabel || "Confirmar";

    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.style.cssText = `
        position: fixed; inset: 0; background: rgba(10,14,46,0.45); z-index: 9998;
        display: flex; align-items: center; justify-content: center;
      `;
      const box = document.createElement("div");
      box.style.cssText = `
        background: ${palette.boxBg}; border: ${palette.border}; border-radius: 16px; padding: 1.8rem; max-width: 420px;
        box-shadow: 0 20px 60px rgba(0,0,0,0.3); font-family: var(--font-body, sans-serif);
      `;
      box.innerHTML = `
        <p style="color:${palette.text}; margin-bottom:1.4rem; line-height:1.4; font-size:${isWarning ? "1.05rem" : "1rem"}; ${isWarning ? "font-weight:600;" : ""}">${message}</p>
        <div style="display:flex; justify-content:flex-end; gap:10px;">
          <button id="toastConfirmCancel" style="border:1px solid #ccc; background:white; border-radius:20px; padding:8px 18px; cursor:pointer; font-weight:600;">Cancelar</button>
          <button id="toastConfirmOk" style="border:none; background:${palette.btnBg}; color:${palette.btnText}; border-radius:20px; padding:8px 18px; cursor:pointer; font-weight:700;">${confirmLabel}</button>
        </div>
      `;
      overlay.appendChild(box);
      document.body.appendChild(overlay);
      box.querySelector("#toastConfirmCancel").addEventListener("click", () => { overlay.remove(); resolve(false); });
      box.querySelector("#toastConfirmOk").addEventListener("click", () => { overlay.remove(); resolve(true); });
      overlay.addEventListener("click", (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } });
    });
  };

  /* Reemplazo de prompt() nativo (bug real de Sprint 2, QA local 2026-09-15: badge_editor.html
     usaba prompt() para "Guardar como plantilla" y el navegador lo rechazaba — "prompt() is not
     supported" — rompiendo la convención del proyecto de no usar diálogos nativos). Mismo patrón
     visual que showConfirm, pero con un campo de texto. Devuelve una Promise<string|null> (null
     si cancela o si el campo queda vacío). opts: { defaultValue, placeholder, confirmLabel }. */
  window.showPrompt = function (message, opts) {
    opts = opts || {};
    const defaultValue = opts.defaultValue || "";
    const confirmLabel = opts.confirmLabel || "Guardar";
    const placeholder = opts.placeholder || "";

    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.style.cssText = `
        position: fixed; inset: 0; background: rgba(10,14,46,0.45); z-index: 9998;
        display: flex; align-items: center; justify-content: center;
      `;
      const box = document.createElement("div");
      box.style.cssText = `
        background: white; border-radius: 16px; padding: 1.8rem; max-width: 420px; width: 90%;
        box-shadow: 0 20px 60px rgba(0,0,0,0.3); font-family: var(--font-body, sans-serif);
      `;
      const escapedDefault = String(defaultValue).replace(/&/g, "&amp;").replace(/"/g, "&quot;");
      const escapedPlaceholder = String(placeholder).replace(/&/g, "&amp;").replace(/"/g, "&quot;");
      box.innerHTML = `
        <p style="color:#333; margin-bottom:1rem; line-height:1.4;">${message}</p>
        <input id="toastPromptInput" type="text" value="${escapedDefault}" placeholder="${escapedPlaceholder}"
               style="width:100%; box-sizing:border-box; border:1px solid #ccc; border-radius:10px; padding:10px 12px; font-size:1rem; margin-bottom:1.4rem;">
        <div style="display:flex; justify-content:flex-end; gap:10px;">
          <button id="toastPromptCancel" style="border:1px solid #ccc; background:white; border-radius:20px; padding:8px 18px; cursor:pointer; font-weight:600;">Cancelar</button>
          <button id="toastPromptOk" style="border:none; background:var(--golden-primary, #D4AF37); color:#1a1200; border-radius:20px; padding:8px 18px; cursor:pointer; font-weight:700;">${confirmLabel}</button>
        </div>
      `;
      overlay.appendChild(box);
      document.body.appendChild(overlay);
      const input = box.querySelector("#toastPromptInput");
      input.focus();
      input.select();
      function finish(value) { overlay.remove(); resolve(value); }
      box.querySelector("#toastPromptCancel").addEventListener("click", () => finish(null));
      box.querySelector("#toastPromptOk").addEventListener("click", () => finish(input.value.trim() || null));
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); finish(input.value.trim() || null); }
        else if (e.key === "Escape") { finish(null); }
      });
      overlay.addEventListener("click", (e) => { if (e.target === overlay) finish(null); });
    });
  };

  /* Confirmación estándar de "esta persona ya se había registrado" — usada por recognize,
     checkin-cedula y el registro manual (mismo texto/estilo en los tres, para no duplicarlo). */
  window.confirmDuplicateRegistration = function (data) {
    const name = data ? `${data.first_name || ""} ${data.last_name || ""}`.trim() : "";
    return window.showConfirm(
      `⚠️ ${name ? `<strong>${name}</strong>` : "Esta persona"} ya había sido registrada/acreditada en este evento.<br><br>` +
      `¿Seguro que deseas registrarla de nuevo? Hazlo solo si fue un error o realmente necesitas repetir el ingreso.`,
      { variant: "warning", confirmLabel: "Sí, registrar de nuevo" }
    );
  };

  /* Modal para preguntar a qué corresponde cada campo "opcional_N" nuevo (hasta 30 posibles) —
     compartido entre kiosk_roster.html (carga de Excel/CSV) y kiosk_registro.html (alta manual
     individual, botón "+ Agregar campo opcional"), 2026-09-22. Devuelve {opcional_1: "Talla de
     camisa", ...} o null si el operador cancela. */
  window.promptOptionalLabels = function (fields) {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.style.cssText = `position:fixed; inset:0; background:rgba(10,14,46,0.45); z-index:9998; display:flex; align-items:center; justify-content:center; padding:1rem;`;
      const box = document.createElement("div");
      box.style.cssText = `background:white; border-radius:16px; padding:1.8rem; max-width:460px; width:100%; box-shadow:0 20px 60px rgba(0,0,0,0.3); font-family: var(--font-body, sans-serif); max-height:80vh; overflow-y:auto;`;

      const rowsHtml = fields.map(f => {
        const n = f.split("_")[1];
        return `<div class="badge-input-group" style="margin-top:0.8rem;">
                <label>¿A qué corresponde "Opcional ${n}"?</label>
                <input type="text" data-field="${f}" placeholder="Ej. Talla de camisa, Grupo, Restricción alimentaria...">
            </div>`;
      }).join("");

      box.innerHTML = `
            <p style="color:#333; margin-bottom:0.5rem; line-height:1.4;">
                <strong>Encontramos ${fields.length} campo(s) opcional(es) nuevo(s)</strong>.
                Dinos a qué corresponde cada uno para poder identificarlos más adelante (en reportes, etc.).
            </p>
            ${rowsHtml}
            <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:1.5rem;">
                <button id="optLabelsCancel" style="border:1px solid #ccc; background:white; border-radius:20px; padding:8px 18px; cursor:pointer; font-weight:600;">Cancelar</button>
                <button id="optLabelsOk" style="border:none; background: var(--golden-primary); color:#1a1200; border-radius:20px; padding:8px 18px; cursor:pointer; font-weight:700;">Guardar y continuar</button>
            </div>
        `;
      overlay.appendChild(box);
      document.body.appendChild(overlay);

      box.querySelector("#optLabelsCancel").addEventListener("click", () => { overlay.remove(); resolve(null); });
      box.querySelector("#optLabelsOk").addEventListener("click", () => {
        const labels = {};
        box.querySelectorAll("input[data-field]").forEach(input => {
          const val = input.value.trim();
          if (val) labels[input.dataset.field] = val;
        });
        overlay.remove();
        resolve(labels);
      });
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
