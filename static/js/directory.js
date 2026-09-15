/* Directorio en vivo, compartido entre kiosk.html (Facial) y kiosk_cedula.html (Cédula) — mismo
   patrón de Editar/Guardar/Eliminar en ambos, más un botón "Acreditar" opcional para el flujo de
   cédula (marca a alguien como Registrado sin necesidad de entrar por Facial). */
(function () {
  function withEvent(url) {
    return url + (url.includes('?') ? '&' : '?') + 'event_id=' + window.EVENT_ID;
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

  window.GoldenDirectory = {
    render(tbodyId, users, opts) {
      opts = opts || {};
      const tbody = document.getElementById(tbodyId);
      tbody.innerHTML = '';
      if (users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; color:#888;">Sin resultados.</td></tr>';
        return;
      }
      users.forEach(user => tbody.appendChild(buildRow(user, opts)));
    },

    async load(tbodyId, opts) {
      opts = opts || {};
      const tbody = document.getElementById(tbodyId);
      tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;">Cargando base de datos...</td></tr>';
      try {
        const res = await fetch(withEvent('/api/users'));
        const users = await res.json();
        this.render(tbodyId, users, opts);
        return users;
      } catch (err) {
        tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; color:red;">Error conectando al servidor</td></tr>';
        return [];
      }
    },
  };
})();
