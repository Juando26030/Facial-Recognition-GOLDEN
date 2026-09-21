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
    if (config.field_type === 'consent') {
      // Casilla de tratamiento de datos (ítem 16): la política se lee justo debajo del check.
      const checked = String(val).trim().toLowerCase() === 'true' ? 'checked' : '';
      return `<label style="display:flex; gap:8px; align-items:flex-start; font-weight:400; text-transform:none; cursor:pointer;">
        <input type="checkbox" name="${key}" value="true" ${checked} ${requiredAttr} style="width:18px; height:18px; flex:0 0 auto; margin-top:2px;">
        <span style="font-size:0.82rem; color:#555; line-height:1.35; white-space:pre-line;">${esc(config.help_text)}</span>
      </label>`;
    }
    if (config.field_type === 'signature') {
      // Captura de firma (ítem 10): política pequeña junto al lienzo. El input oculto lleva un
      // marcador ("1") cuando hay firma, para que "obligatorio" funcione con la validación
      // normal; la imagen en sí se sube aparte (FieldRender.saveSignatures) tras guardar.
      return `<div class="sig-wrap" data-sig-key="${key}" data-user-id="${esc(config.__userId || '')}" style="display:flex; gap:12px; flex-wrap:wrap; align-items:flex-start;">
        <div style="flex:1 1 160px; font-size:0.72rem; color:#666; line-height:1.35; white-space:pre-line;">${esc(config.help_text)}</div>
        <div style="flex:1 1 260px;">
          <canvas class="sig-canvas" width="480" height="180" style="width:100%; max-width:360px; aspect-ratio:8/3; border:1px dashed #999; border-radius:8px; background:#fff; touch-action:none; cursor:crosshair;"></canvas>
          <input type="hidden" name="${key}" value="${val ? '1' : ''}" ${requiredAttr}>
          <div><button type="button" class="sig-clear" style="border:1px solid #ccc; background:white; border-radius:14px; padding:3px 12px; font-size:0.75rem; cursor:pointer;">Borrar firma</button></div>
        </div>
      </div>`;
    }
    if (config.field_type === 'boolean') {
      const checked = String(val).trim().toLowerCase() === 'true' ? 'checked' : '';
      return `<input type="checkbox" name="${key}" value="true" ${checked} ${requiredAttr} style="width:18px; height:18px;">`;
    }
    // text_short (default)
    return `<input type="text" name="${key}" value="${esc(val)}" ${requiredAttr} style="width:100%; box-sizing:border-box; border:1px solid #ccc; border-radius:8px; padding:8px 10px; font-size:0.95rem;">`;
  }

  /* Activa los lienzos de firma dentro de `root` (dibujo con mouse, dedo o lápiz vía Pointer
     Events). `opts.existingUrl(key)` (opcional) devuelve la URL de una firma ya guardada para
     mostrarla de entrada. */
  function initSignatures(root, opts) {
    root.querySelectorAll('.sig-wrap').forEach((wrap) => {
      if (wrap.dataset.ready) return;
      wrap.dataset.ready = '1';
      const canvas = wrap.querySelector('.sig-canvas');
      const hidden = wrap.querySelector('input[type="hidden"]');
      const ctx = canvas.getContext('2d');
      ctx.lineWidth = 3; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#111';
      let drawing = false;
      wrap._dirty = false;
      const pos = (e) => {
        const r = canvas.getBoundingClientRect();
        return [(e.clientX - r.left) * canvas.width / r.width, (e.clientY - r.top) * canvas.height / r.height];
      };
      canvas.addEventListener('pointerdown', (e) => {
        drawing = true; canvas.setPointerCapture(e.pointerId);
        const [x, y] = pos(e); ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + 0.1, y + 0.1); ctx.stroke();
        e.preventDefault();
      });
      canvas.addEventListener('pointermove', (e) => {
        if (!drawing) return;
        const [x, y] = pos(e); ctx.lineTo(x, y); ctx.stroke();
      });
      const end = () => { if (drawing) { drawing = false; wrap._dirty = true; hidden.value = '1'; } };
      canvas.addEventListener('pointerup', end);
      canvas.addEventListener('pointercancel', end);
      wrap.querySelector('.sig-clear').addEventListener('click', () => {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        wrap._dirty = true; hidden.value = '';
      });
      const url = opts && opts.existingUrl ? opts.existingUrl(wrap.dataset.sigKey) : null;
      if (url) {
        const img = new Image();
        img.onload = () => { ctx.drawImage(img, 0, 0, canvas.width, canvas.height); hidden.value = '1'; };
        img.src = url;
      }
    });
  }

  /* Sube (o borra, si quedó vacía) las firmas modificadas dentro de `root` para `userId` — se
     llama DESPUÉS de guardar a la persona, porque la firma cuelga de (evento, persona). */
  async function saveSignatures(root, userId) {
    const base = `/api/events/${window.EVENT_ID}/users/${encodeURIComponent(userId)}/signature/`;
    for (const wrap of root.querySelectorAll('.sig-wrap')) {
      if (!wrap._dirty) continue;
      const key = wrap.dataset.sigKey;
      const empty = !wrap.querySelector('input[type="hidden"]').value;
      const res = empty
        ? await fetch(base + key, { method: 'DELETE' })
        : await fetch(base + key, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image: wrap.querySelector('canvas').toDataURL('image/png') }) });
      if (!res.ok) throw new Error('No se pudo guardar la firma');
      wrap._dirty = false;
    }
  }

  /* Aviso de correo ya registrado (ítem 20): al salir del campo correo (o dejar de escribir), consulta
     el backend y muestra un aviso naranja bajo el campo. Solo informa, no bloquea el guardado.
     `getExcludeId()` = cédula de la persona que se edita (su propio correo no cuenta). */
  function watchEmail(root, getExcludeId) {
    const input = root.querySelector('input[name="email"]');
    if (!input) return;
    const note = document.createElement('div');
    note.style.cssText = 'font-size:0.75rem; color:#b26a00; margin-top:4px; display:none;';
    input.insertAdjacentElement('afterend', note);
    let timer = null, seq = 0;
    async function check() {
      const value = input.value.trim();
      const mine = ++seq;
      if (!value.includes('@')) { note.style.display = 'none'; return; }
      try {
        const qs = new URLSearchParams({ event_id: window.EVENT_ID, email: value, exclude_id: getExcludeId ? (getExcludeId() || '') : '' });
        const data = await (await fetch('/api/email-check?' + qs)).json();
        if (mine !== seq) return;
        if (data.exists) {
          note.textContent = '⚠️ Este correo ya está registrado a nombre de ' + data.matches.map(m => `${m.name || 'sin nombre'} (${m.id})`).join(', ') + '.';
          note.style.display = 'block';
        } else note.style.display = 'none';
      } catch (e) { /* solo es un aviso: si falla la consulta, no molesta */ }
    }
    input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(check, 500); });
    input.addEventListener('blur', () => { clearTimeout(timer); check(); });
  }

  window.FieldRender = { renderControl, initSignatures, saveSignatures, watchEmail };
})();
