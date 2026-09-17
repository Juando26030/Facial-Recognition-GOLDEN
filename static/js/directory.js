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

  function matchesWordPrefix(haystack, query) {
    const queryWords = wordsOf(query);
    if (!queryWords.length) return false;
    const haystackWords = wordsOf(haystack);
    return queryWords.every(qw => haystackWords.some(hw => hw.startsWith(qw)));
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
     los datos (cargo, empresa, teléfono, correo, opcionales) se muestran y editan SOLO dentro del
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
  const EDIT_ROLES = ['coordinador', 'admin', 'super_admin'];
  const ADMIN_ROLES = ['admin', 'super_admin'];
  const STATUS_ROLES = ['coordinador', 'admin', 'super_admin'];
  const canEdit = EDIT_ROLES.includes(window.STAFF_ROLE);
  const isAdmin = ADMIN_ROLES.includes(window.STAFF_ROLE);
  const canManageStatus = STATUS_ROLES.includes(window.STAFF_ROLE);

  /* Modal flotante de edición (2026-09-16, reemplaza la edición inline contentEditable de antes —
     con 10 columnas en pantalla no cabía nada sin scroll horizontal). Mismos campos que el alta
     manual (incluidos los opcionales dinámicos de este evento, vía window.OPTIONAL_VARIABLES,
     inyectado igual que en badge_editor.html). "Estado de registro" y "Eliminar" viven ACÁ dentro
     (no como botones sueltos en la fila) y solo se muestran para admin+ — mismo mínimo que ya
     exigía el backend en DELETE /users/{id}/logs. Cada una de las dos dispara su propia
     confirmación aparte del botón "Guardar cambios" de arriba (pedido explícito: "cada vez que
     vaya a hacer una de estas dos salga la notificación de confirmación"). */
  function buildEditModal(user) {
    // Parámetros del Evento (2026-09-16): las 5 variables fijas + cada opcional_N ya rotulado,
    // con el tipo de control/obligatoriedad/opciones que se haya definido en
    // /kiosk/{event_id}/parametros — mismo FIELD_CONFIGS que usa el alta manual (ver
    // kiosk_registro.html), para que Editar y Registrar nuevo se comporten igual.
    const fieldConfigs = window.FIELD_CONFIGS || [];
    const extras = user.extra_fields || {};

    function esc(v) { return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/"/g, '&quot;'); }
    function fieldRow(label, name, value, type) {
      return `<div style="margin-bottom:0.8rem;">
        <label style="display:block; font-size:0.78rem; font-weight:700; color:#888; margin-bottom:4px;">${label}</label>
        <input type="${type || 'text'}" name="${name}" value="${esc(value)}" style="width:100%; box-sizing:border-box; border:1px solid #ccc; border-radius:8px; padding:8px 10px; font-size:0.95rem;">
      </div>`;
    }
    function configuredValueOf(key) {
      return Object.prototype.hasOwnProperty.call(user, key) ? user[key] : extras[key];
    }
    function configuredFieldRow(cfg) {
      const control = window.FieldRender.renderControl(cfg, configuredValueOf(cfg.key));
      return `<div style="margin-bottom:0.8rem;">
        <label style="display:block; font-size:0.78rem; font-weight:700; color:#888; margin-bottom:4px;">${esc(cfg.label)}${cfg.required ? ' *' : ''}</label>
        ${control}
      </div>`;
    }

    const configuredHtml = fieldConfigs.map(configuredFieldRow).join('');
    const isRegistered = user.status !== 'No registrado';
    const originalStatus = isRegistered ? 'registrado' : 'no_registrado';

    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed; inset:0; background:rgba(10,14,46,0.45); z-index:9997; display:flex; align-items:center; justify-content:center; overflow:auto; padding:2rem 1rem;';
    const box = document.createElement('div');
    box.style.cssText = 'background:white; border-radius:16px; padding:1.8rem; max-width:520px; width:100%; box-shadow:0 20px 60px rgba(0,0,0,0.3); font-family: var(--font-body, sans-serif); max-height:90vh; overflow:auto;';
    box.innerHTML = `
      <h4 style="margin-top:0; color:var(--golden-dark);">Editar persona</h4>
      <form id="editModalForm">
        <div style="display:flex; gap:0.8rem;">
          <div style="flex:1;">${fieldRow('Nombres', 'first_name', user.first_name)}</div>
          <div style="flex:1;">${fieldRow('Apellidos', 'last_name', user.last_name)}</div>
        </div>
        <div style="margin-bottom:0.8rem;">
          <label style="display:block; font-size:0.78rem; font-weight:700; color:#888; margin-bottom:4px;">Cédula</label>
          <input type="text" id="editModalCedulaField" value="${esc(user.id)}" ${isAdmin ? '' : 'disabled'} style="width:100%; box-sizing:border-box; border:1px solid ${isAdmin ? '#ccc' : '#ddd'}; border-radius:8px; padding:8px 10px; font-size:0.95rem; ${isAdmin ? '' : 'background:#f5f5f5; color:#888;'}">
          ${isAdmin ? '<p style="font-size:0.72rem; color:#aaa; margin:4px 0 0;">Corrige un error de digitación (ej. se acreditó por nombre porque la cédula quedó mal). Afecta a esta persona en TODOS los eventos de este cliente, no solo este.</p>' : ''}
        </div>
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
          <option value="no_registrado" ${!isRegistered ? 'selected' : ''}>No registrado</option>
          <option value="registrado" ${isRegistered ? 'selected' : ''}>Registrado</option>
        </select>
        <p style="font-size:0.72rem; color:#aaa; margin:4px 0 0;">Se aplica junto con el resto de cambios al pulsar "Guardar cambios" — ya no hace falta un botón aparte.</p>
      </div>
      <button type="button" id="editModalDelete" class="btn-table-delete" style="width:100%; padding:10px; font-size:0.85rem;">🗑️ Eliminar de este evento</button>
      ` : ''}
    `;
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    function close() { overlay.remove(); }
    // 2026-09-16 (Sprint 2.4 Fase 3, pedido explícito): ya NO se cierra al hacer clic afuera —
    // solo con "Cancelar" o guardando, para no perder cambios sin querer.
    box.querySelector('#editModalCancel').addEventListener('click', close);

    box.querySelector('#editModalSave').addEventListener('click', async () => {
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
          const ok = await showConfirm(`¿Cambiar el estado de registro de esta persona a "${label}"? Se guardará junto con el resto de cambios.`, { variant: 'warning', confirmLabel: 'Sí, cambiar y guardar' });
          if (!ok) return;
          saveBtn.disabled = true; saveBtn.innerText = 'Guardando...';
          try {
            const statusRes = await fetch(`/api/events/${window.EVENT_ID}/users/${currentId}/status`, {
              method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: newStatus }),
            });
            if (!statusRes.ok) {
              const data = await statusRes.json().catch(() => ({}));
              showToast(data.detail || 'No se pudo cambiar el estado', 'error');
              saveBtn.disabled = false; saveBtn.innerText = 'Guardar cambios';
              return;
            }
          } catch (e) {
            showToast('Error de red', 'error');
            saveBtn.disabled = false; saveBtn.innerText = 'Guardar cambios';
            return;
          }
        }
      }

      const payload = { first_name: val('first_name'), last_name: val('last_name') };
      const newExtras = {};
      fieldConfigs.forEach((cfg) => {
        if (Object.prototype.hasOwnProperty.call(user, cfg.key)) payload[cfg.key] = val(cfg.key);
        else newExtras[cfg.key] = val(cfg.key);
      });
      payload.extra_fields = newExtras;

      saveBtn.disabled = true; saveBtn.innerText = 'Guardando...';
      try {
        const res = await fetch(withEvent(`/api/users/${currentId}`), {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
        });
        if (res.ok) {
          showToast('Cambios guardados', 'success');
          close();
          if (window.directorySearch) window.directorySearch.reload();
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
    if (!PRINT_HIDDEN_ROLES.includes(window.STAFF_ROLE)) {
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
     los 3 campos de búsqueda independientes (cédula/nombre/empresa) que filtran en vivo sobre
     los datos ya cargados, más el atajo de lector de código de barras (Enter con cédula exacta
     = acreditar al instante, con el mismo flujo DUPLICADO/force de siempre). Reusado ahora por
     la vista de Registro unificada (2026-09-21) esté o no el modo cámara activo — la búsqueda
     no depende de si el evento tiene reconocimiento facial o no.
     opts: { tbodyId, searchIds: {cedula, nombre, empresa}, fastCheckin }
     Devuelve { reload() } para que la página pueda refrescar manualmente (ej. al volver a la
     pestaña, o tras registrar a alguien nuevo desde otra pestaña). */
  function mountSearch(opts) {
    let allUsers = [];
    let onlyNotRegistered = false;
    const ids = opts.searchIds || {};
    const cedulaInput = ids.cedula ? document.getElementById(ids.cedula) : null;
    const nombreInput = ids.nombre ? document.getElementById(ids.nombre) : null;
    const empresaInput = ids.empresa ? document.getElementById(ids.empresa) : null;

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

    function applyFilters() {
      const cedula = (cedulaInput && cedulaInput.value || '').trim().toLowerCase();
      const nombre = (nombreInput && nombreInput.value || '').trim();
      const empresa = (empresaInput && empresaInput.value || '').trim();
      const filtered = allUsers.filter(u => {
        if (onlyNotRegistered && u.status !== 'No registrado') return false;
        if (cedula && !String(u.id || '').toLowerCase().includes(cedula)) return false;
        if (nombre) {
          const fullName = `${u.first_name || ''} ${u.last_name || ''}`;
          if (!matchesWordPrefix(fullName, nombre)) return false;
        }
        if (empresa && !matchesWordPrefix(String(u.company || ''), empresa)) return false;
        return true;
      });
      updateCounterLabel();
      renderRows(opts.tbodyId, filtered);
    }

    async function reload() {
      allUsers = await loadRows(opts.tbodyId);
      applyFilters();
    }

    [cedulaInput, nombreInput, empresaInput].forEach(input => {
      if (input) input.addEventListener('input', applyFilters);
    });

    /* nameInfo (Sprint 2 Parte 2, 2.1): {nombres, apellidos} cuando el escaneo trajo un nombre
       completo además de la cédula (CSV de la cédula vieja, o el OCR de la MRZ de la nueva) —
       null si solo se tiene un ID suelto (búsqueda de siempre). Búsqueda en dos pasos: primero
       coincidencia exacta por cédula; si no hay match Y sí hay nombre, se intenta un segundo
       paso buscando ese nombre completo entre los ya cargados en el Directorio, reutilizando el
       mismo criterio de prefijo por palabra + insensible a tildes de arriba — recién si ninguno
       de los dos encuentra nada se cae al comportamiento de "no encontrado" de siempre. */
    async function fastCheckin(cedula, force, nameInfo, confirmFlag) {
      const formData = new FormData();
      formData.append('event_id', window.EVENT_ID);
      formData.append('cedula', cedula);
      if (force) formData.append('force', 'true');
      if (confirmFlag) formData.append('confirm', 'true');
      if (nameInfo) {
        if (nameInfo.nombres) formData.append('first_name', nameInfo.nombres);
        if (nameInfo.apellidos) formData.append('last_name', nameInfo.apellidos);
      }
      try {
        const res = await fetch('/api/checkin-cedula', { method: 'POST', body: formData });
        const data = await res.json();
        if (!res.ok) { showToast(data.detail || 'No se pudo acreditar', 'error'); return; }
        if (data.result === 'DUPLICADO') {
          const confirmado = await confirmDuplicateRegistration(data.data, data.times_registered);
          if (confirmado) await fastCheckin(cedula, true, nameInfo);
          return;
        }
        if (data.result === 'SÍ') {
          // Match exacto por cédula: acredita de una vez, sin modal aparte (2026-09-16, pedido
          // explícito) — la "confirmación" es ver la fila aparecer filtrada en el Directorio,
          // como si se hubiera buscado por cédula a mano.
          showToast(`Acreditado: ${data.data.first_name} ${data.data.last_name}`, 'success');
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
              await fastCheckin(data.data.id, false, null, true);
            });
            actionTd.appendChild(acreditarBtn);
          }
          showToast(`${data.data.first_name} ${data.data.last_name} encontrado(a) — confirma con "Acreditar" en la fila`, 'success');
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
          if (parsed) {
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
      submitScannedCedula: (cedula, nameInfo) => fastCheckin(cedula, false, nameInfo || null),
      /* "Limpiar filtros" (2026-09-16, pedido explícito) — vacía los 3 campos de búsqueda + el
         filtro de "sin registrar" y vuelve a mostrar el Directorio completo. */
      clearFilters: () => {
        if (cedulaInput) cedulaInput.value = '';
        if (nombreInput) nombreInput.value = '';
        if (empresaInput) empresaInput.value = '';
        onlyNotRegistered = false;
        if (counterBtn) { counterBtn.style.background = '#fbe9ea'; counterBtn.style.color = '#a12631'; }
        applyFilters();
      },
    };
  }

  window.GoldenDirectory = { render: renderRows, load: loadRows, mountSearch, parseOldCedulaBarcode };
})();
