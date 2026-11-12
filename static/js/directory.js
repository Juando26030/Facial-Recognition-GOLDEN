/* Directorio en vivo, usado por kiosk_registro.html (vista de Registro unificada, 2026-09-21 —
   antes eran dos templates separados, kiosk.html "Facial" y kiosk_cedula.html "Cédula", con esta
   lógica de tabla duplicada entre ambos). Patrón Editar/Guardar/Eliminar + botón "Acreditar"
   opcional (marca a alguien como Registrado sin pasar por el escáner) + mountSearch() para los
   3 campos de búsqueda en vivo y el atajo de lector de código de barras. */
(function () {
  /* A5 (26-oct-2026): las últimas 5 personas que ESTE equipo registró o editó (de la más reciente a la más antigua), guardadas en el equipo. Van primero en SU lista, también tras
     «Limpiar filtros» o refrescar; con un filtro de búsqueda activo se respeta el filtro. No cambia el orden de otros equipos. */
  const Recent = {
    key() { return 'gw_recent_' + (window.EVENT_ID || ''); },
    list() { try { const v = JSON.parse(localStorage.getItem(this.key()) || '[]'); return Array.isArray(v) ? v.map(String).slice(0, 5) : []; } catch (e) { return []; } },
    add(id) { if (!id) return; id = String(id); const l = [id].concat(this.list().filter((x) => x !== id)).slice(0, 5); try { localStorage.setItem(this.key(), JSON.stringify(l)); } catch (e) { /* sin almacenamiento */ } },
    has(id) { return !!id && this.list().indexOf(String(id)) >= 0; },
  };
  /* Cola compartida de recién registrados: la ventana es RELATIVA a la acción más nueva de la lista (recent_at del servidor, UTC); nunca se usa el reloj de este equipo. */
  const RECENT_WINDOW_MS = 15 * 60 * 1000;
  function recentMs(u) { const t = u && u.recent_at ? Date.parse(u.recent_at) : NaN; return Number.isNaN(t) ? null : t; }
  function newestRecentMs(list) { let m = null; for (const u of list) { const t = recentMs(u); if (t !== null && (m === null || t > m)) m = t; } return m; }
  /* Sin consulta de búsqueda: primero lo que ESTE equipo acaba de hacer y el servidor aún no trae (la más reciente primero), luego todo lo que trae recent_at (la más nueva primero), luego el resto en su orden. */
  function orderByRecency(list) {
    const pos = new Map(Recent.list().map((id, i) => [id, i]));
    const locals = [], served = [], rest = [];
    list.forEach((u) => { const t = recentMs(u); if (t !== null) served.push([u, t]); else if (pos.has(String(u.id))) locals.push(u); else rest.push(u); });
    locals.sort((a, b) => pos.get(String(a.id)) - pos.get(String(b.id)));
    served.sort((a, b) => b[1] - a[1]);
    return locals.concat(served.map((x) => x[0]), rest);
  }
  function isRecentRow(u, newest) { const t = recentMs(u); if (t !== null) return newest !== null && newest - t < RECENT_WINDOW_MS; return Recent.has(u.id); }
  const ORIGINS = { base: { icon: '', label: 'Base (Excel)' }, manual: { icon: '', label: 'Creado nuevo' }, autoregistro: { icon: '', label: 'Autoregistro' }, desconocido: { icon: '', label: 'Desconocido' } };
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
  /* PR3 (4a, autoimpresión): las banderas del evento las decide el SERVIDOR (respuestas de checkin-cedula/register/status/undo y `flags` de /users/changes), no la página. Se copian a las variables de
     la página (BadgePrint.setFlags) y a la copia local (el autorregistro sin red usa la última conocida, ya no la de la descarga de hace hasta 4 min). */
  function applyFlags(flags) {
    if (!flags || typeof flags !== 'object') return;
    if (window.BadgePrint && BadgePrint.setFlags) BadgePrint.setFlags(flags);
    const gc = window.GoldenContingency && window.GoldenContingency.instance;
    if (gc && gc.setAutoRegister && typeof flags.auto_register === 'boolean') gc.setAutoRegister(flags.auto_register);
  }
  const jsonOf = async (r) => { try { return (await r.json()) || {}; } catch (e) { return {}; } };
  const primePrint = () => { if (window.BadgePrint && BadgePrint.primeWindow) { try { BadgePrint.primeWindow(); } catch (e) { /* sin ventana preparada */ } } };       // dentro del gesto del usuario (ver badge-render.js)
  const cancelPrimedPrint = () => { if (window.BadgePrint && BadgePrint.cancelPrimed) BadgePrint.cancelPrimed(); };
  /* Veredicto grande (static/js/registro-veredicto.js, Fase 1.7): solo muestra el resultado con ícono y palabras; los avisos de siempre (toasts) y el flujo no cambian. Sin la banda, no hace nada. */
  const verdict = (kind, title, text) => { try { if (typeof window !== 'undefined' && window.GWVerdict) window.GWVerdict.show(kind, title, text); } catch (e) { /* sin banda: nada */ } };
  let lastAccredit = null;          // última acreditación hecha (para ofrecer «Deshacer»): { cid, name, offline, at }
  async function offlineAccredit(GC, target, method, cid) {
    const found = target.h ? await GC.findByHash(target.h) : await GC.scanLocal(target.cedula);
    if (found.status === 'expired') { showToast('No hay copia local vigente: verificar manualmente', 'error'); verdict('err', 'Verificar manualmente', 'No hay copia local vigente de la lista.'); return null; }
    if (found.status === 'not_found') { showToast('No registrado: verificar manualmente', 'error'); verdict('err', 'No está en la lista', 'Verificar manualmente.'); return null; }
    if (found.duplicate && !(await confirmDuplicateRegistration({ first_name: found.person.n, last_name: '' }, undefined))) { verdict('warn', 'Ya estaba registrado(a)', found.person.n); return null; }
    const tm = window.RegTimer ? RegTimer.payload() : null;          // 1A: tiempo medido; viaja en la cola y se envía al sincronizar
    await GC.enqueue(found, method, cid, tm);
    if (window.RegTimer) RegTimer.done();
    lastAccredit = { cid, name: found.person.n, offline: true, at: Date.now() };
    showToast(`Acreditado: ${found.person.n}`, 'success');
    verdict('ok', 'Acreditado(a)', `${found.person.n} · sin conexión: queda guardado y se envía solo al volver la red`);
    accreditHooks.forEach((f) => f(found));
    return found;
  }

  /* Editar SIN red (contingencia): modal limitado. Solo el nombre (lectura) y el «Estado de registro»; el resto de campos no se ofrece y se avisa. «Registrado» se encola igual que un escaneo
     (client_id, huella de la copia local, método `manual`), con el aviso de DUPLICADO si ya consta o está en la cola. Guardar nunca dice «Error de red» genérico. Devuelve los controles
     (para las pruebas). */
  const OFFLINE_EDIT_NOTICE = 'Sin conexión: solo se puede cambiar el estado de registro; para editar datos espera a que vuelva la red';
  /* Acción con rueda (GW.busy, gw-busy.js): bloquea el doble clic y muestra «trabajando» en el botón. Sin el ayudante (pruebas con DOM falso) solo corre la acción. La acción arranca
     de inmediato (síncrona hasta su primer await), así que la ventana de impresión preparada dentro del clic sigue válida. */
  const busyBtn = (btn, work) => (window.GW && window.GW.busy && btn && btn.setAttribute ? window.GW.busy(btn, work) : new Promise((resolve) => resolve(work())));
  function buildOfflineEditModal(user, GC) {
    const mk = (tag, text, cls) => { const el = document.createElement(tag); if (text) el.textContent = text; if (cls) el.className = cls; return el; };
    const overlay = mk('div', '', 'gw-modal-backdrop gw-registro__edit'); overlay.setAttribute('data-open', 'true');
    overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-modal', 'true'); overlay.setAttribute('aria-label', 'Editar persona sin conexión');
    const box = mk('div', '', 'gw-modal gw-registro__editbox');
    const notice = mk('p', OFFLINE_EDIT_NOTICE, 'gw-alert gw-alert--warn');
    notice.setAttribute('role', 'status');
    const name = mk('input', '', 'gw-input gw-registro__editgap');
    name.value = `${user.first_name || ''} ${user.last_name || ''}`.trim(); name.readOnly = true; name.disabled = true; name.setAttribute('aria-label', 'Nombre (solo lectura)');
    const statusLabel = mk('label', 'Estado de registro', 'gw-label');
    const select = mk('select', '', 'gw-select'); select.id = 'offlineEditStatusSimple'; statusLabel.setAttribute('for', 'offlineEditStatusSimple');
    [['no_registrado', 'No registrado'], ['registrado', 'Registrado']].forEach(([v, t]) => { const o = mk('option', t); o.value = v; select.appendChild(o); });
    select.value = 'registrado';                                              // igual que en línea: «Registrado» preseleccionado
    const actions = mk('div', '', 'gw-rowact gw-registro__editactions');
    const cancel = mk('button', 'Cancelar', 'gw-btn gw-btn--secondary'); cancel.type = 'button';
    const save = mk('button', 'Guardar cambios', 'gw-btn gw-btn--primary'); save.type = 'button';
    [cancel, save].forEach((b) => actions.appendChild(b));
    [mk('h4', 'Editar persona', 'gw-modal__title gw-registro__edittitle'), notice, name, statusLabel, select, actions].forEach((el) => box.appendChild(el));
    overlay.appendChild(box); document.body.appendChild(overlay);
    const close = () => overlay.remove();
    cancel.addEventListener('click', close);
    save.addEventListener('click', async () => {
      await busyBtn(save, async () => {
        if (!GC.active()) { close(); showToast('Volvió la conexión: abre Editar de nuevo para ver todos los campos', 'success'); return; }
        if (select.value !== 'registrado') { showToast('Sin conexión: solo se puede registrar; para quitar un registro espera a que vuelva la red', 'error'); return; }
        save.disabled = true;
        try {
          const found = await offlineAccredit(GC, user.__h ? { h: user.__h } : { cedula: user.id }, 'manual');
          if (found) close();
        } finally { save.disabled = false; }
      });
    });
    return { overlay, box, notice, name, select, save, cancel, close };
  }


  /* Editar SIN red con el FORMULARIO DE PERSONA (Fase 1A, pieza 5; solo si el evento lo tiene prendido y la bandeja de salida funciona): la persona se edita igual que con red, sin ver sus datos guardados, así
     que se escribe SOLO lo que cambia (lo que va en blanco queda como estaba) y se encola una operación `edit_person` con la versión del formulario (outbox.js). Cédula, fecha de nacimiento, firmas/consentimientos y
     el envío de la escarapela digital piden conexión (quedan deshabilitados con el motivo). El «Estado de registro» se encola como siempre. Devuelve los controles (para las pruebas) o null si no aplica. */
  const OFFLINE_BLOCKED_TYPES = ['signature', 'consent', 'date', 'digital_contact'];
  function buildOfflinePersonEditModal(user, GC) {
    const pfDef = window.PERSON_FORM && window.PersonForm ? window.PERSON_FORM : null;
    const box = window.GoldenOutbox && window.GoldenOutbox.instance;
    if (!pfDef || !box || !box.supported || !window.FieldRender) return null;
    const cfgs = window.FIELD_CONFIGS || [];
    const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const blocked = (cfg) => cfg.key === 'id' || OFFLINE_BLOCKED_TYPES.includes(cfg.field_type) || cfg.key === 'birth_date';
    const wrap = (cfg, control) => `<div class="gw-field badge-input-group" data-field-key="${esc(cfg.key)}"><label class="gw-label">${esc(cfg.label)}</label>${control}</div>`;
    const fieldsHtml = cfgs.map((cfg) => {
      if (cfg.key === 'id') return wrap(cfg, `<input type="text" name="id_readonly" class="gw-input" value="${esc(user.id || '')}" disabled>`);
      if (cfg.field_type === 'categories') return wrap(cfg, window.FieldRender.renderControl(cfg, user.categories));
      if (cfg.field_type === 'certificate') return wrap(cfg, window.FieldRender.renderControl(cfg, ''));
      if (cfg.field_type === 'digital_contact' || cfg.field_type === 'date' || cfg.field_type === 'signature' || cfg.field_type === 'consent') return wrap(cfg, window.FieldRender.renderControl(cfg, ''));
      return wrap(cfg, window.FieldRender.renderControl(cfg, ''));
    }).join('');
    const overlay = document.createElement('div');
    overlay.className = 'gw-modal-backdrop gw-registro__edit'; overlay.setAttribute('data-open', 'true');
    overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-modal', 'true'); overlay.setAttribute('aria-label', 'Editar persona sin conexión');
    const name = `${user.first_name || ''} ${user.last_name || ''}`.trim();
    overlay.innerHTML = `<div class="gw-modal gw-registro__editflush">
      <div class="gw-modal__head"><h4 class="gw-modal__title">Editar persona</h4></div>
      <div class="gw-modal__body">
        <div class="gw-alert gw-alert--warn" role="status"><div><div class="gw-alert__title">Sin conexión</div><div class="gw-alert__body"></div></div></div>
        <p class="gw-label" data-pf-who></p>
        <form id="offlineEditForm" novalidate><div id="offlineEditFields">${fieldsHtml}</div></form>
        <div class="gw-field"><label class="gw-label" for="offlineEditStatus">Estado de registro</label>
          <select class="gw-select" id="offlineEditStatus"><option value="no_registrado">No registrado</option><option value="registrado" selected>Registrado</option></select></div>
      </div>
      <div class="gw-modal__foot"><button type="button" class="gw-btn gw-btn--secondary" data-pf-cancel>Cancelar</button><button type="button" class="gw-btn gw-btn--primary" data-pf-save>Guardar cambios</button></div>
    </div>`;
    overlay.querySelector('.gw-alert__body').textContent = 'Escribe solo lo que cambia: lo que dejes en blanco queda como estaba. Se guarda en este dispositivo y se envía solo al volver la red. La cédula, la fecha de nacimiento y las firmas piden conexión.';
    overlay.querySelector('[data-pf-who]').textContent = name ? `Persona: ${name}` : 'Persona de la lista local';
    document.body.appendChild(overlay);
    const form = overlay.querySelector('#offlineEditForm'), fieldsBox = overlay.querySelector('#offlineEditFields');
    const ctl = window.PersonForm.mount(fieldsBox, pfDef, { disableKeys: cfgs.filter(blocked).map((c) => c.key), disabledHint: 'Requiere conexión' });
    fieldsBox.querySelectorAll('[required]').forEach((n) => n.removeAttribute('required'));          // en blanco = como estaba: nada se exige sin red (el servidor revisa lo obligatorio al recibirlo)
    fieldsBox.querySelectorAll('label').forEach((l) => { if (l.children.length === 0) l.textContent = l.textContent.replace(/\s*\*\s*$/, ''); });
    const close = () => { ctl.destroy(); overlay.remove(); };
    const collect = () => {
      ctl.applyAll();
      const fields = {}, extras = {};
      cfgs.filter((c) => !blocked(c)).forEach((cfg) => {
        if (cfg.field_type === 'categories') { const cats = Array.from(form.querySelectorAll('input[name="categories"]:checked')).map((i) => i.value); if (cats.length) fields.categories = cats; return; }
        if (cfg.field_type === 'certificate') { if (form.querySelector('input[name="certificate"]:checked')) fields.certificate = 'true'; return; }
        const el = Array.from(form.elements).find((e) => e.name === cfg.key);
        const v = el && el.value ? String(el.value).trim() : '';
        if (!v) return;
        if (/^opcional_\d+$/.test(cfg.key)) extras[cfg.key] = v; else fields[cfg.key] = v;
      });
      if (Object.keys(extras).length) fields.extra_fields = extras;
      return fields;
    };
    const save = overlay.querySelector('[data-pf-save]');
    overlay.querySelector('[data-pf-cancel]').addEventListener('click', close);
    save.addEventListener('click', async () => { await busyBtn(save, async () => {
      if (!GC.active()) { close(); showToast('Volvió la conexión: abre Editar de nuevo para ver todos los campos', 'success'); return; }
      const fields = collect(), status = overlay.querySelector('#offlineEditStatus').value;
      if (status !== 'registrado' && !Object.keys(fields).length) { showToast('Sin conexión: escribe lo que cambia, o deja «Registrado» para acreditarla', 'error'); return; }
      save.disabled = true;
      try {
        const target = user.__h ? { h: user.__h } : { cedula: user.id };
        if (Object.keys(fields).length) {
          if (user.__h) fields.h = user.__h; else fields.id = user.id;
          const pf = window.PERSON_FORM;
          PersonForm.applyCase(fields, pf);
          await box.enqueue(fields, `Edición: ${name || 'persona'}`, { type: 'edit_person', form_version: pf.form_version, form_sig: pf.form_sig });
          showToast('Cambios guardados en este dispositivo: se envían solos al volver la red', 'success');
        }
        if (status === 'registrado') { const found = await offlineAccredit(GC, target, 'manual'); if (!found && !Object.keys(fields).length) return; }
        close();
      } catch (e) { showToast(e.message || 'No se pudo guardar en este dispositivo', 'error'); }
      finally { save.disabled = false; }
    }); });
    return { overlay, form, ctl, save, close, collect };
  }

  /* Modal flotante de edición (2026-09-16, reemplaza la edición inline contentEditable de antes —
     con 10 columnas en pantalla no cabía nada sin scroll horizontal). Mismos campos que el alta
     manual (incluidos los opcionales dinámicos de este evento, vía window.OPTIONAL_VARIABLES,
     inyectado igual que en badge_editor.html). "Estado de registro" y "Eliminar" viven ACÁ dentro
     (no como botones sueltos en la fila) y solo se muestran para admin+ — mismo mínimo que ya
     exigía el backend en DELETE /users/{id}/logs. Cada una de las dos dispara su propia
     confirmación aparte del botón "Guardar cambios" de arriba (pedido explícito: "cada vez que
     vaya a hacer una de estas dos salga la notificación de confirmación"). */
  /* Eliminar a una persona del evento (con confirmación; la usan «Editar persona» y el menú «Más» de la fila). done() corre solo si se eliminó. */
  async function deletePerson(user, done) {
    const GCd = window.GoldenContingency && window.GoldenContingency.instance;
    if (GCd && GCd.active()) { showToast(OFFLINE_EDIT_NOTICE, 'error'); return; }
    const fullName = `${user.first_name || ''} ${user.last_name || ''}`.trim();
    const ok = await showConfirm(`Atención: se elimina a ${window.escapeHtml(fullName || 'esta persona')} del registro de este evento (y de la base general si no pertenece a ningún otro evento de este cliente). No se puede deshacer. ¿Continuar?`, { confirmLabel: 'Eliminar' });
    if (!ok) return;
    try {
      const res = await fetch(withEvent(`/api/users/${user.id}`), { method: 'DELETE' });
      if (res.ok) {
        showToast('Persona eliminada', 'success');
        if (done) done();
        if (window.directorySearch) window.directorySearch.reload();
      } else {
        const data = await res.json().catch(() => ({}));
        showToast(data.detail || 'No se pudo eliminar', 'error');
      }
    } catch (e) { showToast('Error de red', 'error'); }
  }

  function buildEditModal(user, opts) {
    const GCm = window.GoldenContingency && window.GoldenContingency.instance;
    if (GCm && GCm.active()) return buildOfflinePersonEditModal(user, GCm) || buildOfflineEditModal(user, GCm);          // sin red: con el formulario de persona se edita y se encola; si no, modal limitado (solo estado de registro)
    opts = opts || {};       // { method: 'biometrico' (el ingreso viene de una verificación facial), onSaved(id) }
    // Parámetros del Evento (2026-09-16): las 5 variables fijas + cada opcional_N ya rotulado,
    // con el tipo de control/obligatoriedad/opciones que se haya definido en
    // /kiosk/{event_id}/parametros — mismo FIELD_CONFIGS que usa el alta manual (ver
    // kiosk_registro.html), para que Editar y Registrar nuevo se comporten igual.
    const fieldConfigs = window.FIELD_CONFIGS || [];
    const extras = user.extra_fields || {};

    function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
    function fieldRow(label, name, value, type, required) {
      const req = required !== false;          // nombres y cédula siempre; el apellido solo si el evento lo exige (app/lastname.py)
      return `<div class="gw-field gw-registro__editfield">
        <label class="gw-label">${esc(label)}${req ? '<span class="gw-req" aria-hidden="true"> *</span>' : ''}</label>
        <input type="${type || 'text'}" name="${name}" value="${esc(value)}" class="gw-input"${req ? ' required' : ''}>
      </div>`;
    }
    function cedulaRow(label) {
      return `<div class="gw-field gw-registro__editfield">
          <label class="gw-label" for="editModalCedulaField">${esc(label)}<span class="gw-req" aria-hidden="true"> *</span></label>
          <input type="text" id="editModalCedulaField" value="${esc(user.id)}" ${isAdmin ? '' : 'disabled'} class="gw-input">
          ${isAdmin ? '<p class="gw-hint">Corrige un error de digitación (ej. se acreditó por nombre porque la cédula quedó mal). Afecta a esta persona en TODOS los eventos de este cliente, no solo este.</p>' : ''}
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
      return `<div class="gw-field gw-registro__editfield">
        <label class="gw-label">${esc(cfg.label)}${cfg.required ? '<span class="gw-req" aria-hidden="true"> *</span>' : ''}</label>
        ${control}
      </div>`;
    }

    // Todos los campos en el orden definido en Parámetros del Evento (ítems 3a/4): la identidad
    // (nombres/apellidos/cédula) entra en la misma lista, con la etiqueta propia del evento.
    const pfDef = window.PERSON_FORM && window.PersonForm ? window.PERSON_FORM : null;          // formulario de persona diseñado (apagado por defecto: sin él, nada cambia)
    const keyed = (cfg, html) => (pfDef ? `<div data-field-key="${esc(cfg.key)}">${html}</div>` : html);
    const configuredHtml = fieldConfigs.map((cfg) => keyed(cfg, (() => {
      if (cfg.key === 'id') return cedulaRow(cfg.label);
      if (cfg.field_type === 'categories') return configuredFieldRow(cfg, user.categories);
      if (cfg.field_type === 'certificate') return configuredFieldRow(cfg, user.certificate ? 'true' : '');
      if (cfg.field_type === 'digital_contact') return configuredFieldRow({ ...cfg, __sentAt: user.digital_sent_at }, user.digital_contact || '');
      if (cfg.field_type === 'date') return `<div class="gw-field gw-registro__editfield">
        <label class="gw-label">${esc(cfg.label)}</label>
        <input type="date" name="${cfg.key}" value="${esc(user.birth_date || '')}" max="${new Date().toISOString().slice(0, 10)}" class="gw-input">
        <p class="gw-hint">Define si es menor de 18 años: un menor no usa el reconocimiento facial. Si la cambias a una fecha de menor, se borran su rostro y su foto.</p>
      </div>`;
      if (cfg.locked) return fieldRow(cfg.label, cfg.key, user[cfg.key], 'text', (cfg.key === 'last_name' || cfg.key === 'code') ? !!cfg.required : true);          // el código (solo existe con el interruptor activo) y el apellido: obligatorios según el evento
      return configuredFieldRow(cfg);
    })())).join('');
    const isRegistered = user.status !== 'No registrado';
    const originalStatus = isRegistered ? 'registrado' : 'no_registrado';
    // 2026-09-23, pedido explícito: al darle Editar a alguien que aún no llegó, "Registrado" queda
    // preseleccionado — guardar sin tocar nada ya lo deja acreditado (en verde).
    const defaultStatus = 'registrado';

    const overlay = document.createElement('div');
    overlay.className = 'gw-modal-backdrop gw-registro__edit'; overlay.setAttribute('data-open', 'true');
    overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-modal', 'true'); overlay.setAttribute('aria-label', 'Editar persona');
    const box = document.createElement('div');
    box.className = 'gw-modal gw-registro__editbox';
    const iconUrl = (window.GW_ICON_URL || '/static/img/icons.svg');
    box.innerHTML = `
      <div class="gw-modal__head gw-registro__edithead">
        <h4 class="gw-modal__title gw-registro__edittitle">Editar persona</h4>
        <button type="button" id="editModalCancel" class="gw-btn gw-btn--secondary">Cancelar</button>
        <button type="button" id="editModalSave" class="gw-btn gw-btn--primary">Guardar cambios</button>
      </div>
      <div class="gw-modal__body">
      <div id="editModalNotice" role="alert" class="gw-alert gw-alert--warn" hidden></div>
      <form id="editModalForm">
        ${configuredHtml}
      </form>
      ${canManageStatus ? `
      <hr class="gw-registro__editsep">
      <div class="gw-field gw-registro__editfield">
        <label class="gw-label" for="editModalStatus">Estado de registro</label>
        <select id="editModalStatus" class="gw-select">
          <option value="no_registrado" ${defaultStatus === 'no_registrado' ? 'selected' : ''}>No registrado</option>
          <option value="registrado" ${defaultStatus === 'registrado' ? 'selected' : ''}>Registrado</option>
        </select>
        <p class="gw-hint">Se aplica junto con el resto de cambios al pulsar "Guardar cambios" — ya no hace falta un botón aparte.</p>
      </div>
      <details id="editModalHistory" class="gw-form-group">
        <summary class="gw-form-group__summary">Historial de cambios de esta persona</summary>
        <div id="editModalHistoryBody" class="gw-form-group__body gw-hint" aria-live="polite">Se carga al abrir.</div>
      </details>
      <button type="button" id="editModalDelete" class="gw-btn gw-btn--danger gw-btn--block"><svg class="gw-icon" aria-hidden="true"><use href="${iconUrl}#i-trash"/></svg>Eliminar de este evento</button>
      ` : ''}
      </div>
    `;
    overlay.appendChild(box);
    {                                                                   // Archivos subidos en un formulario (PDF, imágenes): se ven como archivo descargable, no como texto (digitador o superior, temporales incluidos; si no hay archivo, queda el texto)
      (async () => {
        try {
          const res = await fetch(`/api/events/${window.EVENT_ID}/users/${encodeURIComponent(user.id)}/form-files`);
          if (!res.ok) return;
          const d = await res.json();
          (d.items || []).forEach((it) => {
            const input = box.querySelector(`[name="${it.key}"]`);
            const row = input ? input.closest('.gw-registro__editfield') : null;
            if (!row) return;
            row.querySelectorAll('input, textarea, select').forEach((el) => el.remove());          // el archivo no se edita aquí: sin campo, no se vuelve a guardar como texto
            const a = document.createElement('a');
            a.className = 'gw-btn gw-btn--ghost gw-btn--sm';
            a.href = it.url;
            a.setAttribute('download', it.filename);
            a.textContent = `Descargar ${it.filename}`;
            const hint = document.createElement('p');
            hint.className = 'gw-hint';
            hint.textContent = 'Archivo subido por la persona en el formulario. Haz clic para descargarlo y revisarlo.';
            row.appendChild(a);
            row.appendChild(hint);
          });
        } catch (e) { /* sin archivos o sin permiso: se deja el campo como estaba */ }
      })();
    }
    {                                                                   // Fase 10 E: historial de datos modificados de la persona (coordinador o superior; se pide solo al desplegar)
      const det = box.querySelector('#editModalHistory');
      if (det) {
        let loaded = false;
        det.addEventListener('toggle', async () => {
          if (!det.open || loaded) return;
          const body = box.querySelector('#editModalHistoryBody');
          if (window.GW && GW.skeleton) GW.skeleton(body, { kind: 'list', rows: 3, label: 'Cargando el historial…' }); else body.textContent = 'Cargando…';
          try {
            const res = await fetch(`/api/events/${window.EVENT_ID}/users/${encodeURIComponent(user.id)}/change-history`);
            if (!res.ok) throw new Error('http ' + res.status);
            const d = await res.json();
            loaded = true;
            body.textContent = '';
            if (!d.items.length) { body.textContent = 'Esta persona no tiene datos modificados.'; return; }
            const ul = document.createElement('ul'); ul.className = 'gw-list';
            d.items.forEach((r) => {
              const li = document.createElement('li');
              li.textContent = `${r.at_local} · ${r.by} · ${r.label}: de ${r.old || '(vacío)'} pasó a ${r.new || '(vacío)'}`;
              ul.appendChild(li);
            });
            body.appendChild(ul);
          } catch (e) { body.textContent = 'No se pudo cargar el historial. Cierra y vuelve a abrir este grupo.'; showToast('No se pudo cargar el historial de la persona', 'error'); }
        });
      }
    }
    document.body.appendChild(overlay);
    const pfCtl = pfDef ? window.PersonForm.mount(box.querySelector('#editModalForm'), pfDef) : null;          // grupos, columnas, obligatorios y «Texto al escribir» del formulario de persona
    window.FieldRender.watchEmail(box, () => user.id);
    window.FieldRender.watchEmailDeliverable(box);
    window.FieldRender.initSignatures(box, {
      existingUrl: (key) => `/api/events/${window.EVENT_ID}/users/${encodeURIComponent(user.id)}/signature/${key}`,
    });

    function close() { overlay.remove(); }
    if (opts && opts.missing && opts.missing.length) {               // A3: llegó aquí porque falta un obligatorio: se dice cuál y el foco va al primero vacío
      const note = box.querySelector('#editModalNotice');
      note.textContent = `Falta el campo obligatorio: ${opts.missing.map((m) => m.label).join(', ')}. Complétalo y guarda: queda acreditado(a) en el mismo paso.`;
      note.hidden = false;
      const first = box.querySelector(`#editModalForm [name="${CSS.escape(opts.missing[0].key)}"]`);
      if (first) setTimeout(() => { first.scrollIntoView({ block: 'center' }); first.focus(); if (first.classList) first.classList.add('gw-registro__editmissing'); }, 60);
    }
    const snapshot = () => { const f = box.querySelector('#editModalForm'); return f ? JSON.stringify(Array.from(new FormData(f).entries()).filter(([, v]) => typeof v === 'string')) : ''; };
    const initialData = snapshot();
    // 2026-09-16 (Sprint 2.4 Fase 3, pedido explícito): ya NO se cierra al hacer clic afuera —
    // solo con "Cancelar" o guardando, para no perder cambios sin querer.
    box.querySelector('#editModalCancel').addEventListener('click', close);

    const saveHandler = async () => {
      const GCs = window.GoldenContingency && window.GoldenContingency.instance;
      if (GCs && GCs.active()) { showToast(OFFLINE_EDIT_NOTICE, 'error'); return; }          // se cortó la red con el modal abierto: aviso claro, no «Error de red»
      const form = box.querySelector('#editModalForm');
      if (pfCtl) pfCtl.applyAll();          // «Texto al escribir» también en lo que se llenó por lector o por foto de la cédula
      const dataChanged = snapshot() !== initialData || (opts && opts.missing && opts.missing.length);
      if (dataChanged && !form.reportValidity()) return;

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
        const ok = await showConfirm(`¿Cambiar la cédula de "${window.escapeHtml(user.id)}" a "${window.escapeHtml(newId)}"?<br><br>Esto afecta a esta persona en TODOS los eventos de este cliente, no solo en este.`, { variant: 'warning', confirmLabel: 'Sí, corregir y guardar' });
        if (!ok) return;
        saveBtn.disabled = true;
        try {
          const cedulaRes = await fetch(withEvent(`/api/users/${user.id}/cedula`), {
            method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ new_id: newId }),
          });
          if (!cedulaRes.ok) {
            const data = await cedulaRes.json().catch(() => ({}));
            showToast(data.detail || 'No se pudo cambiar la cédula', 'error');
            saveBtn.disabled = false;
            return;
          }
          currentId = newId;
        } catch (e) {
          showToast('Error de red', 'error');
          saveBtn.disabled = false;
          return;
        }
      }

      // Cambio de estado de registro (2026-09-17, pedido explícito: "que con el mismo botón de
      // guardar de todo el formulario también tome ese guardar" — antes tenía su propio botón
      // "Aplicar" aparte, ahora se aplica junto con el resto de campos en un solo Guardar). Solo
      // se llama al endpoint si el valor del select realmente cambió — evitar un PATCH de estado
      // sin sentido en cada guardado normal del perfil.
      async function applyStatus() {                // devuelve false si no se pudo (ya avisó)
      if (canManageStatus) {
        const statusSelect = box.querySelector('#editModalStatus');
        const newStatus = statusSelect ? statusSelect.value : originalStatus;
        if (newStatus !== originalStatus) {
          const label = newStatus === 'registrado' ? 'Registrado' : 'No registrado';
          // Pasar a "Registrado" (el valor por defecto de este modal) no pide confirmación: es
          // justo el flujo de "buscar, Editar, Guardar". Volver a "No registrado" sí la pide.
          const ok = newStatus === 'registrado' || await showConfirm(`¿Cambiar el estado de registro de esta persona a "${window.escapeHtml(label)}"? Se guardará junto con el resto de cambios.`, { variant: 'warning', confirmLabel: 'Sí, cambiar y guardar' });
          if (!ok) return false;
          saveBtn.disabled = true;
          try {
            const statusRes = await fetch(`/api/events/${window.EVENT_ID}/users/${currentId}/status`, {
              method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign({ status: newStatus, method: opts.method }, newStatus === 'registrado' && window.RegTimer ? RegTimer.payload() : null)),
            });
            if (!statusRes.ok) {
              const data = await statusRes.json().catch(() => ({}));
              const d = data.detail && typeof data.detail === 'object' ? data.detail.message : data.detail;
              showToast(d || 'No se pudo cambiar el estado', 'error');
              saveBtn.disabled = false;
              return false;
            }
            // Autoimpresión (2026-09-17, pedido explícito): "apenas cambia el estado a
            // registrado, si está autoimpresión activo entonces debe mandar a imprimir" — este es
            // uno de los puntos donde el estado puede pasar a "Registrado" sin pasar por un
            // escaneo (ver maybeAutoPrint en badge-render.js para el resto).
            if (newStatus === 'registrado' && window.RegTimer) RegTimer.done();
            if (newStatus === 'registrado' && window.BadgePrint) { const sd = await jsonOf(statusRes); applyFlags(sd); BadgePrint.maybeAutoPrint(currentId, { auto: sd.auto_print }); }
          } catch (e) {
            showToast('Error de red', 'error');
            saveBtn.disabled = false;
            return false;
          }
        }
      }
      return true;
      }

      const payload = { first_name: val('first_name'), last_name: val('last_name') };
      if (Object.prototype.hasOwnProperty.call(user, 'code')) payload.code = val('code');
      const newExtras = {};
      fieldConfigs.filter((cfg) => !cfg.locked).forEach((cfg) => {
        if (Object.prototype.hasOwnProperty.call(user, cfg.key)) payload[cfg.key] = val(cfg.key);
        else newExtras[cfg.key] = val(cfg.key);
      });
      payload.extra_fields = newExtras;
      if (fieldConfigs.some((cfg) => cfg.key === 'birth_date')) payload.birth_date = val('birth_date');
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

      saveBtn.disabled = true;
      try {
        const res = dataChanged ? await fetch(withEvent(`/api/users/${currentId}`), {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
        }) : { ok: true, clone: () => ({ json: async () => ({}) }) };          // solo cambió el estado: no se reenvían los datos (no los bloquea un obligatorio vacío)
        if (res.ok && !(await applyStatus())) return;                    // los datos quedaron guardados; el estado se aplica DESPUÉS (con su propio aviso si no se pudo)
        if (res.ok) {
          try {
            const info = await res.clone().json();
            if (info.digital) showToast(`Escarapela digital: ${info.digital.detail}`, 'success');
          } catch (e) { /* sin detalle de envío */ }
          try { await window.FieldRender.saveSignatures(box, currentId); }
          catch (e) { showToast(e.message, 'error'); }
          // Digitador (sin selector de estado): guardar la edición de alguien que aún no llegó lo deja
          // "Registrado", igual que el valor por defecto que ven coordinador+.
          if (!canManageStatus && !isRegistered) {
            try {
              const st = await fetch(`/api/events/${window.EVENT_ID}/users/${currentId}/status`, {
                method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign({ status: 'registrado', method: opts.method }, window.RegTimer ? RegTimer.payload() : null)),
              });
              if (st.ok) { if (window.RegTimer) RegTimer.done(); const sd = await jsonOf(st); applyFlags(sd); if (window.BadgePrint) BadgePrint.maybeAutoPrint(currentId, { auto: sd.auto_print }); }
              else { const ed = await st.json().catch(() => ({})); const dd = ed.detail && typeof ed.detail === 'object' ? ed.detail.message : ed.detail; showToast('Se guardaron los cambios, pero no se pudo marcar como Registrado' + (dd ? ': ' + dd : ''), 'error'); }
            } catch (e) { showToast('Se guardaron los cambios, pero no se pudo marcar como Registrado', 'error'); }
          }
          showToast('Cambios guardados', 'success');
          close();
          if (window.directorySearch) window.directorySearch.reload();
          Recent.add(currentId);
          if (opts.onSaved) opts.onSaved(currentId);
        } else {
          const data = await res.json().catch(() => ({}));
          showToast(data.detail || 'Error al guardar cambios', 'error');
          saveBtn.disabled = false;
        }
      } catch (e) {
        showToast('Error de red', 'error');
        saveBtn.disabled = false;
      }
    };
    box.querySelector('#editModalSave').addEventListener('click', async () => {
      // La ventana de impresión se abre AQUÍ, dentro del clic, solo si este guardado va a dejar a la persona «Registrada» (si no, no se abre nada).
      const GCw = window.GoldenContingency && window.GoldenContingency.instance;
      const statusSel = box.querySelector('#editModalStatus');
      const willRegister = canManageStatus ? !!(statusSel && statusSel.value === 'registrado' && originalStatus !== 'registrado') : !isRegistered;
      if (willRegister && !(GCw && GCw.active())) primePrint();
      try { await busyBtn(box.querySelector('#editModalSave'), saveHandler); } finally { cancelPrimedPrint(); }
    });

    if (canManageStatus) {
      box.querySelector('#editModalDelete').addEventListener('click', () => deletePerson(user, close));
    }
  }

  /* Botón de acción de una fila: ícono del sprite + texto corto (en pantallas muy estrechas el CSS deja solo el ícono; el nombre accesible y el tooltip siguen). Sin DOM de SVG (pruebas), queda el texto. */
  function actBtn(label, icon, cls, title, aria) {
    const b = document.createElement('button'); b.type = 'button'; b.className = cls; b.innerText = label;
    if (title) b.title = title;
    if (aria) b.setAttribute('aria-label', aria);
    if (icon && document.createElementNS) {
      const NS = 'http://www.w3.org/2000/svg', s = document.createElementNS(NS, 'svg'), u = document.createElementNS(NS, 'use'), tx = document.createElement('span');
      s.setAttribute('class', 'gw-icon'); s.setAttribute('aria-hidden', 'true'); u.setAttribute('href', (window.GW_ICON_URL || '/static/img/icons.svg') + '#i-' + icon); s.appendChild(u);
      tx.className = 'gw-act__t'; tx.textContent = label;
      b.textContent = ''; b.appendChild(s); b.appendChild(tx);
    }
    return b;
  }

  /* Menú «Más» de una fila (Plan 8): botón + panel con las acciones secundarias. Se cierra con Esc, al elegir o al hacer clic afuera; si no cabe abajo, se abre hacia arriba. */
  let openMenu = null, menuWired = false;
  function closeMenu() { if (openMenu) { openMenu.panel.hidden = true; openMenu.btn.setAttribute('aria-expanded', 'false'); openMenu = null; } }
  function wireMenuClose() {
    if (menuWired || typeof document.addEventListener !== 'function') return;
    menuWired = true;
    document.addEventListener('click', (e) => { if (openMenu && !(e.target && e.target.closest && e.target.closest('.gw-menu'))) closeMenu(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && openMenu) { const b = openMenu.btn; closeMenu(); if (b.focus) b.focus(); } });
  }
  function buildMoreMenu(items, who) {
    wireMenuClose();
    const wrap = document.createElement('div'); wrap.className = 'gw-menu';
    const btn = actBtn('Más', 'more', 'gw-btn gw-btn--secondary btn-table-action gw-menu__btn gw-menu__btn--kebab', 'Más opciones', 'Más acciones' + (who ? ' de ' + who : ''));          // tres puntos (ícono `more` del sprite); el texto «Más» queda solo para lectores de pantalla
    btn.setAttribute('aria-haspopup', 'true'); btn.setAttribute('aria-expanded', 'false');
    const panel = document.createElement('div'); panel.className = 'gw-menu__panel'; panel.hidden = true; panel.setAttribute('role', 'group');
    items.forEach((it) => {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'gw-menu__item' + (it.danger ? ' gw-menu__item--danger' : ''); b.innerText = it.label;
      b.addEventListener('click', () => { closeMenu(); it.run(); });
      panel.appendChild(b);
    });
    panel.addEventListener('keydown', (e) => {          // flechas arriba/abajo entre las opciones (Esc lo atiende el documento)
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
      const list = Array.prototype.slice.call(panel.children || []), at = list.indexOf(document.activeElement);
      const next = list[(at + (e.key === 'ArrowDown' ? 1 : list.length - 1)) % list.length];
      if (next && next.focus) { if (e.preventDefault) e.preventDefault(); next.focus(); }
    });
    btn.addEventListener('click', (e) => {
      if (e.stopPropagation) e.stopPropagation();
      const wasOpen = openMenu && openMenu.panel === panel; closeMenu();
      if (wasOpen) return;
      panel.hidden = false; btn.setAttribute('aria-expanded', 'true'); openMenu = { panel, btn };
      const box = wrap.closest && wrap.closest('.gw-workarea__list'), r = btn.getBoundingClientRect ? btn.getBoundingClientRect() : null, lim = box && box.getBoundingClientRect ? box.getBoundingClientRect() : null;
      wrap.className = r && lim && r.bottom + panel.offsetHeight > lim.bottom && r.top - panel.offsetHeight > lim.top ? 'gw-menu gw-menu--up' : 'gw-menu';
      const first = panel.firstChild; if (first && first.focus) first.focus();
    });
    wrap.appendChild(btn); wrap.appendChild(panel);
    return wrap;
  }

  function pollSignal(ok) { try { window.dispatchEvent(new CustomEvent('gw:poll', { detail: { ok: !!ok } })); } catch (e) { /* sin ventana de eventos (pruebas): nada */ } }          // la pantalla muestra «Sin conexión» si el último sondeo falló
  let rowAccredit = null;          // lo fija mountSearch cuando quien mira puede acreditar (digitador o más): botón «Acreditar» en TODAS las filas
  /* La cédula se MUESTRA sin ceros a la izquierda («0000349220» -> «349220»); el valor guardado y el que se usa para buscar o editar no cambian. Un documento con letras no se toca. */
  function shownId(v) { const t = String(v == null ? '' : v); return /^\d+$/.test(t) ? t.replace(/^0+(?=\d)/, '') : t; }
  function buildRow(user) {
    const tr = document.createElement('tr');
    tr.className = user.status === 'No registrado' ? 'row-noregistrado' : 'row-registrado';        // B1: el color sigue el ESTADO (el alta manual ya no es otro color: es un origen)
    tr.dataset.userId = user.id;
    if (user.__h) tr.dataset.h = user.__h;          // fila de la lista local (sin cédula)
    if (isRecentRow(user, null)) tr.dataset.recent = '1';          // el resaltado y la insignia los pone drawRows (relativos a la lista)

    /* La columna de Acción va PRIMERO (2026-09-16, pedido explícito: antes al final, obligaba a
       desplazarse hasta el final de la fila para editar/imprimir). El resto de columnas
       (ID/Nombres/Apellidos/Tipo Asistente/Estado) siguen en el mismo orden de siempre. */
    const actionTd = document.createElement('td');
    actionTd.className = 'action-cell';

    /* «Acreditar» en CADA fila (docs/16, 7a): un clic acredita, con «Deshacer» ~8 s (el servidor lo permite solo a quien acreditó y hasta 15 s). La fila ya acreditada muestra «Acreditado» sin acción. */
    if (rowAccredit) {
      const done = user.status === 'Registrado' || user.status === 'Nuevo';
      const acc = actBtn(done ? 'Acreditado' : 'Acreditar', 'check', 'gw-btn ' + (done ? 'gw-btn--secondary' : 'gw-btn--primary') + ' gw-btn--xl btn-table-action btn-accredit-row' + (done ? ' is-done' : ''), done ? 'Ya acreditado' : 'Acreditar a esta persona', (done ? 'Ya acreditado: ' : 'Acreditar a ') + ([user.first_name, user.last_name].filter(Boolean).join(' ') || 'la persona'));
      acc.disabled = done;
      if (!done) acc.addEventListener('click', () => rowAccredit(user, acc));
      actionTd.appendChild(acc);
    }

    /* Regla de frecuencia (Plan 8, corrección): lo que se hace con CADA persona va a la vista en una sola línea: [Acreditar] [Imprimir] [Editar]. «Más» queda solo para lo raro y
       destructivo (eliminar, con confirmación). Imprimir: cliente es de solo lectura y 'comercial' no imprime (el backend ya lo bloquea con require_role_excluding en badges.py);
       la lista local (sin red) no tiene la cédula, así que tampoco imprime. */
    const PRINT_HIDDEN_ROLES = ['cliente', 'comercial'];
    const who = [user.first_name, user.last_name].filter(Boolean).join(' ');
    if (!PRINT_HIDDEN_ROLES.includes(window.STAFF_ROLE) && !user.__local) {
      const printBtn = actBtn('Imprimir', 'printer', 'gw-btn gw-btn--secondary gw-btn--xl btn-table-action', 'Imprimir escarapela', 'Imprimir escarapela' + (who ? ' de ' + who : ''));
      printBtn.addEventListener('click', () => { if (window.BadgePrint) BadgePrint.openPrintWindow(user.id); });
      actionTd.appendChild(printBtn);
    }
    if (canEdit) {
      const editBtn = actBtn('Editar', 'edit', 'gw-btn gw-btn--secondary btn-table-action', 'Editar persona', 'Editar a ' + (who || 'la persona'));
      editBtn.addEventListener('click', () => buildEditModal(user));
      actionTd.appendChild(editBtn);
      if (!user.__local && canManageStatus) actionTd.appendChild(buildMoreMenu([{ label: 'Eliminar de este evento', danger: true, run: () => deletePerson(user) }], who));          // eliminar es de coordinador en adelante: el digitador (temporal o no) no ve ni «Más»
    }

    tr.appendChild(actionTd);

    FIELDS_ORDER.forEach(field => {
      const td = document.createElement('td');
      td.dataset.field = field;                     // el modo «Registro touch» arma la tarjeta de dos filas con estas marcas (static/js/shared-print.js)
      td.innerText = field === 'id' ? shownId(user[field]) : (user[field] || '');
      tr.appendChild(td);
    });

    const statusTd = document.createElement('td');
    statusTd.dataset.field = 'status';
    statusTd.innerText = user.status === 'No registrado' ? 'No registrado' : 'Registrado';
    statusTd.className = 'gw-registro__status';
    tr.appendChild(statusTd);
    const entityTd = document.createElement('td');   // la empresa: va AL FINAL (las columnas de siempre no se corren) y solo se ve en la tarjeta del modo touch (en la tabla de escritorio no hay columna para ella)
    entityTd.dataset.field = 'entity';
    entityTd.className = 'touch-only';
    entityTd.innerText = user.entity || '';
    tr.appendChild(entityTd);

    /* Casillas propias de la tarjeta (cada una es una pieza suelta, sin insignias anidadas dentro de otra): origen de carga (B1: aparte del estado, no cambia al registrar o quitar el registro),
       «Recién registrado/creado» (la pone drawRows junto al nombre) y el motivo de la búsqueda unificada (drawRows). Vacías no se ven. */
    const og = ORIGINS[user.origin];
    const originTd = document.createElement('td'); originTd.dataset.field = 'origin';
    if (og && user.origin !== 'desconocido') {
      const tag = document.createElement('span');
      tag.className = 'gw-origin'; tag.dataset.origin = user.origin; tag.textContent = og.label; tag.title = 'Origen de carga: ' + og.label;
      originTd.appendChild(tag);
    }
    tr.appendChild(originTd);
    ['recent', 'reason'].forEach((slot) => { const td = document.createElement('td'); td.dataset.field = slot; tr.appendChild(td); });

    return tr;
  }

  /* Casilla de la tarjeta por su marca (`recent`, `reason`); en las pruebas con DOM falso se busca entre los hijos. */
  function slotOf(tr, name) {
    const q = tr.querySelector && tr.querySelector('td[data-field="' + name + '"]');
    return q || Array.prototype.find.call(tr.children || [], (c) => c.dataset && c.dataset.field === name) || null;
  }

  function renderRows(tbodyId, users) {
    const tbody = document.getElementById(tbodyId);
    tbody.innerHTML = '';
    if (users.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="gw-registro__empty">Sin resultados con esa búsqueda.</td></tr>';
      return;
    }
    users.forEach(user => tbody.appendChild(buildRow(user)));
  }

  // Mientras llega la lista: filas esqueleto con las columnas de la tabla (static/js/gw-carga.js); sin él, la fila de texto de siempre.
  function loadingRows(tbody) {
    if (window.GW && window.GW.skeleton) window.GW.skeleton(tbody, { kind: 'table', rows: 8, label: 'Cargando la lista de personas…' });
    else tbody.innerHTML = '<tr><td colspan="6" class="gw-registro__empty" role="status">Cargando la lista de personas…</td></tr>';
  }

  async function loadRows(tbodyId) {
    const tbody = document.getElementById(tbodyId);
    loadingRows(tbody);
    try {
      const res = await fetch(withEvent('/api/users'));
      const users = await res.json();
      renderRows(tbodyId, users);
      return users;
    } catch (err) {
      tbody.innerHTML = '<tr><td colspan="6" class="gw-registro__empty gw-registro__empty--err" role="alert">No se pudo conectar con el servidor. Revisa la red e inténtalo de nuevo.</td></tr>';
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
    const SC = window.SearchCore;
    const unified = !!(opts.unified && cedulaInput && SC);            // buscador único: una sola caja (cédula, nombre o empresa) con SearchCore
    const hintEl = unified ? document.getElementById('gwSearchHint') : null;
    const reasons = new WeakMap();                                    // persona -> motivo de la coincidencia (solo con consulta activa)
    let activeQuery = false;

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
    let originSelect = null;
    if (tableEl && tableEl.parentNode) {
      const summaryHost = document.getElementById('gwDirSummary');            // Plan 8: los contadores y el filtro viven en la franja fija de arriba (si la página la trae)
      const place = (el) => {
        if (summaryHost) { const ref = document.getElementById('clearFiltersBtn'); summaryHost.insertBefore(el, ref && ref.parentNode === summaryHost ? ref : null); return; }
        const anchor = (tableEl.closest && tableEl.closest('.gw-reg__list')) || tableEl; anchor.parentNode.insertBefore(el, anchor);
      };
      counterBtn = document.createElement('button');
      counterBtn.type = 'button';
      counterBtn.className = 'not-registered-counter gw-chip gw-chip--err';
      counterBtn.setAttribute('aria-pressed', 'false');
      counterBtn.addEventListener('click', () => {
        onlyNotRegistered = !onlyNotRegistered;
        counterBtn.setAttribute('aria-pressed', onlyNotRegistered ? 'true' : 'false');
        applyFilters();
      });
      place(counterBtn);

      totalCounterEl = document.createElement('span');
      totalCounterEl.className = 'total-registered-counter gw-chip gw-chip--ok';
      place(totalCounterEl);
      originSelect = document.createElement('select');                 // B1: filtro por origen de carga
      originSelect.className = 'origin-filter gw-chip';
      originSelect.setAttribute('aria-label', 'Filtrar por origen de carga');
      originSelect.innerHTML = '<option value="">Origen: todos</option>' + Object.keys(ORIGINS).map((k) => `<option value="${k}">${ORIGINS[k].label}</option>`).join('');
      originSelect.addEventListener('change', () => { pageIdx = 0; applyFilters(); });
      place(originSelect);
      if (summaryHost && !document.getElementById('gwSummaryMore')) {            // celular: origen y «Limpiar filtros» quedan plegados tras este chip para que los contadores ocupen UNA fila (en escritorio el CSS lo oculta)
        const more = document.createElement('button');
        more.type = 'button'; more.id = 'gwSummaryMore'; more.className = 'gw-chip gw-summary__more'; more.textContent = 'Filtros';
        more.setAttribute('aria-expanded', 'false'); more.setAttribute('aria-controls', 'gwDirSummary');
        more.addEventListener('click', () => { const open = summaryHost.classList.toggle('is-open'); more.setAttribute('aria-expanded', open ? 'true' : 'false'); });
        summaryHost.appendChild(more);
      }
    }

    function updateCounterLabel() {
      if (!counterBtn) return;
      const real = allUsers.filter(u => !u.test);                     // la persona de prueba del evento no cuenta en los contadores
      const origin = originSelect && originSelect.value;
      const scoped = origin ? real.filter(u => (u.origin || 'desconocido') === origin) : real;          // las cifras siguen el filtro de origen (no la búsqueda)
      const total = scoped.length;
      const count = scoped.filter(u => u.status === 'No registrado').length;
      const registered = total - count;
      counterBtn.innerText = `${count} sin registrar` + (onlyNotRegistered ? ' (filtrando)' : '');
      counterBtn.hidden = count === 0 && !onlyNotRegistered;
      const scope = origin && ORIGINS[origin] ? ORIGINS[origin].label : 'Total';
      if (totalCounterEl) totalCounterEl.innerText = `${scope}: ${registered} registrados de ${total}`;
    }

    /* Buscador rápido (antes, cada tecla re-normalizaba a TODAS las personas y redibujaba TODAS las filas: 180-230 ms por tecla con
       3.000 personas, con el campo de texto congelado mientras tanto):
       - lo que se compara (cédula en minúsculas, palabras del nombre y de la entidad sin tildes) se calcula UNA vez por persona;
       - las filas ya construidas se reutilizan (una por persona; si el servidor manda una versión nueva, es otro objeto y se reconstruye);
       - se dibuja UNA página de `pageSize()` filas (parámetro del evento: 10, 20, 50, 100 o 200), con «Anterior / Siguiente» e «Ir a la página» para llegar a cualquier fila;
       - al escribir se espera SEARCH_DELAY_MS después de la última tecla antes de filtrar (la letra aparece al instante). */
    const PAGE_SIZES = [10, 20, 50, 100, 200];
    /* Filas por página (6-nov-2026): 20 por defecto y cada computador elige las suyas con el selector del pie de la tabla (static/js/gw-pager.js); ya no es un parámetro del evento. */
    const pageSize = () => (window.GW && window.GW.pageSize ? window.GW.pageSize('registro') : (() => { const v = Number(opts.pageSize || window.DIRECTORY_PAGE_SIZE); return PAGE_SIZES.includes(v) ? v : 200; })());          // sin gw-pager.js (páginas viejas): como antes
    const SEARCH_DELAY_MS = 250;
    const searchKeys = new WeakMap();
    const rowCache = new WeakMap();
    let pageIdx = 0;
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

    /* CAUSA REAL del «me quedo atrapado al deslizar sobre las personas» (celular): el sondeo (pollRefresh, cada pocos segundos) trae cambios de otros equipos y drawRows() hacía
       tbody.replaceChildren(...) — QUITA y vuelve a poner las filas mientras el dedo está sobre una. El navegador cancela el gesto (touchcancel) cuando el elemento tocado sale del
       documento: el dedo deja de desplazar la página y solo queda el clic; fuera de las filas sí desliza. Arreglo: no se redibuja la lista mientras hay un dedo abajo o la página
       acaba de moverse; se redibuja al soltar (una sola vez), y si las filas son las mismas, en el mismo orden, no se toca el DOM. Lo fija tests/test_registro_visual.py. */
    let touching = false, lastScrollAt = 0, deferredDraw = null;
    const gestureBusy = () => touching || (Date.now() - lastScrollAt < 400);
    const redrawSoon = () => { if (deferredDraw) return; deferredDraw = setTimeout(() => { deferredDraw = null; drawRows(); }, 450); };
    if (typeof document !== 'undefined' && document.addEventListener) {
      document.addEventListener('touchstart', () => { touching = true; }, { passive: true });
      document.addEventListener('touchend', () => { touching = false; }, { passive: true });
      document.addEventListener('touchcancel', () => { touching = false; }, { passive: true });
      if (typeof window !== 'undefined' && window.addEventListener) window.addEventListener('scroll', () => { lastScrollAt = Date.now(); }, { passive: true });
    }

    function drawRows() {
      if (gestureBusy()) { redrawSoon(); return; }
      const tbody = document.getElementById(opts.tbodyId);
      // El «Acreditar» puntual (FOUND_PENDING) vive en una fila reutilizada: como antes, se va al volver a dibujar.
      tbody.querySelectorAll('.btn-accredit-pending').forEach(b => b.remove());
      if (!lastFiltered.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="gw-registro__empty">Sin resultados con esa búsqueda.</td></tr>';
        if (localMode) tbody.insertBefore(localNoteRow(), tbody.children[0] || null);
        return;
      }
      const size = pageSize(), total = lastFiltered.length, pages = Math.max(1, Math.ceil(total / size));
      if (pageIdx > pages - 1) pageIdx = pages - 1;                    // un filtro o un refresco dejó la página fuera de rango
      const rows = lastFiltered.slice(pageIdx * size, (pageIdx + 1) * size).map(rowOf);
      const newest = newestRecentMs(allUsers);
      lastFiltered.slice(pageIdx * size, (pageIdx + 1) * size).forEach((u, i) => {          // resaltado + insignia «Recién registrado» (se quitan las previas: las filas están en caché)
        const tr = rows[i];
        if (!tr || !tr.querySelectorAll) return;
        tr.querySelectorAll('.gw-recent-tag').forEach((n) => n.remove());
        if (!isRecentRow(u, newest)) { delete tr.dataset.recent; return; }
        tr.dataset.recent = '1';
        const td = slotOf(tr, 'recent');
        if (!td) return;
        const b = document.createElement('span');
        const created = u.origin === 'manual';                         // alta manual («Registrar nuevo»): «Recién creado» (azul); acreditar a alguien de la base: «Recién registrado» (verde)
        b.className = created ? 'gw-badge gw-recent-tag gw-recent-tag--new' : 'gw-badge gw-recent-tag';
        b.textContent = created ? 'Recién creado' : 'Recién registrado';
        td.appendChild(b);
      });
      if (unified) {                                                   // el motivo vive en la fila en caché: se quita el anterior y se pone el actual (no se duplican filas)
        lastFiltered.slice(pageIdx * size, (pageIdx + 1) * size).forEach((u, i) => {
          const tr = rows[i];
          if (!tr || !tr.querySelectorAll) return;
          tr.querySelectorAll('.gw-reason').forEach((n) => n.remove());
          const motivo = activeQuery ? reasons.get(u) : '';
          if (!motivo) return;
          const td = slotOf(tr, 'reason');
          if (!td) return;
          const b = document.createElement('span');
          b.className = 'gw-badge gw-badge--info gw-reason gw-registro__reason';
          b.textContent = motivo;
          td.appendChild(b);
        });
      }
      if (localMode) rows.unshift(localNoteRow());
      if (total > PAGE_SIZES[0]) rows.push(pagerRow(total, size, pages));          // con 10 filas o menos no hay nada que paginar ni elegir
      const same = tbody.children.length === rows.length && rows.every((r, i) => tbody.children[i] === r);
      if (!same) tbody.replaceChildren(...rows);
    }

    function goToPage(i, pages) { pageIdx = Math.max(0, Math.min(i, pages - 1)); drawRows(); }
    function pagerRow(total, size, pages) {
      const tr = document.createElement('tr');
      tr.className = 'directory-more';
      const td = document.createElement('td');
      td.colSpan = 6;
      td.className = 'gw-registro__pager';
      td.innerText = `Mostrando ${pageIdx * size + 1}-${Math.min(total, (pageIdx + 1) * size)} de ${total} · Página ${pageIdx + 1} de ${pages}. `;
      const btn = (label, onClick, disabled) => {
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'gw-btn gw-btn--secondary gw-btn--sm btn-table-action'; b.innerText = label; b.disabled = !!disabled;
        b.addEventListener('click', onClick); td.appendChild(b); return b;
      };
      btn('‹ Anterior', () => goToPage(pageIdx - 1, pages), pageIdx === 0);
      btn('Siguiente ›', () => goToPage(pageIdx + 1, pages), pageIdx >= pages - 1);
      const input = document.createElement('input');
      input.type = 'number'; input.min = '1'; input.max = String(pages); input.placeholder = 'Ir a la página'; input.setAttribute('aria-label', 'Ir a la página');
      input.className = 'gw-input gw-registro__goto';
      td.appendChild(input);
      btn('Ir', () => { const n = parseInt(input.value, 10); if (n >= 1) goToPage(n - 1, pages); }, false);
      if (window.GW && window.GW.pageSizeSelect) td.appendChild(window.GW.pageSizeSelect('registro', () => { pageIdx = 0; drawRows(); }));
      tr.appendChild(td);
      return tr;
    }

    function setHint(text) { if (hintEl) hintEl.textContent = text; }
    function applyUnified() {
      syncClearBtn();
      const q = SC.classifyQuery(cedulaInput.value || '');
      const base = allUsers.filter((u) => {
        if (onlyNotRegistered && u.status !== 'No registrado') return false;
        if (originSelect && originSelect.value && (u.origin || 'desconocido') !== originSelect.value) return false;
        return true;
      });
      activeQuery = q.kind !== 'vacio';
      if (!activeQuery) {
        lastFiltered = orderByRecency(base);
        setHint(localMode ? 'Sin red: se busca por nombre y por cédula completa. Ves lo que registra este equipo; lo de los demás llega al reconectar.' : '');
      } else {
        const sopts = {};
        if (localMode && q.cedula && q.completa) {                    // lista local: la cédula se compara por huella (exacta); nunca se guarda en claro
          const h = localHashes.get(q.cedula);
          if (h !== undefined) sopts.hash = h;
          else { const GC = GCref(); if (GC) { const job = GC.hashFor(q.cedula).then((hh) => { localHashes.set(q.cedula, hh); applyFilters(); }).finally(() => inflightHashes.delete(job)); inflightHashes.add(job); } }
        }
        const res = SC.search(base, q, sopts);
        lastFiltered = res.map((r) => { reasons.set(r.persona, r.motivo); return r.persona; });
        setHint(res.length ? `${res.length} ${res.length === 1 ? 'coincidencia' : 'coincidencias'}` : 'Sin coincidencias. Revisa la cédula o prueba con el nombre.');
      }
      updateCounterLabel();
      drawRows();
    }

    function applyFilters() {
      clearTimeout(searchTimer);
      if (unified) return applyUnified();
      const cedula = (cedulaInput && cedulaInput.value || '').trim().toLowerCase();
      const nombre = wordsOf((nombreInput && nombreInput.value || '').trim());
      const entidad = wordsOf((entidadInput && entidadInput.value || '').trim());
      let wantH = '';
      if (localMode && cedula) {                          // lista local: la cédula se compara por huella (exacta); se calcula una vez y se vuelve a filtrar
        wantH = localHashes.get(cedula);
        if (wantH === undefined) {
          wantH = ''; const GC = GCref();
          if (GC) { const job = GC.hashFor(cedula).then((h) => { localHashes.set(cedula, h); applyFilters(); }).finally(() => inflightHashes.delete(job)); inflightHashes.add(job); }       // el cálculo de la huella es asíncrono: al terminar se vuelve a filtrar
        }
      }
      lastFiltered = allUsers.filter(u => {
        if (onlyNotRegistered && u.status !== 'No registrado') return false;
        if (originSelect && originSelect.value && (u.origin || 'desconocido') !== originSelect.value) return false;
        if (!cedula && !nombre.length && !entidad.length) return true;
        const k = keysOf(u);
        if (cedula && !(u.__local ? (wantH && u.__h === wantH) : k.id.includes(cedula))) return false;
        if (nombre.length && !matchesWords(k.name, nombre)) return false;
        if (entidad.length && !matchesWords(k.entity, entidad)) return false;
        return true;
      });
      if (!cedula && !nombre.length && !entidad.length) lastFiltered = orderByRecency(lastFiltered);          // sin consulta: la cola de recién registrados primero
      updateCounterLabel();
      drawRows();
    }

    /* Vacía la caja de búsqueda y vuelve a mostrar la lista completa; el foco queda en la caja para la siguiente persona. Lo usan acreditar y el botón de la papelera. */
    function clearSearchBox() {
      if (!cedulaInput) return;
      cedulaInput.value = '';
      if (!unified) { if (nombreInput) nombreInput.value = ''; if (entidadInput) entidadInput.value = ''; }
      pageIdx = 0;
      applyFilters();
      syncClearBtn();
      if (!cedulaInput.disabled) { try { cedulaInput.focus(); } catch (_) { /* sin foco en pruebas */ } }
    }
    const clearBtn = unified ? document.getElementById('searchClearBtn') : null;           // la papelera junto a la caja (solo con el buscador único)
    function syncClearBtn() { if (clearBtn) clearBtn.hidden = !(cedulaInput && cedulaInput.value); }
    if (clearBtn) clearBtn.addEventListener('click', clearSearchBox);

    function onSearchInput() {
      syncClearBtn();
      clearTimeout(searchTimer);
      pageIdx = 0;
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
    const inflightHashes = new Set();                    // huellas que se están calculando (crypto.subtle usa hilos reales): `hashesSettled()` espera a que terminen, sin depender del tiempo
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
      const st = GC.serverTotal ? await GC.serverTotal() : null, meta = GC.rosterMeta ? await GC.rosterMeta() : null;
      localStats = { n: people.length, total: st ? st.n : null, at: st ? st.at : null, generated: meta && meta.generated_at ? Date.parse(meta.generated_at) : null };
      setLocalMode(true);
      allUsers = people.map((p) => ({ id: '', first_name: p.n, last_name: '', entity: '', opt_1: (p.c || []).join(', '), status: p.s, categories: p.c || [], __h: p.h, __local: true }));
      applyFilters();
      return true;
    }
    /* «LISTA LOCAL: N de N»: N = personas de la copia local; el segundo número es el total que el servidor informó la última vez que la lista en vivo se cargó en este dispositivo (se guarda en la copia).
       Si no coinciden, o el servidor nunca informó, se avisa con claridad (nunca se muestra una lista recortada o vieja como si fuera la completa). */
    let localStats = null;
    const hhmm = (ms) => { const d = new Date(ms); return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; };
    function localCounterText() {
      const s = localStats;
      if (!s) return 'LISTA LOCAL';
      const ago = s.generated ? ` · copia de hace ${Math.max(0, Math.round((Date.now() - s.generated) / 60000))} min` : '';
      if (s.total == null) return `LISTA LOCAL: ${s.n} de ? — el servidor aún no informó su total en este dispositivo${ago}`;
      if (s.total === s.n) return `LISTA LOCAL: ${s.n} de ${s.total}${ago}`;
      const diff = s.total > s.n ? `faltan ${s.total - s.n}` : `sobran ${s.n - s.total}`;
      return `LISTA LOCAL: ${s.n} de ${s.total} — NO COINCIDE (el servidor tenía ${s.total} a las ${hhmm(s.at)}; ${diff} en esta copia). Actualiza con conexión antes de confiar en ella${ago}`;
    }
    function localNoteRow() {
      const tr = document.createElement('tr'); tr.className = 'directory-local-note';
      const td = document.createElement('td'); td.colSpan = 6;
      const s = localStats, bad = !s || s.total == null || s.total !== s.n;
      td.className = 'gw-registro__localnote ' + (!s || s.total == null ? 'is-warn' : (bad ? 'is-err' : 'is-ok'));
      td.innerText = `${localCounterText()}. Sin conexión: se muestra la copia local (nombre, categorías y estado). La cédula, la entidad y demás datos no están en esta copia: busca por nombre o escribe la cédula exacta.`;
      tr.appendChild(td);
      return tr;
    }

    const T = (n, x) => { if (window.GoldenTrace) window.GoldenTrace.mark(n, x); };          // marcas de arranque (static/js/boot-trace.js)
    async function fullLoad() {
      T('directory:fullLoad:begin');
      const tbody = document.getElementById(opts.tbodyId);
      const GC0 = GCref();
      if (GC0) { await GC0.ready; if (GC0.active() && await loadFromLocalCopy()) return; }          // ya en contingencia: ni se intenta la red
      if (localMode) { setLocalMode(false); allUsers = []; }
      if (!allUsers.length) loadingRows(tbody);
      T('directory:loading-row-shown');
      try {
        // El cursor se toma ANTES de leer las páginas: lo que cambie mientras tanto llega en el siguiente incremental.
        const head = await fetch(withEvent('/api/users/changes?cursor=' + NOW_CURSOR));
        if (!head.ok) throw new Error(head.status);
        const headBody = await head.json();
        applyFlags(headBody.flags);
        const nextCursor = headBody.cursor;
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
        pollSignal(true);
        { const GCt = GCref(); if (GCt && GCt.noteServerTotal) GCt.noteServerTotal(allUsers.length); }          // total del servidor: lo usa el contador «LISTA LOCAL: N de N»
      } catch (err) {
        T('directory:fetch-failed', { error: String((err && err.name) || err) });
        pollSignal(false);
        if (await loadFromLocalCopy()) { T('directory:local-list-shown'); return; }           // sin red: la lista local en vez de «Error conectando al servidor»
        tbody.innerHTML = '<tr><td colspan="6" class="gw-registro__empty gw-registro__empty--err" role="alert">No se pudo conectar con el servidor. Revisa la red e inténtalo de nuevo.</td></tr>';
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
        pollSignal(true);
        applyFlags(delta.flags);
        cursor = delta.cursor;
        { const GCt = GCref(); if (GCt && GCt.noteServerTotal && Number.isInteger(delta.total)) GCt.noteServerTotal(delta.total); }
        if (delta.users.length) {
          const byId = new Map(allUsers.map(u => [u.id, u]));
          delta.users.forEach(u => { const old = byId.get(u.id); if (old && u.recent_at === undefined && old.recent_at !== undefined) u.recent_at = old.recent_at; byId.set(u.id, u); });          // merge por id: recent_at nuevo manda
          allUsers = [...byId.values()];
        }
        if (allUsers.length !== delta.total) return reload();
        if (delta.users.length) applyFilters();
      } catch (err) { pollSignal(false); /* sin red: se reintenta en el siguiente ciclo */ }
    }

    function reload() {
      if (loading) T('directory:reload-joined-in-flight');          // ya hay una carga en curso: esta llamada espera a ESA (si está colgada en una petición, espera con ella)
      if (!loading) loading = fullLoad().finally(() => { loading = null; checkIncomplete(); });
      return loading;
    }
    /* A3 (26-oct-2026): registradas a las que les falta un obligatorio (acreditadas sin conexión, o el campo se volvió obligatorio después): aviso con la lista «falta completar». */
    let incompleteAt = 0, incompleteBar = null;
    async function checkIncomplete(force) {
      if (!opts.fastCheckin || localMode || (!force && Date.now() - incompleteAt < 20000)) return;
      incompleteAt = Date.now();
      let data = null;
      try { const r = await fetch(`/api/events/${window.EVENT_ID}/incomplete-registrations`, { cache: 'no-store' }); data = r.ok ? await r.json() : null; } catch (e) { data = null; }
      if (!data) return;
      const table = document.getElementById(opts.tbodyId);
      if (!incompleteBar && table) {
        incompleteBar = document.createElement('div');
        incompleteBar.setAttribute('role', 'status');
        incompleteBar.className = 'gw-alert gw-alert--warn gw-registro__incomplete'; incompleteBar.hidden = true;
        const host = table.closest('table') || table;
        host.parentNode.insertBefore(incompleteBar, host);
        incompleteBar.addEventListener('click', async (e) => {
          const b = e.target.closest('[data-complete]');
          if (b) { const id = b.dataset.complete; const p = (incompleteBar.__people || []).find((x) => x.id === id); const person = allUsers.find((u) => u.id === id) || p; if (person) buildEditModal(person, { missing: p ? p.missing : [], onSaved: () => checkIncomplete(true) }); return; }
          if (e.target.closest('[data-toggle]')) { const l = incompleteBar.querySelector('[data-list]'); l.hidden = !l.hidden; }
        });
      }
      if (!incompleteBar) return;
      incompleteBar.__people = data.people;
      incompleteBar.hidden = !data.count;
      if (!data.count) return;
      const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
      incompleteBar.innerHTML = `<div class="gw-registro__grow"><b>${data.count} persona(s) registradas con datos obligatorios por completar.</b> <button type="button" data-toggle class="gw-btn gw-btn--secondary gw-btn--sm">Ver lista</button>
        <div data-list hidden class="gw-registro__incomplete-list">${data.people.map((p) => `<div class="gw-rowact"><span class="gw-registro__grow">${esc(p.first_name)} ${esc(p.last_name)} — falta: ${esc(p.missing.map((m) => m.label).join(', '))}</span><button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-complete="${esc(p.id)}">Completar</button></div>`).join('')}</div></div>`;
    }

    {
      const GC = GCref();
      if (GC && GC.onSynced) GC.onSynced(() => { if (!localMode) reload(); });          // la cola ya está en el servidor: la lista y los contadores al día
      if (GC && GC.onChange) GC.onChange((st) => { if (st === 'normal' && localMode) reload(); else if (st === 'contingency' && !allUsers.length) reload(); });      // vuelve la red: la lista del servidor
    }

    const pollRefresh = () => { if (document.visibilityState === 'visible' && tbodyEl && tbodyEl.offsetParent !== null) refresh(); };
    if (window.GW && window.GW.poll) window.GW.poll(pollRefresh, POLL_MS); else setInterval(pollRefresh, POLL_MS);      // sin uso 60 s no consulta la base (toast.js, GW.idle); al volver se pone al día enseguida
    // Con la pestaña oculta no se consulta (no gasta la base); al volver a ella se ponen al día los cambios de inmediato.
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') refresh(); });

    // 1A: el cronómetro del registro arranca con la primera tecla en cualquiera de los buscadores y se descarta si se vacían todos (no se registró a nadie). Va DENTRO del mismo escuchador (uno solo por campo).
    const timerOnInput = () => {
      if (!opts.fastCheckin || !window.RegTimer) return;
      if ([cedulaInput, nombreInput, entidadInput].every((i) => !i || !i.value)) RegTimer.cancel(); else RegTimer.start();
    };
    [cedulaInput, nombreInput, entidadInput].forEach(input => {
      if (input) input.addEventListener('input', (e) => { timerOnInput(); return onSearchInput(e); });
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
    const UNDO_MS = 8000;           // cuánto se ofrece «Deshacer» en pantalla (el servidor lo permite hasta 15 s)
    /* Botón «Acreditar» de una fila: acredita como el botón puntual (confirmando) y ofrece «Deshacer». Sin red usa la lista local (la fila local no tiene la cédula: se acredita por huella). */
    async function acreditarFila(user, btn) {
      const cid = newClientId(), GC = window.GoldenContingency && window.GoldenContingency.instance;
      btn.disabled = true; btn.innerText = 'Acreditando...';
      lastAccredit = null;
      try {
        if (GC && (user.__local || GC.active())) await offlineAccredit(GC, user.__h ? { h: user.__h } : { cedula: user.id }, 'manual', cid);         // lista local o sin red: se encola y se envía al volver la red
        else await fastCheckin(user.id, false, null, true, undefined, cid);
      } finally {
        if (lastAccredit && lastAccredit.cid === cid) offerUndo(lastAccredit);
        else { btn.disabled = false; btn.innerText = 'Acreditar'; }
      }
    }
    function offerUndo(acc) {
      showToast(`${acc.name} acreditado(a)`, 'success', { action: { label: 'Deshacer', onClick: () => undoAccredit(acc) }, duration: UNDO_MS });
    }
    async function undoAccredit(acc) {
      const GC = window.GoldenContingency && window.GoldenContingency.instance;
      try {
        if (acc.offline) {
          if (!(GC && (await GC.unqueue(acc.cid)))) { showToast('Ya se envió al servidor: no se puede deshacer desde aquí', 'error'); return; }
          await loadFromLocalCopy();
        } else {
          const res = await fetch(`/api/events/${window.EVENT_ID}/accreditations/undo`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ client_id: acc.cid }) });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) { showToast(data.detail || 'No se pudo deshacer', 'error'); return; }
          applyFlags(data);
          if (window.BadgePrint && BadgePrint.releaseClaim) BadgePrint.releaseClaim(data.user_id || acc.id);       // PR3 (causa B/T5): volver a acreditar a la misma persona dentro de los 30 s sí imprime
          await reload();
        }
        showToast(`Acreditación de ${acc.name} deshecha`, 'success');
      } catch (e) { showToast('No se pudo deshacer: sin conexión con el servidor', 'error'); }
    }
    rowAccredit = opts.fastCheckin ? acreditarFila : null;
    let retryNote = null;
    function showRetryNote(on) {
      if (!on) { if (retryNote) { retryNote.remove(); retryNote = null; } return; }
      if (retryNote) return;
      retryNote = document.createElement('div');
      retryNote.setAttribute('role', 'status'); retryNote.setAttribute('aria-live', 'polite');
      retryNote.className = 'gw-alert gw-alert--warn gw-registro__retry';
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
      if (found.cedula) localHashes.set(found.cedula.toLowerCase(), found.person.h);
      clearSearchBox();                                                  // sin red también: acreditar deja la caja vacía
    });
    async function offlineCheckin(GC, cedula, method, cid) {
      if (await GC.autoRegister()) { await offlineAccredit(GC, { cedula }, method, cid); return; }
      const found = await GC.scanLocal(cedula);
      if (found.status === 'expired') { showToast('No hay copia local vigente: verificar manualmente', 'error'); verdict('err', 'Verificar manualmente', 'No hay copia local vigente de la lista.'); return; }
      if (found.status === 'not_found') { showToast('No registrado: verificar manualmente', 'error'); verdict('err', 'No está en la lista', 'Verificar manualmente.'); return; }
      if (cedulaInput) { cedulaInput.value = found.cedula; localHashes.set(found.cedula.toLowerCase(), found.person.h); applyFilters(); }          // la huella ya se conoce: el filtro de la lista local es inmediato
      const tbody = document.getElementById(opts.tbodyId);
      const row = tbody && (tbody.querySelector(`tr[data-user-id="${CSS.escape(found.cedula)}"]`) || tbody.querySelector(`tr[data-h="${found.person.h}"]`));
      const actionTd = row ? row.querySelector('.action-cell') : null;
      if (actionTd && !actionTd.querySelector('.btn-accredit-pending')) {
        const btn = document.createElement('button');
        btn.type = 'button'; btn.innerText = 'Acreditar'; btn.className = 'gw-btn gw-btn--primary gw-btn--xl btn-table-action btn-accredit-pending';
        btn.addEventListener('click', async () => { btn.disabled = true; btn.innerText = 'Acreditando...'; await offlineAccredit(GC, { cedula: found.cedula }, method, newClientId()); });
        actionTd.appendChild(btn);
      }
      showToast(`${found.person.n} encontrado(a) — el modo autoregistro está apagado: confirma con "Acreditar" en la fila`, 'success');
      verdict('info', 'Encontrado(a): confirma', `${found.person.n} · pulsa «Acreditar» en su tarjeta`);
    }

    async function fastCheckin(cedula, force, nameInfo, confirmFlag, method, clientId) {
      const GC0 = window.GoldenContingency && window.GoldenContingency.instance;
      if (!(GC0 && GC0.active()) && (confirmFlag || window.EVENT_AUTO_REGISTER !== false)) primePrint();          // la ventana de impresión se abre dentro del gesto (Enter del lector, clic en «Acreditar»), antes de cualquier llamada de red
      try { return await fastCheckinCore(cedula, force, nameInfo, confirmFlag, method, clientId); } finally { cancelPrimedPrint(); }
    }
    async function fastCheckinCore(cedula, force, nameInfo, confirmFlag, method, clientId) {
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
      if (window.RegTimer) RegTimer.appendTo(formData);  // 1A: took_ms/ui_flow (tiempo desde la primera tecla); el servidor lo acota y lo ignora si no sirve
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
            if (!res) { showToast('Error de red', 'error'); verdict('err', 'Sin conexión con el servidor', 'Revisa la red e inténtalo de nuevo.'); return; }
          } else if (res.status < 500 && res.status !== 401 && res.status !== 403) GC.noteAuthGood();
        }
        const data = await res.json();
        if (!res.ok) { showToast(data.detail || 'No se pudo acreditar', 'error'); verdict('err', 'No se pudo acreditar', data.detail || ''); return; }
        if (data.result === 'DUPLICADO') {
          cancelPrimedPrint();                                      // mientras se pregunta no queda una ventana en blanco abierta
          const confirmado = await confirmDuplicateRegistration(data.data, data.times_registered);
          if (confirmado) await fastCheckin(cedula, true, nameInfo, undefined, method, cid);
          else verdict('warn', 'Ya estaba registrado(a)', `${[data.data.first_name, data.data.last_name].filter(Boolean).join(' ')} · no se volvió a acreditar`.replace(/^ · /, ''));
          return;
        }
        if (data.result === 'MISSING_REQUIRED') {
          // A3 (26-oct-2026): falta un campo OBLIGATORIO (p. ej. se marcó obligatorio después de cargar la base): NO se acredita. Se dice cuál y se abre «Editar persona» con el foco en el
          // primer campo vacío; al guardar queda acreditado(a) en el mismo paso y la autoimpresión imprime después, con el dato ya lleno.
          showToast(data.details || `Falta el campo obligatorio: ${(data.missing || []).map((m) => m.label).join(', ')}`, 'warning');
          verdict('warn', 'Falta un dato obligatorio', (data.missing || []).map((m) => m.label).join(', '));
          await reload();
          const person = allUsers.find((u) => u.id === data.data.id) || Object.assign({ status: 'No registrado' }, data.data);
          buildEditModal(person, { missing: data.missing || [], method });
          return;
        }
        if (data.result === 'SÍ') {
          // Match exacto por cédula: acredita de una vez, sin modal aparte (2026-09-16, pedido
          // explícito) — la "confirmación" es ver la fila aparecer filtrada en el Directorio,
          // como si se hubiera buscado por cédula a mano.
          showToast(`Acreditado: ${data.data.first_name} ${data.data.last_name}`, 'success');
          verdict('ok', 'Acreditado(a)', `${data.data.first_name} ${data.data.last_name}`.trim());
          if (window.RegTimer) RegTimer.done();
          Recent.add(data.data.id);
          lastAccredit = { cid, id: data.data.id, name: `${data.data.first_name} ${data.data.last_name}`.trim(), offline: false, at: Date.now() };
          if (data.data.sibling_events && data.data.sibling_events.length) {
            showToast(`Ya asistió a ${data.data.sibling_events.join(', ')} (mismo superevento) — sus datos se vincularon, no hizo falta capturarlos de nuevo`, 'success');
          }
          applyFlags(data);
          if (window.BadgePrint) BadgePrint.maybeAutoPrint(data.data.id, { auto: data.auto_print });
          await reload();
          clearSearchBox();                                         // 5-nov-2026: acreditar deja la caja vacía (antes dejaba la cédula escrita)
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
            acreditarBtn.innerText = 'Acreditar';
            acreditarBtn.className = 'gw-btn gw-btn--primary gw-btn--xl btn-table-action btn-accredit-pending';
            acreditarBtn.addEventListener('click', async () => {
              acreditarBtn.disabled = true; acreditarBtn.innerText = 'Acreditando...';
              await fastCheckin(data.data.id, false, null, true, method);
            });
            actionTd.appendChild(acreditarBtn);
          }
          showToast(`${data.data.first_name} ${data.data.last_name} encontrado(a) — confirma con "Acreditar" en la fila`, 'success');
          verdict('info', 'Encontrado(a): confirma', `${data.data.first_name} ${data.data.last_name}`.trim() + ' · pulsa «Acreditar» en su tarjeta');
          if (data.data.sibling_events && data.data.sibling_events.length) {
            showToast(`Ya asistió a ${data.data.sibling_events.join(', ')} (mismo superevento) — sus datos ya están guardados`, 'success');
          }
          return;
        }
        // NO_MATCH: ya NO se ofrece alta manual automática (2026-09-16, pedido explícito — para
        // eso está el botón "Registrar nuevo" aparte). Si venía un nombre (CSV de la cédula
        // vieja, u OCR de la MRZ nueva), se filtra el Directorio por ese nombre — mismo criterio
        // de "empieza por palabra" que la búsqueda manual — y el operador decide desde ahí.
        const fullName = nameInfo ? `${nameInfo.nombres || ''} ${nameInfo.apellidos || ''}`.trim() : '';
        if (fullName && (nombreInput || unified)) {
          if (unified) cedulaInput.value = fullName;
          else { if (cedulaInput) cedulaInput.value = ''; nombreInput.value = fullName; }
          applyFilters();
          const found = data.name_matches && data.name_matches.length;
          showToast(
            found
              ? `Cédula no encontrada — mostrando coincidencias por nombre para "${fullName}"`
              : `Cédula no encontrada y sin coincidencias por nombre para "${fullName}"`,
            found ? 'success' : 'error'
          );
          if (found) verdict('info', 'Cédula no encontrada', `Mostrando coincidencias por nombre para «${fullName}»`);
          else verdict('err', 'No está en la lista', `Sin coincidencias para «${fullName}». Puedes usar «Registrar nuevo».`);
        } else {
          showToast(data.details || 'Cédula no encontrada', 'error');
          verdict('err', 'No está en la lista', 'Cédula no encontrada. Si es una persona nueva, usa «Registrar nuevo».');
        }
      } catch (e) {
        showToast('Error de red', 'error');
        verdict('err', 'Error de red', 'Revisa la conexión e inténtalo de nuevo.');
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
          let raw = cedulaInput.value.trim();
          if (!raw) return;
          if (window.QrCode && QrCode.collect) {                       // QR en vCard con lector de mano: llega en varias líneas; se espera a que termine (Fase 10, C)
            const whole = QrCode.collect(raw);
            if (whole === null) { cedulaInput.value = ''; syncClearBtn(); return; }
            raw = QrCode.unwrap(whole).trim();
            if (!raw) { cedulaInput.value = ''; syncClearBtn(); return; }
          }
          if (window.QrCode && QrCode.isDynamic && QrCode.isDynamic(raw)) {           // QR dinámico de la credencial digital: el servidor valida firma y vigencia y devuelve la persona
            QrCode.resolveDynamic(raw, window.EVENT_ID).then((resolved) => {
              const qr = QrCode.parse(resolved);
              fastCheckin(qr.cedula, false, { nombres: qr.nombres, apellidos: qr.apellidos }, undefined, 'qr');
              cedulaInput.value = ''; syncClearBtn();
            }).catch((err) => { showToast(err.message || 'No se pudo validar el código', 'error'); verdict('err', 'Código no válido', err.message || 'No se pudo validar el código'); });
            return;
          }
          if (unified) {                                                // nombre/empresa (o menos de 3 dígitos): solo buscar, sin registrar ni limpiar
            const q = SC.classifyQuery(raw);
            const doc = (q.kind === 'cedula' && !q.corta) || q.kind === 'lector' || q.kind === 'qr'
              || (q.kind === 'texto' && q.compact && /\d/.test(q.compact) && /[a-z]/.test(q.compact) && !/\s/.test(raw));
            if (!doc) { clearTimeout(searchTimer); pageIdx = 0; applyFilters(); return; }
          }
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
          syncClearBtn();
        }
      });
    }

    if (unified && !cedulaInput.disabled) { try { cedulaInput.focus(); } catch (_) { /* sin foco en pruebas */ } }
    reload();
    return {
      reload, refresh,
      searchState: () => ({ unified, query: activeQuery, reasons: lastFiltered.map((u) => reasons.get(u) || ''), results: lastFiltered.slice() }),
      /* Punto de entrada compartido para cualquier OTRO método que resuelva una cédula+nombre
         fuera del campo de texto de arriba (ej. el escaneo por foto de la MRZ, Historia 2.3) —
         reusa exactamente el mismo flujo de dos pasos + DUPLICADO/force que el atajo de lector. */
      hashesSettled: async () => { while (inflightHashes.size) await Promise.all([...inflightHashes]); },      // para pruebas y para quien necesite saber que la búsqueda por cédula ya se completó
      submitScannedCedula: (cedula, nameInfo, method) => fastCheckin(cedula, false, nameInfo || null, undefined, method),
      /* "Limpiar filtros" (2026-09-16, pedido explícito) — vacía los 3 campos de búsqueda + el
         filtro de "sin registrar" y vuelve a mostrar el Directorio completo. */
      clearFilters: () => {
        if (cedulaInput) cedulaInput.value = '';
        if (nombreInput) nombreInput.value = '';
        if (entidadInput) entidadInput.value = '';
        onlyNotRegistered = false;
        if (originSelect) originSelect.value = '';
        pageIdx = 0;
        if (counterBtn) counterBtn.setAttribute('aria-pressed', 'false');
        applyFilters();
      },
    };
  }

  window.GoldenDirectory = { render: renderRows, load: loadRows, mountSearch, parseOldCedulaBarcode, matchesWordPrefix, openEdit: buildEditModal, noteRecent: (id) => Recent.add(id), recent: () => Recent.list() };
})();
