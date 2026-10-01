/* Directorio en vivo, usado por kiosk_registro.html (vista de Registro unificada, 2026-09-21 —
   antes eran dos templates separados, kiosk.html "Facial" y kiosk_cedula.html "Cédula", con esta
   lógica de tabla duplicada entre ambos). Patrón Editar/Guardar/Eliminar + botón "Acreditar"
   opcional (marca a alguien como Registrado sin pasar por el escáner) + mountSearch() para los
   3 campos de búsqueda en vivo y el atajo de lector de código de barras. */
(function () {
  function withEvent(url) {
    return url + (url.includes('?') ? '&' : '?') + 'event_id=' + window.EVENT_ID;
  }

  /* Búsqueda insensible a tildes/ñ + "prefijo por palabra" (no substring en cualquier posición)
     — Sprint 2 Fix 1, 2026-09-15: buscar "maria"/"MARIA" debía encontrar "María", y buscar "Ma"
     debía encontrar "María" pero NO "Amaya" (ninguna de sus palabras EMPIEZA con "ma", aunque la
     contenga en medio). Mismo criterio que `_matches_by_word_prefix` en routers/events.py — se
     mantiene la misma lógica en los dos lados a propósito. */
  function stripAccents(text) {
    return String(text || '').normalize('NFD').replace(/[̀-ͯ]/g, '');
  }

  function wordsOf(text) {
    return stripAccents(text).toLowerCase().match(/\w+/g) || [];
  }

  /* Distancia de edición con transposición (Damerau/OSA): "jaun" vs "juan" = 1. Misma lógica que
     `_edit_distance` en routers/events.py. */
  function editDistance(a, b) {
    let prev2 = null, prev = Array.from({ length: b.length + 1 }, (_, j) => j);
    for (let i = 1; i <= a.length; i++) {
      const cur = [i];
      for (let j = 1; j <= b.length; j++) {
        const cost = a[i - 1] === b[j - 1] ? 0 : 1;
        cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
        if (prev2 && i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) cur[j] = Math.min(cur[j], prev2[j - 2] + 1);
      }
      prev2 = prev; prev = cur;
    }
    return prev[b.length];
  }

  /* ¿La palabra escrita `qw` corresponde a la palabra guardada `hw`? (ítem 2, reunión 2026-09-21)
     - prefijo normal ("sebas" -> "sebastian"),
     - apodo al revés: se escribe la forma larga y en base hay la corta de 4+ letras ("sebastian" -> "sebas"),
     - error de tipeo: 4-6 letras con 1 error, 7+ con 2 ("juliana" -> "yuliana", "jaun" -> "juan"),
       comparando también contra el inicio de la palabra para que funcione mientras se escribe. */
  function wordMatches(qw, hw) {
    if (hw.startsWith(qw)) return true;
    if (hw.length >= 4 && qw.startsWith(hw)) return true;
    const shortLen = Math.min(qw.length, hw.length);
    if (shortLen < 4) return false;
    const limit = shortLen <= 6 ? 1 : 2;
    return editDistance(qw, hw) <= limit || editDistance(qw, hw.slice(0, qw.length)) <= limit;
  }

  /* Cada palabra escrita debe corresponder a alguna palabra distinta de lo guardado, en cualquier
     orden: "David Juzga" encuentra "Juan David Ramirez Juzga". */
  function matchesWordPrefix(haystack, query) {
    return matchesWords(wordsOf(haystack), wordsOf(query));
  }

  /* Igual que matchesWordPrefix pero con las palabras ya normalizadas (el buscador del Directorio las precalcula una vez por persona). */
  function matchesWords(haystackWords, queryWords) {
    if (!queryWords.length) return false;
    const available = haystackWords.slice();
    return queryWords.every(qw => {
      const idx = available.findIndex(hw => wordMatches(qw, hw));
      if (idx === -1) return false;
      available.splice(idx, 1);
      return true;
    });
  }

  /* Cédula vieja (código de barras) — Sprint 2 Parte 2, 2.1: el lector manda un CSV plano
     "cedula,nombre1,nombre2,apellido1,apellido2,fecha_nacimiento(AAAAMMDD)" en vez de solo el
     número suelto (muestra real confirmada: "1016100329,JHOAN,SEBASTIAN,ANGARITA,ROJAS,19980206").
     Si el texto no calza con este patrón (no tiene comas, o el primer segmento no es numérico),
     se sigue tratando como hoy: un ID suelto. Devuelve null en ese caso. */
  function parseOldCedulaBarcode(raw) {
    const text = String(raw || '').trim();
    if (!text.includes(',')) return null;
    const parts = text.split(',');
    if (parts.length < 5) return null;
    const cedula = parts[0].trim();
    if (!/^\d+$/.test(cedula)) return null;
    const nombres = [parts[1], parts[2]].map(p => (p || '').trim()).filter(Boolean).join(' ');
    const apellidos = [parts[3], parts[4]].map(p => (p || '').trim()).filter(Boolean).join(' ');
    return { cedula, nombres, apellidos };
  }

  /* Columnas visibles en la tabla (2026-09-16, pedido explícito de Juan David: la tabla de antes
     obligaba a hacer scroll horizontal con 10 columnas — ya no cabía en pantalla). El resto de
     los datos (cargo, entidad, teléfono, correo, opcionales) se muestran y editan SOLO dentro del
     modal de "Editar" (ver buildEditModal), no como <td> sueltos en la fila. opt_2 (antes
     "cantidad de empl") sigue deprecado, ni siquiera vive en el modal. */
  const FIELDS_ORDER = ['id', 'first_name', 'last_name', 'opt_1'];

  /* Mismos mínimos que el backend exige de verdad (PATCH /api/users/{id} = coordinador+, ver tabla
     de "Roles y permisos" en CLAUDE.md) — bug real encontrado en testing (DIR-06, 2026-09-21): el
     botón "Editar" se mostraba para digitador/cliente aunque el PATCH les fuera a dar 403 igual.
     Ocultar el botón entero es más claro que dejar que el usuario lo intente y falle.
     ADMIN_ROLES: corregir la cédula (User.id) sigue siendo admin+ solamente — afecta a la persona
     en TODOS los eventos del cliente, más sensible que el resto (sin cambios, Sprint 2.3).
     STATUS_ROLES (2026-09-17, pedido explícito: "asígnale ese permiso también a los
     coordinadores" — antes admin+ solamente): "Eliminar" y "Cambiar estado de registro" pasan a
     coordinador+, DESACOPLADO de ADMIN_ROLES (la cédula sigue admin+, esto ya no). */
  const EDIT_ROLES = ['digitador', 'coordinador', 'admin', 'super_admin'];  // 2026-09-23: el digitador temporal también edita datos (no cédula, ni estado a "No registrado", ni eliminar)
  const ADMIN_ROLES = ['admin', 'super_admin'];
  const STATUS_ROLES = ['coordinador', 'admin', 'super_admin'];
  const canEdit = EDIT_ROLES.includes(window.STAFF_ROLE);
  const isAdmin = ADMIN_ROLES.includes(window.STAFF_ROLE);
  const canManageStatus = STATUS_ROLES.includes(window.STAFF_ROLE);

  /* Acreditar SIN red (modo contingencia, static/js/contingency.js). `target`: {cedula} (lo escrito/escaneado, o la fila cargada con red) o {h} (fila de la lista local, que no tiene la
     cédula). Busca en la copia local; quien no está NO se admite; si ya consta como registrado o está en la cola pide la confirmación de DUPLICADO; si no, encola (client_id, marca de
     tiempo, huella; método `cedula` | `qr` | `manual`) y avisa. Devuelve lo encontrado o null. Las listas abiertas se actualizan por `accreditHooks`. */
  const accreditHooks = [];
  async function offlineAccredit(GC, target, method, cid) {
    const found = target.h ? await GC.findByHash(target.h) : await GC.scanLocal(target.cedula);
    if (found.status === 'expired') { showToast('No hay copia local vigente: verificar manualmente', 'error'); return null; }
    if (found.status === 'not_found') { showToast('No registrado: verificar manualmente', 'error'); return null; }
    if (found.duplicate && !(await confirmDuplicateRegistration({ first_name: found.person.n, last_name: '' }, undefined))) return null;
    await GC.enqueue(found, method, cid);
    showToast(`Acreditado: ${found.person.n}`, 'success');
    accreditHooks.forEach((f) => f(found));
    return found;
  }

  /* Editar SIN red (contingencia): modal limitado. Solo el nombre (lectura) y el «Estado de registro»; el resto de campos no se ofrece y se avisa. «Registrado» se encola igual que un escaneo
     (client_id, huella de la copia local, método `manual`), con el aviso de DUPLICADO si ya consta o está en la cola. Guardar nunca dice «Error de red» genérico. Devuelve los controles
     (para las pruebas). */
  const OFFLINE_EDIT_NOTICE = 'Sin conexión: solo se puede cambiar el estado de registro; para editar datos espera a que vuelva la red';
  function buildOfflineEditModal(user, GC) {
    const mk = (tag, text, css) => { const el = document.createElement(tag); if (text) el.textContent = text; if (css) el.style.cssText = css; return el; };
    const overlay = mk('div', '', 'position:fixed; inset:0; background:rgba(10,14,46,0.45); z-index:9997; display:flex; align-items:center; justify-content:center; overflow:auto; padding:2rem 1rem;');
    overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-label', 'Editar persona sin conexión');
    const box = mk('div', '', 'background:white; border-radius:16px; padding:1.8rem; max-width:520px; width:100%; box-shadow:0 20px 60px rgba(0,0,0,0.3); font-family: var(--font-body, sans-serif);');
    const notice = mk('p', OFFLINE_EDIT_NOTICE, 'background:#fff8e1; color:#7a5b00; border-left:4px solid #f0ad4e; padding:8px 12px; border-radius:8px; font-size:0.85rem; font-weight:600;');
    notice.setAttribute('role', 'status');
    const name = mk('input', '', 'width:100%; box-sizing:border-box; border:1px solid #ddd; border-radius:8px; padding:8px 10px; font-size:0.95rem; background:#f5f5f5; color:#555; margin-bottom:0.8rem;');
    name.value = `${user.first_name || ''} ${user.last_name || ''}`.trim(); name.readOnly = true; name.disabled = true; name.setAttribute('aria-label', 'Nombre (solo lectura)');
    const statusLabel = mk('label', 'Estado de registro', 'display:block; font-size:0.78rem; font-weight:700; color:#888; margin-bottom:4px;');
    const select = mk('select', '', 'width:100%; border:1px solid #ccc; border-radius:8px; padding:8px 10px; font-size:0.95rem;');
    [['no_registrado', 'No registrado'], ['registrado', 'Registrado']].forEach(([v, t]) => { const o = mk('option', t); o.value = v; select.appendChild(o); });
    select.value = 'registrado';                                              // igual que en línea: «Registrado» preseleccionado
    const actions = mk('div', '', 'display:flex; justify-content:flex-end; gap:10px; margin-top:1rem;');
    const cancel = mk('button', 'Cancelar', 'border:1px solid #ccc; background:white; border-radius:20px; padding:8px 18px; cursor:pointer; font-weight:600;'); cancel.type = 'button';
    const save = mk('button', 'Guardar cambios', 'border:none; background:var(--golden-primary,#D4AF37); color:#1a1200; border-radius:20px; padding:8px 18px; cursor:pointer; font-weight:700;'); save.type = 'button';
    [cancel, save].forEach((b) => actions.appendChild(b));
    [mk('h4', 'Editar persona', 'margin-top:0; color:var(--golden-dark);'), notice, name, statusLabel, select, actions].forEach((el) => box.appendChild(el));
    overlay.appendChild(box); document.body.appendChild(overlay);
    const close = () => overlay.remove();
    cancel.addEventListener('click', close);
    save.addEventListener('click', async () => {
      if (!GC.active()) { close(); showToast('Volvió la conexión: abre Editar de nuevo para ver todos los campos', 'success'); return; }
      if (select.value !== 'registrado') { showToast('Sin conexión: solo se puede registrar; para quitar un registro espera a que vuelva la red', 'error'); return; }
      save.disabled = true;
      try {
        const found = await offlineAccredit(GC, user.__h ? { h: user.__h } : { cedula: user.id }, 'manual');
        if (found) close();
      } finally { save.disabled = false; }
    });
    return { overlay, box, notice, name, select, save, cancel, close };
  }

  /* Modal flotante de edición (2026-09-16, reemplaza la edición inline contentEditable de antes —
     con 10 columnas en pantalla no cabía nada sin scroll horizontal). Mismos campos que el alta
     manual (incluidos los opcionales dinámicos de este evento, vía window.OPTIONAL_VARIABLES,
     inyectado igual que en badge_editor.html). "Estado de registro" y "Eliminar" viven ACÁ dentro
     (no como botones sueltos en la fila) y solo se muestran para admin+ — mismo mínimo que ya
     exigía el backend en DELETE /users/{id}/logs. Cada una de las dos dispara su propia
     confirmación aparte del botón "Guardar cambios" de arriba (pedido explícito: "cada vez que
     vaya a hacer una de estas dos salga la notificación de confirmación"). */
  function buildEditModal(user, opts) {
    const GCm = window.GoldenContingency && window.GoldenContingency.instance;
    if (GCm && GCm.active()) return buildOfflineEditModal(user, GCm);          // sin red: modal limitado (solo estado de registro)
    opts = opts || {};       // { method: 'biometrico' (el ingreso viene de una verificación facial), onSaved(id) }
    // Parámetros del Evento (2026-09-16): las 5 variables fijas + cada opcional_N ya rotulado,
    // con el tipo de control/obligatoriedad/opciones que se haya definido en
    // /kiosk/{event_id}/parametros — mismo FIELD_CONFIGS que usa el alta manual (ver
    // kiosk_registro.html), para que Editar y Registrar nuevo se comporten igual.
    const fieldConfigs = window.FIELD_CONFIGS || [];
    const extras = user.extra_fields || {};

    function esc(v) { return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/"/g, '&quot;'); }
    function fieldRow(label, name, value, type) {
      return `<div style="margin-bottom:0.8rem;">
        <label style="display:block; font-size:0.78rem; font-weight:700; color:#888; margin-bottom:4px;">${esc(label)} *</label>
        <input type="${type || 'text'}" name="${name}" value="${esc(value)}" style="width:100%; box-sizing:border-box; border:1px solid #ccc; border-radius:8px; padding:8px 10px; font-size:0.95rem;">
      </div>`;
    }
    function cedulaRow(label) {
      return `<div style="margin-bottom:0.8rem;">
          <label style="display:block; font-size:0.78rem; font-weight:700; color:#888; margin-bottom:4px;">${esc(label)}</label>
          <input type="text" id="editModalCedulaField" value="${esc(user.id)}" ${isAdmin ? '' : 'disabled'} style="width:100%; box-sizing:border-box; border:1px solid ${isAdmin ? '#ccc' : '#ddd'}; border-radius:8px; padding:8px 10px; font-size:0.95rem; ${isAdmin ? '' : 'background:#f5f5f5; color:#888;'}">
          ${isAdmin ? '<p style="font-size:0.72rem; color:#aaa; margin:4px 0 0;">Corrige un error de digitación (ej. se acreditó por nombre porque la cédula quedó mal). Afecta a esta persona en TODOS los eventos de este cliente, no solo este.</p>' : ''}
        </div>`;
    }
    function configuredValueOf(key, cfg) {
      // La firma es por EVENTO (archivo aparte): el valor guardado en extra_fields no dice si
      // ESTE evento la tiene — la existencia se comprueba al dibujar el lienzo (initSignatures).
      if (cfg && cfg.field_type === 'signature') return '';
      return Object.prototype.hasOwnProperty.call(user, key) ? user[key] : extras[key];
    }
    function configuredFieldRow(cfg, valueOverride) {
      const control = window.FieldRender.renderControl(cfg, valueOverride !== undefined ? valueOverride : configuredValueOf(cfg.key, cfg));
      return `<div style="margin-bottom:0.8rem;">
        <label style="display:block; font-size:0.78rem; font-weight:700; color:#888; margin-bottom:4px;">${esc(cfg.label)}${cfg.required ? ' *' : ''}</label>
        ${control}
      </div>`;
    }

    // Todos los campos en el orden definido en Parámetros del Evento (ítems 3a/4): la identidad
    // (nombres/apellidos/cédula) entra en la misma lista, con la etiqueta propia del evento.
    const configuredHtml = fieldConfigs.map((cfg) => {
      if (cfg.key === 'id') return cedulaRow(cfg.label);
      if (cfg.field_type === 'categories') return configuredFieldRow(cfg, user.categories);
      if (cfg.field_type === 'certificate') return configuredFieldRow(cfg, user.certificate ? 'true' : '');
      if (cfg.field_type === 'digital_contact') return configuredFieldRow({ ...cfg, __sentAt: user.digital_sent_at }, user.digital_contact || '');
      if (cfg.locked) return fieldRow(cfg.label, cfg.key, user[cfg.key]);
      return configuredFieldRow(cfg);
    }).join('');
    const isRegistered = user.status !== 'No registrado';
    const originalStatus = isRegistered ? 'registrado' : 'no_registrado';
    // 2026-09-23, pedido explícito: al darle Editar a alguien que aún no llegó, "Registrado" queda
    // preseleccionado — guardar sin tocar nada ya lo deja acreditado (en verde).
    const defaultStatus = 'registrado';

    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed; inset:0; background:rgba(10,14,46,0.45); z-index:9997; display:flex; align-items:center; justify-content:center; overflow:auto; padding:2rem 1rem;';
    const box = document.createElement('div');
    box.style.cssText = 'background:white; border-radius:16px; padding:1.8rem; max-width:520px; width:100%; box-shadow:0 20px 60px rgba(0,0,0,0.3); font-family: var(--font-body, sans-serif); max-height:90vh; overflow:auto;';
    box.innerHTML = `
      <h4 style="margin-top:0; color:var(--golden-dark);">Editar persona</h4>
      <form id="editModalForm">
        ${configuredHtml}
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:1rem;">
          <button type="button" id="editModalCancel" style="border:1px solid #ccc; background:white; border-radius:20px; padding:8px 18px; cursor:pointer; font-weight:600;">Cancelar</button>
          <button type="button" id="editModalSave" style="border:none; background:var(--golden-primary,#D4AF37); color:#1a1200; border-radius:20px; padding:8px 18px; cursor:pointer; font-weight:700;">Guardar cambios</button>
        </div>
      </form>
      ${canManageStatus ? `
      <hr style="margin:1.2rem 0; border:none; border-top:1px solid #eee;">
      <div style="margin-bottom:0.8rem;">
        <label style="display:block; font-size:0.78rem; font-weight:700; color:#888; margin-bottom:4px;">Estado de registro</label>
        <select id="editModalStatus" style="width:100%; border:1px solid #ccc; border-radius:8px; padding:8px 10px; font-size:0.95rem;">
          <option value="no_registrado" ${defaultStatus === 'no_registrado' ? 'selected' : ''}>No registrado</option>
          <option value="registrado" ${defaultStatus === 'registrado' ? 'selected' : ''}>Registrado</option>
        </select>
        <p style="font-size:0.72rem; color:#aaa; margin:4px 0 0;">Se aplica junto con el resto de cambios al pulsar "Guardar cambios" — ya no hace falta un botón aparte.</p>
      </div>
      <button type="button" id="editModalDelete" class="btn-table-delete" style="width:100%; padding:10px; font-size:0.85rem;">🗑️ Eliminar de este evento</button>
      ` : ''}
    `;
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    window.FieldRender.watchEmail(box, () => user.id);
    window.FieldRender.watchEmailDeliverable(box);
    window.FieldRender.initSignatures(box, {
      existingUrl: (key) => `/api/events/${window.EVENT_ID}/users/${encodeURIComponent(user.id)}/signature/${key}`,
    });

    function close() { overlay.remove(); }
    // 2026-09-16 (Sprint 2.4 Fase 3, pedido explícito): ya NO se cierra al hacer clic afuera —
    // solo con "Cancelar" o guardando, para no perder cambios sin querer.
    box.querySelector('#editModalCancel').addEventListener('click', close);

    box.querySelector('#editModalSave').addEventListener('click', async () => {
      const GCs = window.GoldenContingency && window.GoldenContingency.instance;
      if (GCs && GCs.active()) { showToast(OFFLINE_EDIT_NOTICE, 'error'); return; }          // se cortó la red con el modal abierto: aviso claro, no «Error de red»
      const form = box.querySelector('#editModalForm');
      if (!form.reportValidity()) return;

      const saveBtn = box.querySelector('#editModalSave');
      const val = (name) => {
        const el = form.querySelector(`[name="${name}"]`);
        if (!el) return '';
        if (el.type === 'checkbox') return el.checked ? 'true' : '';
        return el.value.trim();
      };

      // Cédula editable en el mismo "Guardar cambios" (2026-09-16, pedido explícito) — admin
      // solamente (ver input #editModalCedulaField, disabled para el resto de roles). Si cambió,
      // se corrige PRIMERO (PUT .../cedula, con su propia confirmación porque afecta a la
      // persona en TODOS los eventos de este cliente) y recién después se guarda el resto de
      // campos con el id ya actualizado.
      let currentId = user.id;
      const cedulaInput = box.querySelector('#editModalCedulaField');
      const newId = cedulaInput ? cedulaInput.value.trim() : user.id;

      if (isAdmin && newId && newId !== user.id) {
        const ok = await showConfirm(`¿Cambiar la cédula de "${user.id}" a "${newId}"?<br><br>Esto afecta a esta persona en TODOS los eventos de este cliente, no solo en este.`, { variant: 'warning', confirmLabel: 'Sí, corregir y guardar' });
        if (!ok) return;
        saveBtn.disabled = true; saveBtn.innerText = 'Guardando...';
        try {
          const cedulaRes = await fetch(withEvent(`/api/users/${user.id}/cedula`), {
            method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ new_id: newId }),
          });
          if (!cedulaRes.ok) {
            const data = await cedulaRes.json().catch(() => ({}));
            showToast(data.detail || 'No se pudo cambiar la cédula', 'error');
            saveBtn.disabled = false; saveBtn.innerText = 'Guardar cambios';
            return;
          }
          currentId = newId;
        } catch (e) {
          showToast('Error de red', 'error');
          saveBtn.disabled = false; saveBtn.innerText = 'Guardar cambios';
          return;
        }
      }

      // Cambio de estado de registro (2026-09-17, pedido explícito: "que con el mismo botón de
      // guardar de todo el formulario también tome ese guardar" — antes tenía su propio botón
      // "Aplicar" aparte, ahora se aplica junto con el resto de campos en un solo Guardar). Solo
      // se llama al endpoint si el valor del select realmente cambió — evitar un PATCH de estado
      // sin sentido en cada guardado normal del perfil.
      if (canManageStatus) {
        const statusSelect = box.querySelector('#editModalStatus');
        const newStatus = statusSelect ? statusSelect.value : originalStatus;
        if (newStatus !== originalStatus) {
          const label = newStatus === 'registrado' ? 'Registrado' : 'No registrado';
          // Pasar a "Registrado" (el valor por defecto de este modal) no pide confirmación: es
          // justo el flujo de "buscar, Editar, Guardar". Volver a "No registrado" sí la pide.
          const ok = newStatus === 'registrado' || await showConfirm(`¿Cambiar el estado de registro de esta persona a "${label}"? Se guardará junto con el resto de cambios.`, { variant: 'warning', confirmLabel: 'Sí, cambiar y guardar' });
          if (!ok) return;
          saveBtn.disabled = true; saveBtn.innerText = 'Guardando...';
          try {
            const statusRes = await fetch(`/api/events/${window.EVENT_ID}/users/${currentId}/status`, {
              method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: newStatus, method: opts.method }),
            });
            if (!statusRes.ok) {
              const data = await statusRes.json().catch(() => ({}));
              showToast(data.detail || 'No se pudo cambiar el estado', 'error');
              saveBtn.disabled = false; saveBtn.innerText = 'Guardar cambios';
              return;
            }
            // Autoimpresión (2026-09-17, pedido explícito): "apenas cambia el estado a
            // registrado, si está autoimpresión activo entonces debe mandar a imprimir" — este es
            // uno de los puntos donde el estado puede pasar a "Registrado" sin pasar por un
            // escaneo (ver maybeAutoPrint en badge-render.js para el resto).
            if (newStatus === 'registrado' && window.BadgePrint) BadgePrint.maybeAutoPrint(currentId);
          } catch (e) {
            showToast('Error de red', 'error');
            saveBtn.disabled = false; saveBtn.innerText = 'Guardar cambios';
            return;
          }
        }
      }

      const payload = { first_name: val('first_name'), last_name: val('last_name') };
      const newExtras = {};
      fieldConfigs.filter((cfg) => !cfg.locked).forEach((cfg) => {
        if (Object.prototype.hasOwnProperty.call(user, cfg.key)) payload[cfg.key] = val(cfg.key);
        else newExtras[cfg.key] = val(cfg.key);
      });
      payload.extra_fields = newExtras;
      if (fieldConfigs.some((cfg) => cfg.field_type === 'digital_contact')) {
        payload.digital_contact = val('digital_contact');
        payload.send_digital_now = !!form.querySelector('input[name="send_digital_now"]:checked');  // casilla «Enviar ahora»
      }
      if (fieldConfigs.some((cfg) => cfg.field_type === 'certificate')) {
        payload.certificate = !!form.querySelector('input[name="certificate"]:checked');
      }
      if (fieldConfigs.some((cfg) => cfg.field_type === 'categories')) {
        payload.categories = Array.from(form.querySelectorAll('input[name="categories"]:checked')).map((i) => i.value);
      }

      saveBtn.disabled = true; saveBtn.innerText = 'Guardando...';
      try {
        const res = await fetch(withEvent(`/api/users/${currentId}`), {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
        });
        if (res.ok) {
          try {
            const info = await res.clone().json();
            if (info.digital) showToast(`📲 Escarapela digital: ${info.digital.detail}`, 'success');
          } catch (e) { /* sin detalle de envío */ }
          try { await window.FieldRender.saveSignatures(box, currentId); }
          catch (e) { showToast(e.message, 'error'); }
          // Digitador (sin selector de estado): guardar la edición de alguien que aún no llegó lo deja
          // "Registrado", igual que el valor por defecto que ven coordinador+.
          if (!canManageStatus && !isRegistered) {
            try {
              const st = await fetch(`/api/events/${window.EVENT_ID}/users/${currentId}/status`, {
                method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'registrado', method: opts.method }),
              });
              if (st.ok) { if (window.BadgePrint) BadgePrint.maybeAutoPrint(currentId); }
              else showToast('Se guardaron los cambios, pero no se pudo marcar como Registrado', 'error');
            } catch (e) { showToast('Se guardaron los cambios, pero no se pudo marcar como Registrado', 'error'); }
          }
          showToast('Cambios guardados', 'success');
          close();
          if (window.directorySearch) window.directorySearch.reload();
          if (opts.onSaved) opts.onSaved(currentId);
        } else {
          const data = await res.json().catch(() => ({}));
          showToast(data.detail || 'Error al guardar cambios', 'error');
          saveBtn.disabled = false; saveBtn.innerText = 'Guardar cambios';
        }
      } catch (e) {
        showToast('Error de red', 'error');
        saveBtn.disabled = false; saveBtn.innerText = 'Guardar cambios';
      }
    });

    if (canManageStatus) {
      box.querySelector('#editModalDelete').addEventListener('click', async () => {
        const GCd = window.GoldenContingency && window.GoldenContingency.instance;
        if (GCd && GCd.active()) { showToast(OFFLINE_EDIT_NOTICE, 'error'); return; }
        const fullName = `${user.first_name || ''} ${user.last_name || ''}`.trim();
        const ok = await showConfirm(`⚠️ Esto elimina COMPLETAMENTE a ${fullName || 'esta persona'} de la base de este evento (y de la base general si no pertenece a ningún otro evento de este cliente). No se puede deshacer. ¿Continuar?`, { confirmLabel: 'Eliminar' });
        if (!ok) return;
        try {
          const res = await fetch(withEvent(`/api/users/${user.id}`), { method: 'DELETE' });
          if (res.ok) {
            showToast('Persona eliminada', 'success');
            close();
            if (window.directorySearch) window.directorySearch.reload();
          } else {
            const data = await res.json().catch(() => ({}));
            showToast(data.detail || 'No se pudo eliminar', 'error');
          }
        } catch (e) { showToast('Error de red', 'error'); }
      });
    }
  }

  function buildRow(user) {
    const tr = document.createElement('tr');
    tr.className = user.status === 'Registrado' ? 'row-registrado' : user.status === 'Nuevo' ? 'row-nuevo' : 'row-noregistrado';
    tr.dataset.userId = user.id;
    if (user.__h) tr.dataset.h = user.__h;          // fila de la lista local (sin cédula)

    /* La columna de Acción va PRIMERO (2026-09-16, pedido explícito: antes al final, obligaba a
       desplazarse hasta el final de la fila para editar/imprimir). El resto de columnas
       (ID/Nombres/Apellidos/Tipo Asistente/Estado) siguen en el mismo orden de siempre. */
    const actionTd = document.createElement('td');
    actionTd.className = 'action-cell';

    /* Botón de impresión persistente por fila (Historia 2.2) — vive siempre en la fila para
       poder reimprimir a cualquiera en cualquier momento, no solo recién registrado. cliente es
       de solo lectura; 'comercial' excluido explícitamente (Sprint 2.4 Fase 6, pedido explícito:
       "la comercial no debe poder imprimir en directorio en vivo") — el backend ya lo bloquea
       (require_role_excluding en badges.py), esto evita mostrarle un botón que le va a fallar. */
    const PRINT_HIDDEN_ROLES = ['cliente', 'comercial'];
    if (!PRINT_HIDDEN_ROLES.includes(window.STAFF_ROLE) && !user.__local) {          // la lista local no tiene la cédula (y sin red no se imprime)
      const printBtn = document.createElement('button');
      printBtn.type = 'button';
      printBtn.innerText = '🖨️';
      printBtn.title = 'Imprimir escarapela';
      printBtn.className = 'golden-btn btn-table-action';
      printBtn.addEventListener('click', () => {
        if (window.BadgePrint) BadgePrint.openPrintWindow(user.id);
      });
      actionTd.appendChild(printBtn);
    }

    /* Botones que quedan en la fila (2026-09-16): imprimir + editar, y ya — "Acreditar" como
       botón suelto desaparece (acreditar ahora pasa por el flujo de escaneo/búsqueda con
       confirmación, o por "Cambiar estado de registro" dentro de Editar para admin+). */
    if (canEdit) {
      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.innerText = 'Editar';
      editBtn.className = 'golden-btn btn-table-action';
      editBtn.addEventListener('click', () => buildEditModal(user));
      actionTd.appendChild(editBtn);
    }

    tr.appendChild(actionTd);

    FIELDS_ORDER.forEach(field => {
      const td = document.createElement('td');
      td.innerText = user[field] || '';
      tr.appendChild(td);
    });

    const statusTd = document.createElement('td');
    statusTd.innerText = user.status;
    statusTd.style.fontWeight = 'bold';
    tr.appendChild(statusTd);

    return tr;
  }

  function renderRows(tbodyId, users) {
    const tbody = document.getElementById(tbodyId);
    tbody.innerHTML = '';
    if (users.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#888;">Sin resultados.</td></tr>';
      return;
    }
    users.forEach(user => tbody.appendChild(buildRow(user)));
  }

  async function loadRows(tbodyId) {
    const tbody = document.getElementById(tbodyId);
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">Cargando base de datos...</td></tr>';
    try {
      const res = await fetch(withEvent('/api/users'));
      const users = await res.json();
      renderRows(tbodyId, users);
      return users;
    } catch (err) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:red;">Error conectando al servidor</td></tr>';
      return [];
    }
  }

  /* Unifica en un solo componente lo que antes vivía duplicado inline en kiosk_cedula.html:
     los 3 campos de búsqueda independientes (cédula/nombre/entidad) que filtran en vivo sobre
     los datos ya cargados, más el atajo de lector de código de barras (Enter con cédula exacta
     = acreditar al instante, con el mismo flujo DUPLICADO/force de siempre). Reusado ahora por
     la vista de Registro unificada (2026-09-21) esté o no el modo cámara activo — la búsqueda
     no depende de si el evento tiene reconocimiento facial o no.
     opts: { tbodyId, searchIds: {cedula, nombre, entidad}, fastCheckin }
     Devuelve { reload() } para que la página pueda refrescar manualmente (ej. al volver a la
     pestaña, o tras registrar a alguien nuevo desde otra pestaña). */
  function mountSearch(opts) {
    let allUsers = [];
    let onlyNotRegistered = false;
    const ids = opts.searchIds || {};
    const cedulaInput = ids.cedula ? document.getElementById(ids.cedula) : null;
    const nombreInput = ids.nombre ? document.getElementById(ids.nombre) : null;
    const entidadInput = ids.entidad ? document.getElementById(ids.entidad) : null;

    /* Botón/contador "N sin registrar" (Sprint 2 Fix 2, 2026-09-15) — se crea solo, insertado
       justo antes de la tabla, así no hay que tocar cada template que use mountSearch. Clic
       alterna un filtro adicional (combinado con los campos de búsqueda de arriba, no los
       reemplaza) que deja solo las filas en estado "No registrado". Junto a él, un segundo
       indicador de solo lectura "X registrados de Y" (2026-09-16, pedido explícito) — Y es el
       total de personas del evento (roster + altas manuales), no solo las visibles tras filtrar. */
    const tbodyEl = document.getElementById(opts.tbodyId);
    const tableEl = tbodyEl ? tbodyEl.closest('table') : null;
    let counterBtn = null;
    let totalCounterEl = null;
    if (tableEl && tableEl.parentNode) {
      counterBtn = document.createElement('button');
      counterBtn.type = 'button';
      counterBtn.className = 'not-registered-counter';
      counterBtn.style.cssText = 'display:inline-block; margin-bottom:1rem; margin-right:0.6rem; border:1px solid #dc3545; background:#fbe9ea; color:#a12631; border-radius:20px; padding:6px 16px; font-weight:700; font-size:0.85rem; cursor:pointer;';
      counterBtn.addEventListener('click', () => {
        onlyNotRegistered = !onlyNotRegistered;
        counterBtn.style.background = onlyNotRegistered ? '#dc3545' : '#fbe9ea';
        counterBtn.style.color = onlyNotRegistered ? 'white' : '#a12631';
        applyFilters();
      });
      tableEl.parentNode.insertBefore(counterBtn, tableEl);

      totalCounterEl = document.createElement('span');
      totalCounterEl.className = 'total-registered-counter';
      totalCounterEl.style.cssText = 'display:inline-block; margin-bottom:1rem; border:1px solid #28a745; background:#eaf6ec; color:#1c7a34; border-radius:20px; padding:6px 16px; font-weight:700; font-size:0.85rem;';
      tableEl.parentNode.insertBefore(totalCounterEl, tableEl);
    }

    function updateCounterLabel() {
      if (!counterBtn) return;
      const total = allUsers.length;
      const count = allUsers.filter(u => u.status === 'No registrado').length;
      const registered = total - count;
      counterBtn.innerText = `⚠️ ${count} sin registrar` + (onlyNotRegistered ? ' (filtrando)' : '');
      counterBtn.style.display = count === 0 && !onlyNotRegistered ? 'none' : 'inline-block';
      if (totalCounterEl) totalCounterEl.innerText = `✅ ${registered} registrados de ${total}`;
    }

    /* Buscador rápido (antes, cada tecla re-normalizaba a TODAS las personas y redibujaba TODAS las filas: 180-230 ms por tecla con
       3.000 personas, con el campo de texto congelado mientras tanto):
       - lo que se compara (cédula en minúsculas, palabras del nombre y de la entidad sin tildes) se calcula UNA vez por persona;
       - las filas ya construidas se reutilizan (una por persona; si el servidor manda una versión nueva, es otro objeto y se reconstruye);
       - se dibujan como máximo RENDER_LIMIT filas, con «Mostrar más» para el resto;
       - al escribir se espera SEARCH_DELAY_MS después de la última tecla antes de filtrar (la letra aparece al instante). */
    const RENDER_LIMIT = 200;
    const SEARCH_DELAY_MS = 250;
    const searchKeys = new WeakMap();
    const rowCache = new WeakMap();
    let shownLimit = RENDER_LIMIT;
    let lastFiltered = [];
    let searchTimer = null;

    function keysOf(u) {
      let k = searchKeys.get(u);
      if (!k) {
        k = { id: String(u.id || '').toLowerCase(), name: wordsOf(`${u.first_name || ''} ${u.last_name || ''}`), entity: wordsOf(u.entity || '') };
        searchKeys.set(u, k);
      }
      return k;
    }

    function rowOf(u) {
      let tr = rowCache.get(u);
      if (!tr) { tr = buildRow(u); rowCache.set(u, tr); }
      return tr;
    }

    function drawRows() {
      const tbody = document.getElementById(opts.tbodyId);
      // El «✅ Acreditar» puntual (FOUND_PENDING) vive en una fila reutilizada: como antes, se va al volver a dibujar.
      tbody.querySelectorAll('.btn-accredit-pending').forEach(b => b.remove());
      if (!lastFiltered.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#888;">Sin resultados.</td></tr>';
        if (localMode) tbody.insertBefore(localNoteRow(), tbody.children[0] || null);
        return;
      }
      const rows = lastFiltered.slice(0, shownLimit).map(rowOf);
      if (localMode) rows.unshift(localNoteRow());
      if (lastFiltered.length > shownLimit) {
        const more = document.createElement('tr');
        more.className = 'directory-more';
        const td = document.createElement('td');
        td.colSpan = 6;
        td.style.cssText = 'text-align:center; padding:0.8rem; color:#555;';
        td.innerText = `Mostrando ${shownLimit} de ${lastFiltered.length}. Escribe en el buscador para afinar, o `;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'golden-btn btn-table-action';
        btn.innerText = `Mostrar ${Math.min(RENDER_LIMIT, lastFiltered.length - shownLimit)} más`;
        btn.addEventListener('click', () => { shownLimit += RENDER_LIMIT; drawRows(); });
        td.appendChild(btn);
        more.appendChild(td);
        rows.push(more);
      }
      tbody.replaceChildren(...rows);
    }

    function applyFilters() {
      clearTimeout(searchTimer);
      const cedula = (cedulaInput && cedulaInput.value || '').trim().toLowerCase();
      const nombre = wordsOf((nombreInput && nombreInput.value || '').trim());
      const entidad = wordsOf((entidadInput && entidadInput.value || '').trim());
      let wantH = '';
      if (localMode && cedula) {                          // lista local: la cédula se compara por huella (exacta); se calcula una vez y se vuelve a filtrar
        wantH = localHashes.get(cedula);
        if (wantH === undefined) { wantH = ''; const GC = GCref(); if (GC) GC.hashFor(cedula).then((h) => { localHashes.set(cedula, h); applyFilters(); }); }
      }
      lastFiltered = allUsers.filter(u => {
        if (onlyNotRegistered && u.status !== 'No registrado') return false;
        if (!cedula && !nombre.length && !entidad.length) return true;
        const k = keysOf(u);
        if (cedula && !(u.__local ? (wantH && u.__h === wantH) : k.id.includes(cedula))) return false;
        if (nombre.length && !matchesWords(k.name, nombre)) return false;
        if (entidad.length && !matchesWords(k.entity, entidad)) return false;
        return true;
      });
      updateCounterLabel();
      drawRows();
    }

    function onSearchInput() {
      clearTimeout(searchTimer);
      shownLimit = RENDER_LIMIT;
      searchTimer = setTimeout(applyFilters, SEARCH_DELAY_MS);
    }

    /* Carga por páginas + incremental (Fase 1-2). La lista completa llega en páginas de PAGE (la primera se ve enseguida) y después cada
       POLL_MS se piden solo los cambios (/api/users/changes). Lo que el incremental no ve (bajas, estados revertidos) se detecta porque
       el total no cuadra, y ahí se recarga todo. reload() —lo llaman las acciones locales— siempre recarga completo. */
    const PAGE = 1000;
    const POLL_MS = 15000;
    const NOW_CURSOR = '9007199254740991:9007199254740991';   // cursor «en el futuro»: no trae filas, solo el cursor y el total de ahora
    let cursor = null;
    let loading = null;

    /* LISTA LOCAL (modo contingencia): sin red —o ya en contingencia— la tabla sale de la copia local del roster (static/js/contingency.js): nombre, categorías y estado (contando también lo
       encolado sin red) y los contadores de siempre. La copia NO trae cédula ni entidad: se busca por nombre y por cédula EXACTA (huella); el filtro de entidad se desactiva con un aviso. */
    let localMode = false;
    const localHashes = new Map();                       // cédula escrita -> huella (se calcula una vez)
    const GCref = () => window.GoldenContingency && window.GoldenContingency.instance;
    const entidadPlaceholder = entidadInput ? entidadInput.placeholder : '';
    function setLocalMode(on) {
      localMode = on;
      if (entidadInput) { entidadInput.disabled = on; entidadInput.placeholder = on ? 'No disponible sin conexión' : entidadPlaceholder; if (on) entidadInput.value = ''; }
    }
    async function loadFromLocalCopy() {
      const GC = GCref();
      if (!GC) return false;
      await GC.ready;
      if (!GC.supported || !(await GC.rosterUsable())) return false;
      const people = await GC.localPeople();
      setLocalMode(true);
      allUsers = people.map((p) => ({ id: '', first_name: p.n, last_name: '', entity: '', opt_1: (p.c || []).join(', '), status: p.s, categories: p.c || [], __h: p.h, __local: true }));
      applyFilters();
      return true;
    }
    function localNoteRow() {
      const tr = document.createElement('tr'); tr.className = 'directory-local-note';
      const td = document.createElement('td'); td.colSpan = 6;
      td.style.cssText = 'text-align:center; padding:0.6rem; background:#fff8e1; color:#7a5b00; font-weight:600;';
      td.innerText = 'Sin conexión: se muestra la LISTA LOCAL (nombre, categorías y estado). La cédula, la entidad y demás datos no están en esta copia: busca por nombre o escribe la cédula exacta.';
      tr.appendChild(td);
      return tr;
    }

    async function fullLoad() {
      const tbody = document.getElementById(opts.tbodyId);
      const GC0 = GCref();
      if (GC0) { await GC0.ready; if (GC0.active() && await loadFromLocalCopy()) return; }          // ya en contingencia: ni se intenta la red
      if (localMode) { setLocalMode(false); allUsers = []; }
      if (!allUsers.length) tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">Cargando base de datos...</td></tr>';
      try {
        // El cursor se toma ANTES de leer las páginas: lo que cambie mientras tanto llega en el siguiente incremental.
        const head = await fetch(withEvent('/api/users/changes?cursor=' + NOW_CURSOR));
        if (!head.ok) throw new Error(head.status);
        const nextCursor = (await head.json()).cursor;
        const byId = new Map();
        for (let offset = 0, total = 1; offset < total; offset += PAGE) {
          const res = await fetch(withEvent(`/api/users?limit=${PAGE}&offset=${offset}`));
          if (!res.ok) throw new Error(res.status);
          total = parseInt(res.headers.get('X-Total-Count') || '0', 10);
          const page = await res.json();
          page.forEach(u => byId.set(u.id, u));
          if (!page.length) break;
          if (offset + PAGE < total) { allUsers = [...byId.values()]; applyFilters(); }   // se ve lo que ya llegó mientras bajan las demás
        }
        allUsers = [...byId.values()];
        cursor = nextCursor;
      } catch (err) {
        if (await loadFromLocalCopy()) return;           // sin red: la lista local en vez de «Error conectando al servidor»
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:red;">Error conectando al servidor</td></tr>';
        return;
      }
      applyFilters();
    }

    async function refresh() {
      if (!cursor || loading || localMode) return;
      try {
        const res = await fetch(withEvent('/api/users/changes?cursor=' + encodeURIComponent(cursor)));
        if (!res.ok) return;
        const delta = await res.json();
        cursor = delta.cursor;
        if (delta.users.length) {
          const byId = new Map(allUsers.map(u => [u.id, u]));
          delta.users.forEach(u => byId.set(u.id, u));
          allUsers = [...byId.values()];
        }
        if (allUsers.length !== delta.total) return reload();
        if (delta.users.length) applyFilters();
      } catch (err) { /* sin red: se reintenta en el siguiente ciclo */ }
    }

    function reload() {
      if (!loading) loading = fullLoad().finally(() => { loading = null; });
      return loading;
    }

    {
      const GC = GCref();
      if (GC && GC.onSynced) GC.onSynced(() => { if (!localMode) reload(); });          // la cola ya está en el servidor: la lista y los contadores al día
      if (GC && GC.onChange) GC.onChange((st) => { if (st === 'normal' && localMode) reload(); else if (st === 'contingency' && !allUsers.length) reload(); });      // vuelve la red: la lista del servidor
    }

    setInterval(() => {
      if (document.visibilityState === 'visible' && tbodyEl && tbodyEl.offsetParent !== null) refresh();
    }, POLL_MS);
    // Con la pestaña oculta no se consulta (no gasta la base); al volver a ella se ponen al día los cambios de inmediato.
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') refresh(); });

    [cedulaInput, nombreInput, entidadInput].forEach(input => {
      if (input) input.addEventListener('input', onSearchInput);
    });

    /* nameInfo (Sprint 2 Parte 2, 2.1): {nombres, apellidos} cuando el escaneo trajo un nombre
       completo además de la cédula (CSV de la cédula vieja, o el OCR de la MRZ de la nueva) —
       null si solo se tiene un ID suelto (búsqueda de siempre). Búsqueda en dos pasos: primero
       coincidencia exacta por cédula; si no hay match Y sí hay nombre, se intenta un segundo
       paso buscando ese nombre completo entre los ya cargados en el Directorio, reutilizando el
       mismo criterio de prefijo por palabra + insensible a tildes de arriba — recién si ninguno
       de los dos encuentra nada se cae al comportamiento de "no encontrado" de siempre. */
    /* Cada intento de acreditar lleva un `client_id` propio (Fase 0 de escalabilidad): si la red falla y se reintenta —o el navegador reenvía— el
       servidor devuelve el mismo resultado en vez de registrar dos veces. Los reintentos automáticos (red caída, 502/503/504) reusan el MISMO id. */
    const newClientId = () => (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : `c${Date.now()}${Math.random().toString(16).slice(2)}`;
    /* Misma regla que la estación emulada por el generador de carga (tests/load/locustfile.py::CedulaScanner): cada intento espera 10 s como máximo y, ante 502/503/504, un
       error de red o el tiempo agotado, se reintenta SOLO (hasta 2 reintentos, con espera creciente corta) y con el MISMO `client_id` (el servidor no duplica el ingreso, ver
       /api/checkin-cedula: `replayed`). Mientras reintenta se muestra un aviso discreto y el operador no tiene que hacer nada. */
    const CHECKIN_TIMEOUT_MS = 10000;
    let retryNote = null;
    function showRetryNote(on) {
      if (!on) { if (retryNote) { retryNote.remove(); retryNote = null; } return; }
      if (retryNote) return;
      retryNote = document.createElement('div');
      retryNote.setAttribute('role', 'status'); retryNote.setAttribute('aria-live', 'polite');
      retryNote.style.cssText = 'position:fixed; bottom:12px; right:12px; z-index:9998; background:#fff8e1; color:#7a5b00; border-left:4px solid #f0ad4e; padding:6px 12px; border-radius:8px; font-size:.8rem; opacity:.95;';
      retryNote.textContent = 'Conexión lenta: reintentando, no hace falta volver a escanear…';
      document.body.appendChild(retryNote);
    }
    async function postWithRetry(url, formData, attempts = 3) {
      try {
        for (let i = 1; ; i++) {
          const ctl = typeof AbortController === 'function' ? new AbortController() : null;
          const timer = ctl ? setTimeout(() => ctl.abort(), CHECKIN_TIMEOUT_MS) : null;
          try {
            const res = await fetch(url, { method: 'POST', body: formData, signal: ctl ? ctl.signal : undefined });
            if (![502, 503, 504].includes(res.status) || i >= attempts) return res;
          } catch (e) {
            if (i >= attempts) throw e;
          } finally {
            if (timer) clearTimeout(timer);
          }
          showRetryNote(true);
          await new Promise(r => setTimeout(r, 400 * i));
        }
      } finally {
        showRetryNote(false);
      }
    }

    /* Modo contingencia (static/js/contingency.js, Fase 3): sin red NO se espera al servidor. Igual que en línea, escanear/escribir una cédula exacta SOLO acredita de inmediato si el «Modo
       autoregistro» está encendido (el valor viaja con la copia local y se guarda en IndexedDB: vale tras recargar sin red); con el modo apagado SOLO busca y resalta a la persona, con un
       botón «Acreditar» en su fila (como FOUND_PENDING). */
    accreditHooks.push((found) => {
      const u = allUsers.find((x) => (found.cedula && x.id === found.cedula) || (x.__h && x.__h === found.person.h));
      if (u) { u.status = 'Registrado'; rowCache.delete(u); }
      if (cedulaInput && found.cedula) { cedulaInput.value = found.cedula; localHashes.set(found.cedula.toLowerCase(), found.person.h); }
      applyFilters();
    });
    async function offlineCheckin(GC, cedula, method, cid) {
      if (await GC.autoRegister()) { await offlineAccredit(GC, { cedula }, method, cid); return; }
      const found = await GC.scanLocal(cedula);
      if (found.status === 'expired') { showToast('No hay copia local vigente: verificar manualmente', 'error'); return; }
      if (found.status === 'not_found') { showToast('No registrado: verificar manualmente', 'error'); return; }
      if (cedulaInput) { cedulaInput.value = found.cedula; localHashes.set(found.cedula.toLowerCase(), found.person.h); applyFilters(); }          // la huella ya se conoce: el filtro de la lista local es inmediato
      const tbody = document.getElementById(opts.tbodyId);
      const row = tbody && (tbody.querySelector(`tr[data-user-id="${CSS.escape(found.cedula)}"]`) || tbody.querySelector(`tr[data-h="${found.person.h}"]`));
      const actionTd = row ? row.querySelector('.action-cell') : null;
      if (actionTd && !actionTd.querySelector('.btn-accredit-pending')) {
        const btn = document.createElement('button');
        btn.type = 'button'; btn.innerText = '✅ Acreditar'; btn.className = 'golden-btn btn-table-action btn-accredit-pending';
        btn.addEventListener('click', async () => { btn.disabled = true; btn.innerText = 'Acreditando...'; await offlineAccredit(GC, { cedula: found.cedula }, method, newClientId()); });
        actionTd.appendChild(btn);
      }
      showToast(`${found.person.n} encontrado(a) — el modo autoregistro está apagado: confirma con "Acreditar" en la fila`, 'success');
    }

    async function fastCheckin(cedula, force, nameInfo, confirmFlag, method, clientId) {
      const cid = clientId || newClientId();
      const GC = window.GoldenContingency && window.GoldenContingency.instance;
      if (GC && GC.active()) return offlineCheckin(GC, cedula, method, cid);
      const formData = new FormData();
      formData.append('event_id', window.EVENT_ID);
      formData.append('client_id', cid);
      formData.append('cedula', cedula);
      if (force) formData.append('force', 'true');
      if (confirmFlag) formData.append('confirm', 'true');
      if (method) formData.append('method', method);  // 'qr' cuando la cédula vino de un código QR
      if (nameInfo) {
        if (nameInfo.nombres) formData.append('first_name', nameInfo.nombres);
        if (nameInfo.apellidos) formData.append('last_name', nameInfo.apellidos);
      }
      try {
        let res = null;
        try { res = await postWithRetry('/api/checkin-cedula', formData); } catch (e) { if (!GC) throw e; }
        if (GC) {
          if (!res || [502, 503, 504].includes(res.status)) {          // agotó sus reintentos: 2 seguidos activan la contingencia y ESTE escaneo ya se atiende sin red
            GC.noteScanExhausted();
            if (GC.active()) return offlineCheckin(GC, cedula, method, cid);
            if (!res) { showToast('Error de red', 'error'); return; }
          } else if (res.status < 500 && res.status !== 401 && res.status !== 403) GC.noteAuthGood();
        }
        const data = await res.json();
        if (!res.ok) { showToast(data.detail || 'No se pudo acreditar', 'error'); return; }
        if (data.result === 'DUPLICADO') {
          const confirmado = await confirmDuplicateRegistration(data.data, data.times_registered);
          if (confirmado) await fastCheckin(cedula, true, nameInfo, undefined, method, cid);
          return;
        }
        if (data.result === 'SÍ') {
          // Match exacto por cédula: acredita de una vez, sin modal aparte (2026-09-16, pedido
          // explícito) — la "confirmación" es ver la fila aparecer filtrada en el Directorio,
          // como si se hubiera buscado por cédula a mano.
          showToast(`Acreditado: ${data.data.first_name} ${data.data.last_name}`, 'success');
          if (data.data.sibling_events && data.data.sibling_events.length) {
            showToast(`ℹ️ Ya asistió a ${data.data.sibling_events.join(', ')} (mismo superevento) — sus datos se vincularon, no hizo falta capturarlos de nuevo`, 'success');
          }
          if (window.BadgePrint) BadgePrint.maybeAutoPrint(data.data.id);
          await reload();
          if (cedulaInput) { cedulaInput.value = data.data.id; applyFilters(); }
          return;
        }
        if (data.result === 'FOUND_PENDING') {
          // Match exacto, pero "Modo autoregistro" está apagado (2026-09-16, Fase 3, corrección
          // real: antes esto acreditaba igual, quedaba "verde" sin querer) — se deja la fila
          // filtrada y VISIBLE pero SIN acreditar (blanco/"No registrado"); un botón puntual en
          // esa misma fila confirma con un clic, sin modal aparte.
          await reload();
          if (cedulaInput) { cedulaInput.value = data.data.id; applyFilters(); }
          const row = document.querySelector(`#directoryTableBody tr[data-user-id="${CSS.escape(data.data.id)}"]`);
          const actionTd = row ? row.querySelector('.action-cell') : null;
          if (actionTd && !actionTd.querySelector('.btn-accredit-pending')) {
            const acreditarBtn = document.createElement('button');
            acreditarBtn.type = 'button';
            acreditarBtn.innerText = '✅ Acreditar';
            acreditarBtn.className = 'golden-btn btn-table-action btn-accredit-pending';
            acreditarBtn.addEventListener('click', async () => {
              acreditarBtn.disabled = true; acreditarBtn.innerText = 'Acreditando...';
              await fastCheckin(data.data.id, false, null, true, method);
            });
            actionTd.appendChild(acreditarBtn);
          }
          showToast(`${data.data.first_name} ${data.data.last_name} encontrado(a) — confirma con "Acreditar" en la fila`, 'success');
          if (data.data.sibling_events && data.data.sibling_events.length) {
            showToast(`ℹ️ Ya asistió a ${data.data.sibling_events.join(', ')} (mismo superevento) — sus datos ya están guardados`, 'success');
          }
          return;
        }
        // NO_MATCH: ya NO se ofrece alta manual automática (2026-09-16, pedido explícito — para
        // eso está el botón "Registrar nuevo" aparte). Si venía un nombre (CSV de la cédula
        // vieja, u OCR de la MRZ nueva), se filtra el Directorio por ese nombre — mismo criterio
        // de "empieza por palabra" que la búsqueda manual — y el operador decide desde ahí.
        const fullName = nameInfo ? `${nameInfo.nombres || ''} ${nameInfo.apellidos || ''}`.trim() : '';
        if (fullName && nombreInput) {
          if (cedulaInput) cedulaInput.value = '';
          nombreInput.value = fullName;
          applyFilters();
          const found = data.name_matches && data.name_matches.length;
          showToast(
            found
              ? `Cédula no encontrada — mostrando coincidencias por nombre para "${fullName}"`
              : `Cédula no encontrada y sin coincidencias por nombre para "${fullName}"`,
            found ? 'success' : 'error'
          );
        } else {
          showToast(data.details || 'Cédula no encontrada', 'error');
        }
      } catch (e) {
        showToast('Error de red', 'error');
      }
    }

    if (opts.fastCheckin && cedulaInput) {
      cedulaInput.addEventListener('keydown', (e) => {
        /* Blindaje contra atajos del navegador (Sprint 2 Parte 2, 2.2): la cédula nueva trae un
           QR encriptado por la Registraduría que, si el lector igual lo entrega como si fuera
           texto, puede incluir caracteres que el navegador interpreta como una combinación de
           teclas (confirmado en QA: abrió sola una pestaña/buscador) — un lector legítimo nunca
           necesita una tecla modificadora para escribir texto + Enter, así que se bloquean todas
           mientras el foco esté en este campo. Aplica en general, no solo para este caso puntual. */
        if (e.ctrlKey || e.altKey || e.metaKey) { e.preventDefault(); e.stopPropagation(); return; }
        if (e.key === 'Enter') {
          e.preventDefault();
          const raw = cedulaInput.value.trim();
          if (!raw) return;
          const parsed = parseOldCedulaBarcode(raw);
          const qr = window.QrCode ? QrCode.parse(raw) : null;
          if (qr && qr.isQr) {
            // QR propio (escarapela): cédula, o cédula|nombre — mismo flujo que la cédula: por cédula y luego por nombre.
            fastCheckin(qr.cedula, false, { nombres: qr.nombres, apellidos: qr.apellidos }, undefined, 'qr');
          } else if (parsed) {
            fastCheckin(parsed.cedula, false, { nombres: parsed.nombres, apellidos: parsed.apellidos });
          } else {
            fastCheckin(raw, false, null);
          }
          cedulaInput.value = '';
        }
      });
    }

    reload();
    return {
      reload,
      /* Punto de entrada compartido para cualquier OTRO método que resuelva una cédula+nombre
         fuera del campo de texto de arriba (ej. el escaneo por foto de la MRZ, Historia 2.3) —
         reusa exactamente el mismo flujo de dos pasos + DUPLICADO/force que el atajo de lector. */
      submitScannedCedula: (cedula, nameInfo, method) => fastCheckin(cedula, false, nameInfo || null, undefined, method),
      /* "Limpiar filtros" (2026-09-16, pedido explícito) — vacía los 3 campos de búsqueda + el
         filtro de "sin registrar" y vuelve a mostrar el Directorio completo. */
      clearFilters: () => {
        if (cedulaInput) cedulaInput.value = '';
        if (nombreInput) nombreInput.value = '';
        if (entidadInput) entidadInput.value = '';
        onlyNotRegistered = false;
        shownLimit = RENDER_LIMIT;
        if (counterBtn) { counterBtn.style.background = '#fbe9ea'; counterBtn.style.color = '#a12631'; }
        applyFilters();
      },
    };
  }

  window.GoldenDirectory = { render: renderRows, load: loadRows, mountSearch, parseOldCedulaBarcode, matchesWordPrefix, openEdit: buildEditModal };
})();
