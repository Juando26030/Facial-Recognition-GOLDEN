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

  /* opt_2 (antes "cantidad de empl") quedó deprecado el 2026-09-20 — la carga de base ahora usa
     hasta 30 campos "opcional_N" dinámicos (ver bulk_register/CLAUDE.md) en vez de dos fijos. Se
     deja de mostrar/editar aquí; el campo sigue existiendo en la base por compatibilidad. */
  const FIELDS_ORDER = ['id', 'first_name', 'last_name', 'role', 'company', 'phone', 'email', 'opt_1'];
  const EDITABLE_FIELDS = ['first_name', 'last_name', 'role', 'company', 'phone', 'email', 'opt_1'];

  /* Mismos mínimos que el backend exige de verdad (PATCH /api/users/{id} = coordinador+, DELETE
     .../logs = admin+, ver tabla de "Roles y permisos" en CLAUDE.md) — bug real encontrado en
     testing (DIR-06, 2026-09-21): el botón "Editar" se mostraba para digitador/cliente aunque el
     PATCH les fuera a dar 403 igual. Ocultar el botón entero es más claro que dejar que el
     usuario lo intente y falle. */
  const EDIT_ROLES = ['coordinador', 'admin', 'super_admin'];
  const DELETE_ROLES = ['admin', 'super_admin'];
  const canEdit = EDIT_ROLES.includes(window.STAFF_ROLE);
  const canDelete = DELETE_ROLES.includes(window.STAFF_ROLE);

  function buildRow(user, opts) {
    const tr = document.createElement('tr');
    tr.className = user.status === 'Registrado' ? 'row-registrado' : user.status === 'Nuevo' ? 'row-nuevo' : 'row-noregistrado';

    const tds = {};
    FIELDS_ORDER.forEach(field => {
      const td = document.createElement('td');
      td.innerText = user[field] || '';
      tr.appendChild(td);
      tds[field] = td;
    });

    const statusTd = document.createElement('td');
    statusTd.innerText = user.status;
    statusTd.style.fontWeight = 'bold';
    tr.appendChild(statusTd);

    const actionTd = document.createElement('td');
    actionTd.className = 'action-cell';

    if (opts.showAccredit && user.status === 'No registrado') {
      const accreditBtn = document.createElement('button');
      accreditBtn.innerText = 'Acreditar';
      accreditBtn.className = 'golden-btn btn-table-action btn-save';
      async function doAccredit(force) {
        accreditBtn.disabled = true;
        accreditBtn.innerText = 'Acreditando...';
        try {
          const formData = new FormData();
          formData.append('event_id', window.EVENT_ID);
          formData.append('cedula', user.id);
          if (force) formData.append('force', 'true');
          const res = await fetch('/api/checkin-cedula', { method: 'POST', body: formData });
          const data = await res.json();
          if (res.ok && data.result === 'DUPLICADO') {
            const confirmado = await confirmDuplicateRegistration(data.data);
            if (confirmado) { await doAccredit(true); return; }
            accreditBtn.disabled = false;
            accreditBtn.innerText = 'Acreditar';
            return;
          }
          if (res.ok && data.result === 'SÍ') {
            showToast('Acreditado', 'success');
            tr.className = 'row-registrado';
            statusTd.innerText = 'Registrado';
            user.status = 'Registrado';
            accreditBtn.remove();
          } else {
            showToast((data && (data.detail || data.details)) || 'No se pudo acreditar', 'error');
            accreditBtn.disabled = false;
            accreditBtn.innerText = 'Acreditar';
          }
        } catch (e) {
          showToast('Error de red', 'error');
          accreditBtn.disabled = false;
          accreditBtn.innerText = 'Acreditar';
        }
      }
      accreditBtn.addEventListener('click', () => doAccredit(false));
      actionTd.appendChild(accreditBtn);
    }

    if (!canEdit) {
      tr.appendChild(actionTd);
      return tr;
    }

    const actionBtn = document.createElement('button');
    actionBtn.innerText = 'Editar';
    actionBtn.className = 'golden-btn btn-table-action';

    const deleteBtn = document.createElement('button');
    deleteBtn.innerText = 'Eliminar';
    deleteBtn.className = 'btn-table-delete';
    deleteBtn.style.display = 'none';

    let isEditing = false;

    actionBtn.addEventListener('click', async () => {
      if (!isEditing) {
        isEditing = true;
        actionBtn.innerText = 'Guardar';
        actionBtn.classList.add('btn-save');
        if (canDelete) deleteBtn.style.display = 'inline-block';
        EDITABLE_FIELDS.forEach(field => {
          tds[field].contentEditable = 'true';
          tds[field].classList.add('editable-cell-active');
        });
        tds['first_name'].focus();
      } else {
        actionBtn.innerText = 'Guardando...';
        actionBtn.disabled = true;
        deleteBtn.style.display = 'none';

        const payload = {};
        EDITABLE_FIELDS.forEach(field => {
          payload[field] = tds[field].innerText.trim();
          tds[field].contentEditable = 'false';
          tds[field].classList.remove('editable-cell-active');
        });

        try {
          const updateRes = await fetch(withEvent(`/api/users/${user.id}`), {
            method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
          });
          if (updateRes.ok) {
            actionBtn.innerText = 'Editar';
            actionBtn.classList.remove('btn-save');
            isEditing = false;
            showToast('Cambios guardados', 'success');
          } else {
            showToast('Error al guardar cambios en SQL', 'error');
            actionBtn.innerText = 'Guardar';
          }
        } catch (error) {
          showToast('Error de red', 'error');
          actionBtn.innerText = 'Guardar';
        }
        actionBtn.disabled = false;
      }
    });

    deleteBtn.addEventListener('click', async () => {
      const fullName = `${user.first_name || ''} ${user.last_name || ''}`.trim();
      const isConfirmed = await showConfirm(`⚠️ CUIDADO: Estás a punto de borrar el registro de asistencia de ${fullName}.<br><br>Esto devolverá a la persona al estado "No registrado" y borrará sus logs de hoy, pero NO lo eliminará de la base de datos principal.`);
      if (!isConfirmed) return;
      try {
        const delRes = await fetch(withEvent(`/api/users/${user.id}/logs`), { method: 'DELETE' });
        if (delRes.ok) {
          showToast('Registro de asistencia eliminado', 'success');
          tr.className = 'row-noregistrado';
          statusTd.innerText = 'No registrado';
          user.status = 'No registrado';
          actionBtn.innerText = 'Editar';
          actionBtn.classList.remove('btn-save');
          deleteBtn.style.display = 'none';
          isEditing = false;
          EDITABLE_FIELDS.forEach(field => {
            tds[field].contentEditable = 'false';
            tds[field].classList.remove('editable-cell-active');
          });
        } else {
          showToast('Error al eliminar el registro', 'error');
        }
      } catch (e) {
        showToast('Error de red al intentar borrar', 'error');
      }
    });

    actionTd.appendChild(actionBtn);
    actionTd.appendChild(deleteBtn);
    tr.appendChild(actionTd);
    return tr;
  }

  function renderRows(tbodyId, users, opts) {
    opts = opts || {};
    const tbody = document.getElementById(tbodyId);
    tbody.innerHTML = '';
    if (users.length === 0) {
      tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; color:#888;">Sin resultados.</td></tr>';
      return;
    }
    users.forEach(user => tbody.appendChild(buildRow(user, opts)));
  }

  async function loadRows(tbodyId, opts) {
    opts = opts || {};
    const tbody = document.getElementById(tbodyId);
    tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;">Cargando base de datos...</td></tr>';
    try {
      const res = await fetch(withEvent('/api/users'));
      const users = await res.json();
      renderRows(tbodyId, users, opts);
      return users;
    } catch (err) {
      tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; color:red;">Error conectando al servidor</td></tr>';
      return [];
    }
  }

  /* Unifica en un solo componente lo que antes vivía duplicado inline en kiosk_cedula.html:
     los 3 campos de búsqueda independientes (cédula/nombre/empresa) que filtran en vivo sobre
     los datos ya cargados, más el atajo de lector de código de barras (Enter con cédula exacta
     = acreditar al instante, con el mismo flujo DUPLICADO/force de siempre). Reusado ahora por
     la vista de Registro unificada (2026-09-21) esté o no el modo cámara activo — la búsqueda
     no depende de si el evento tiene reconocimiento facial o no.
     opts: { tbodyId, searchIds: {cedula, nombre, empresa}, showAccredit, fastCheckin, onNotFound }
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
       reemplaza) que deja solo las filas en estado "No registrado". */
    const tbodyEl = document.getElementById(opts.tbodyId);
    const tableEl = tbodyEl ? tbodyEl.closest('table') : null;
    let counterBtn = null;
    if (tableEl && tableEl.parentNode) {
      counterBtn = document.createElement('button');
      counterBtn.type = 'button';
      counterBtn.className = 'not-registered-counter';
      counterBtn.style.cssText = 'display:inline-block; margin-bottom:1rem; border:1px solid #dc3545; background:#fbe9ea; color:#a12631; border-radius:20px; padding:6px 16px; font-weight:700; font-size:0.85rem; cursor:pointer;';
      counterBtn.addEventListener('click', () => {
        onlyNotRegistered = !onlyNotRegistered;
        counterBtn.style.background = onlyNotRegistered ? '#dc3545' : '#fbe9ea';
        counterBtn.style.color = onlyNotRegistered ? 'white' : '#a12631';
        applyFilters();
      });
      tableEl.parentNode.insertBefore(counterBtn, tableEl);
    }

    function updateCounterLabel() {
      if (!counterBtn) return;
      const count = allUsers.filter(u => u.status === 'No registrado').length;
      counterBtn.innerText = `⚠️ ${count} sin registrar` + (onlyNotRegistered ? ' (filtrando)' : '');
      counterBtn.style.display = count === 0 && !onlyNotRegistered ? 'none' : 'inline-block';
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
      renderRows(opts.tbodyId, filtered, { showAccredit: opts.showAccredit });
    }

    async function reload() {
      allUsers = await loadRows(opts.tbodyId, { showAccredit: opts.showAccredit });
      applyFilters();
    }

    [cedulaInput, nombreInput, empresaInput].forEach(input => {
      if (input) input.addEventListener('input', applyFilters);
    });

    async function fastCheckin(cedula, force) {
      const formData = new FormData();
      formData.append('event_id', window.EVENT_ID);
      formData.append('cedula', cedula);
      if (force) formData.append('force', 'true');
      try {
        const res = await fetch('/api/checkin-cedula', { method: 'POST', body: formData });
        const data = await res.json();
        if (!res.ok) { showToast(data.detail || 'No se pudo acreditar', 'error'); return; }
        if (data.result === 'DUPLICADO') {
          const confirmado = await confirmDuplicateRegistration(data.data);
          if (confirmado) await fastCheckin(cedula, true);
          return;
        }
        if (data.result === 'SÍ') {
          showToast(`Acreditado: ${data.data.first_name} ${data.data.last_name}`, 'success');
          reload();
        } else if (opts.onNotFound) {
          opts.onNotFound(cedula);
        } else {
          showToast(data.details || 'Cédula no encontrada', 'error');
        }
      } catch (e) {
        showToast('Error de red', 'error');
      }
    }

    if (opts.fastCheckin && cedulaInput) {
      cedulaInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          const cedula = cedulaInput.value.trim();
          if (!cedula) return;
          fastCheckin(cedula);
          cedulaInput.value = '';
        }
      });
    }

    reload();
    return { reload };
  }

  window.GoldenDirectory = { render: renderRows, load: loadRows, mountSearch };
})();
