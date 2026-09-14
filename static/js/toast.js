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
})();
