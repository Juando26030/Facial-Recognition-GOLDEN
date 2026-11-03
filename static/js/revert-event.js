/* Devolver un evento «En proceso» a «Creado» (solo admin y super_admin; app/routers/events.py `revert_to_created`).
   `revertEventToCreated(eventId)` muestra la ventana de confirmación (nombre del evento, cuántas personas e ingresos tiene y el aviso del quiosco), pide un motivo opcional y llama al servidor.
   Devuelve una promesa con true si el evento volvió a «Creado». No borra nada. Requiere toast.js. */
(function () {
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  window.revertEventToCreated = async function (eventId) {
    let info;
    try {
      const r = await fetch(`/api/events/${eventId}/revert-to-created`, { cache: "no-store" });
      info = await r.json();
      if (!r.ok) { showToast(info.detail || "No se pudo consultar el evento", "error"); return false; }
    } catch (e) {
      showToast("Error de red", "error");
      return false;
    }
    if (!info.allowed) { showToast("Solo un evento «En proceso» se puede devolver a «Creado».", "error"); return false; }
    const ok = await showConfirm(
      `¿Devolver el evento <strong>${esc(info.name)}</strong> a <strong>Creado</strong>?<br><br>` +
      `Hoy tiene <strong>${info.attendees}</strong> personas y <strong>${info.access_logs}</strong> registros de acceso. <strong>No se borra nada</strong>: solo cambia el estado y queda anotado quién lo hizo y cuándo.<br><br>` +
      `⚠️ <strong>El quiosco dejará de registrar y reconocer hasta que vuelva a estar en curso.</strong> Los quioscos sin conexión podrán sincronizar lo que registraron antes del cambio durante ${info.sync_days} días.`,
      { variant: "warning", confirmLabel: "Sí, devolver a Creado" });
    if (!ok) return false;
    const reason = await showPrompt("Motivo (opcional). Cancela o déjalo vacío si no hay motivo:", { confirmLabel: "Devolver", placeholder: "Ej.: se abrió por error" });
    try {
      const res = await fetch(`/api/events/${eventId}/revert-to-created`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: reason || null }) });
      const data = await res.json().catch(() => ({}));
      showToast(res.ok ? "El evento volvió a «Creado»" : (data.detail || "No se pudo devolver el evento"), res.ok ? "success" : "error");
      return res.ok;
    } catch (e) {
      showToast("Error de red", "error");
      return false;
    }
  };
})();
