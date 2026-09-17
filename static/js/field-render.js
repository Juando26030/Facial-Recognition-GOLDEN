/* Parámetros del Evento (Sprint 2.2, 2026-09-16) — un único renderer de control de formulario
   compartido entre el alta manual (kiosk_registro.html) y la edición desde el Directorio
   (directory.js: buildEditModal), para que ambos generen exactamente el mismo tipo de campo
   (texto corto/largo, lista desplegable con sus opciones, booleano) según lo que se configuró en
   /kiosk/{event_id}/parametros — antes cada uno tenía sus propios <input> fijos hardcodeados. */
(function () {
  function esc(v) {
    return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }

  /* Devuelve solo el HTML del control (name=config.key ya puesto) — quien llame decide cómo
     envolverlo (label, layout), cada template ya tiene su propio estilo para eso. */
  function renderControl(config, value) {
    const key = config.key;
    const requiredAttr = config.required ? 'required' : '';
    const val = value == null ? '' : value;

    if (config.field_type === 'text_long') {
      return `<textarea name="${key}" rows="3" ${requiredAttr} style="width:100%; box-sizing:border-box; border:1px solid #ccc; border-radius:8px; padding:8px 10px; font-size:0.95rem; font-family:inherit;">${esc(val)}</textarea>`;
    }
    if (config.field_type === 'select') {
      const options = config.options || [];
      const opts = options.map(o => `<option value="${esc(o)}" ${String(o) === String(val) ? 'selected' : ''}>${esc(o)}</option>`).join('');
      return `<select name="${key}" ${requiredAttr} style="width:100%; box-sizing:border-box; border:1px solid #ccc; border-radius:8px; padding:8px 10px; font-size:0.95rem;">
        <option value="">Selecciona…</option>${opts}
      </select>`;
    }
    if (config.field_type === 'boolean') {
      const checked = String(val).trim().toLowerCase() === 'true' ? 'checked' : '';
      return `<input type="checkbox" name="${key}" value="true" ${checked} ${requiredAttr} style="width:18px; height:18px;">`;
    }
    // text_short (default)
    return `<input type="text" name="${key}" value="${esc(val)}" ${requiredAttr} style="width:100%; box-sizing:border-box; border:1px solid #ccc; border-radius:8px; padding:8px 10px; font-size:0.95rem;">`;
  }

  window.FieldRender = { renderControl };
})();
