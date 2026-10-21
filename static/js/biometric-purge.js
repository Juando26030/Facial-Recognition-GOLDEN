/* «Borrar fotos del evento» (admin+): modal propio (toast.js) que explica qué se borra y qué no y pide escribir el nombre del evento.
   Lo usan Estadísticas y Parámetros. purgeEventBiometrics(eventId) → Promise<{ok, data}|null> (null si canceló). */
(function () {
  const esc = (t) => String(t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  window.purgeEventBiometrics = async function (eventId) {
    const base = `/api/events/${eventId}`;
    const info = await (await fetch(`${base}/privacy`)).json();
    const typed = await showPrompt(
      `<b>Borrar fotos del evento</b><br><br>Se borrarán <b>de forma definitiva</b> las <b>fotos y los vectores del rostro</b> de las personas de este evento (${info.with_biometrics} con rostro guardado).<br>` +
      `<b>No</b> se borra nada más: nombres, cédulas, registros de ingreso y formularios se conservan. Quien también esté en otro evento abierto con reconocimiento facial se omite.<br><br>` +
      `Para confirmar escribe el nombre del evento:<br><b>${esc(info.event_name)}</b>`,
      { placeholder: 'Nombre del evento', confirmLabel: 'Borrar fotos' });
    if (typed === null) return null;
    const r = await fetch(`${base}/biometrics/purge`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm_name: typed }) });
    const data = await r.json().catch(() => ({}));
    return { ok: r.ok, data };
  };
  window.purgeEventMessage = (d) => `Se borraron ${d.deleted} rostro(s).` + (d.kept_in_other_events ? ` Se omitieron ${d.kept_in_other_events} (${d.kept_reason}).` : '');
})();
