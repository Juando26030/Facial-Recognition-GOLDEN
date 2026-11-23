/* Legalizaciones del evento en el formato oficial de Golden (14-nov-2026): una pestaña por rubro (las hojas del Excel), encabezado, resumen,
   envío a revisión y aprobación del director. Las rutas son /api/events/{id}/legalization/… (app/routers/legalizations.py); archivar, restaurar y
   borrar un gasto siguen siendo /api/events/{id}/expenses/{id}/… de siempre. */
(function () {
  'use strict';
  const EVENT_ID = window.EVENT_ID;
  const API = '/api/events/' + EVENT_ID;
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const icon = (n) => '<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="' + window.GW_ICONS + '#i-' + n + '"/></svg>';
  const money = (n) => Number(n || 0).toLocaleString('es-CO', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  const ROLE = window.STAFF_ROLE || '', isSuper = ROLE === 'super_admin';
  const busy = (btn, work) => (window.GW && GW.busy && btn ? GW.busy(btn, work) : Promise.resolve(work()));

  const STATUS = { borrador: ['Borrador', ''], enviada: ['Enviada a revisión', 'gw-badge--info'], aprobada: ['Aprobada', 'gw-badge--ok'], devuelta: ['Devuelta para corregir', 'gw-badge--warn'] };
  const SUMMARY_KEY = { hospedaje: 'hospedaje', pasaje: 'pasajes', taxi_terminal: 'traslado_terminales', taxi_ciudad: 'taxis_ciudad', alimentacion: 'alimentacion', digitador: 'digitadores', otro: 'otros' };
  const TAB_ICON = { hospedaje: 'form', pasaje: 'form', taxi_terminal: 'form', taxi_ciudad: 'form', alimentacion: 'form', digitador: 'form', otro: 'form' };

  /* Campos de cada rubro, en el orden de la hoja del Excel. [campo, etiqueta, tipo, ancho (1-3 columnas), obligatorio] */
  const F = {
    date: ['expense_date', 'Fecha', 'date'], tax: ['tax_id', 'NIT o cédula', 'text'], addr: ['address', 'Dirección', 'text'], phone: ['phone', 'Teléfono', 'text'],
    email: ['email', 'Correo', 'text'], origin: ['origin', 'Origen', 'text'], dest: ['destination', 'Destino', 'text'], iva: ['iva', 'IVA', 'money'],
    support: ['has_support', '¿Tiene recibo o factura?', 'support'], obs: ['observation', 'Observaciones', 'text'],
  };
  const named = (label, req) => ['vendor_name', label, 'text', req];
  const amount = (label) => ['amount', label || 'Valor', 'money', true];
  const CONFIG = {
    hospedaje: { lead: 'Hoteles y alojamiento del equipo.', fields: [F.date, F.tax, named('Hotel o establecimiento'), F.addr, F.phone, F.email, ['concept', 'Concepto', 'text'], amount(), F.iva, F.support] },
    pasaje: { lead: 'Pasajes aéreos o terrestres.', fields: [F.date, F.tax, named('Empresa o aerolínea'), F.addr, F.phone, F.email, F.origin, F.dest, ['concept', 'Concepto', 'text'], amount(), F.iva, F.support] },
    taxi_terminal: { lead: 'Traslados hacia y desde terminales o aeropuertos.', fields: [F.date, F.tax, named('Conductor o empresa'), F.addr, F.phone, F.email, F.origin, F.dest, ['concept', 'Concepto', 'text'], amount(), F.iva, F.support] },
    taxi_ciudad: { lead: 'Taxis y transporte público dentro de la ciudad. Si no hay recibo, el Excel arma el comprobante en la hoja «Soportes».',
      fields: [F.date, F.tax, named('Nombre del conductor'), ['plate', 'Placa', 'text'], F.phone, F.email, F.origin, F.dest, ['concept', 'Concepto', 'text'], ['vehicle', 'Vehículo', 'vehicle'], amount(), F.support] },
    digitador: { lead: 'Pago a digitadores(as): el valor se escribe a mano porque puede variar.', fields: [F.date, F.tax, named('Nombre', true), F.addr, F.phone, F.email, amount('Valor pagado')] },
    alimentacion: { lead: 'Escribe el valor unitario y cuántos desayunos, almuerzos, comidas y refrigerios fueron; el valor del gasto es el valor unitario × esa suma.',
      fields: [F.date, F.tax, named('Establecimiento'), F.addr, F.email, F.phone, ['unit_value', 'Valor unitario', 'money'], ['breakfast', 'Desayunos (cantidad)', 'count'], ['lunch', 'Almuerzos (cantidad)', 'count'],
        ['dinner', 'Comidas (cantidad)', 'count'], ['snack', 'Refrigerios (cantidad)', 'count'], F.obs, F.iva, F.support] },
    otro: { lead: 'Cualquier gasto que no sea de los otros rubros. El detalle es obligatorio.', fields: [F.date, F.tax, named('Proveedor o a quién se pagó'), F.addr, F.phone, F.email, ['concept', 'Detalle', 'text', true], F.obs, amount(), F.iva, F.support] },
  };

  let state = null;          // última respuesta de GET /legalization
  let activeKind = 'hospedaje';
  let editing = null;        // id del gasto que se está corrigiendo (o null)
  let pendingFile = null;    // foto elegida en el formulario
  const isEditable = () => !state || ['borrador', 'devuelta'].includes(state.header.status);
  const isDirector = () => !!(state && state.can_review);

  async function api(path, opts) {
    const res = await fetch(API + path, opts);
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) throw new Error((data && data.detail) || 'No se pudo completar la acción');
    return data;
  }
  const jsonOpts = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

  /* ---------------------------------------------------------------- Carga y pintado general */
  async function load() {
    try {
      const withArchived = $('showArchived') && $('showArchived').checked;
      state = await api('/legalization' + (withArchived ? '?include_archived=true' : ''));
    } catch (err) {
      $('legPanels').innerHTML = '<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">No se pudo cargar la legalización</p><p class="gw-state__text">Revisa tu conexión e inténtalo de nuevo.</p><button type="button" class="gw-btn gw-btn--secondary" data-retry>Reintentar</button></div>';
      return;
    }
    paintAll();
  }

  function paintAll() {
    paintHeader();
    paintSummary();
    paintTabs();
  }

  function paintHeader() {
    const h = state.header, ed = isEditable();
    const [label, cls] = STATUS[h.status] || STATUS.borrador;
    const badge = $('legStatus');
    badge.textContent = label;
    badge.className = 'gw-badge ' + cls;
    badge.hidden = false;
    const form = $('legHeadForm');
    if (!form.dataset.dirty) {
      $('hName').value = h.responsible_name || '';
      $('hCc').value = h.responsible_cc || '';
      $('hAdvance').value = h.advance_amount == null ? '' : h.advance_amount;
      $('hDate').value = h.legalization_date || '';
    }
    form.querySelectorAll('input').forEach((i) => { i.disabled = !ed; });
    $('legEventLine').textContent = 'Evento ' + h.event_code + ' · ' + h.event_name + (h.city ? ' · ' + h.city : '') + '. El archivo se descarga como ' + state.file_name + '.';
    const n = $('legNotice');
    if (h.status === 'devuelta') {
      n.hidden = false;
      n.className = 'gw-alert gw-alert--warn';
      n.innerHTML = '<div class="gw-alert__body"><p class="gw-alert__title">El director devolvió la legalización</p><p>' + esc(h.review_note || 'Corrígela y vuelve a enviarla.') + '</p></div>';
    } else if (h.status === 'enviada') {
      n.hidden = false;
      n.className = 'gw-alert';
      n.innerHTML = '<div class="gw-alert__body"><p class="gw-alert__title">Enviada a revisión</p><p>' + (isDirector() ? 'Marca cada gasto como aprobado o no aprobado y luego aprueba o devuelve la legalización.' : 'Está bloqueada mientras el director la revisa. Si necesita correcciones, te la devolverá con una nota.') + '</p></div>';
    } else if (h.status === 'aprobada') {
      n.hidden = false;
      n.className = 'gw-alert gw-alert--ok';
      n.innerHTML = '<div class="gw-alert__body"><p class="gw-alert__title">Legalización aprobada</p><p>Descarga el Excel y entrégalo al área administrativa para la contabilización.</p></div>';
    } else {
      n.hidden = true;
    }
    $('legSubmit').hidden = !ed;
    $('legApprove').hidden = !(isDirector() && h.status === 'enviada');
    $('legReturn').hidden = !(isDirector() && h.status === 'enviada');
  }

  function paintSummary() {
    const s = state.summary, adv = state.header.advance_amount || 0;
    $('sTotal').textContent = money(s.total);
    $('sAdvance').textContent = money(adv);
    $('sCount').textContent = String(state.lines.filter((x) => !x.archived).length);
    const dev = s.devolver > 0;
    $('sBalance').textContent = money(dev ? s.devolver : s.reembolsar);
    $('sBalanceLabel').textContent = dev ? 'A devolver por el coordinador' : 'A reembolsar al coordinador';
  }

  /* ---------------------------------------------------------------- Pestañas */
  function paintTabs() {
    const list = $('legTablist');
    list.innerHTML = state.kinds.map((k) => {
      const sel = k.kind === activeKind;
      const count = state.lines.filter((x) => x.kind === k.kind && !x.archived).length;
      const total = state.summary[SUMMARY_KEY[k.kind]] || 0;
      return `<button type="button" class="gw-tab" role="tab" id="tab_${k.kind}" data-kind="${k.kind}" aria-controls="panel_${k.kind}" aria-selected="${sel}" ${sel ? '' : 'tabindex="-1"'}>
        ${icon(TAB_ICON[k.kind])}<span class="gw-tab__name">${esc(k.label)}</span><span class="gw-tab__sum">${count ? count + (count === 1 ? ' gasto · ' : ' gastos · ') + '$ ' + money(total) : 'Sin gastos'}</span></button>`;
    }).join('');
    $('legPanels').innerHTML = state.kinds.map((k) => `<section class="gw-tabpanel" role="tabpanel" id="panel_${k.kind}" data-kind="${k.kind}" aria-labelledby="tab_${k.kind}" ${k.kind === activeKind ? '' : 'hidden'}></section>`).join('');
    paintPanel(activeKind);
  }

  function fieldHtml(kind, f, line) {
    const [name, label, type, req] = f;
    const id = 'f_' + name;
    const val = line ? line[name] : '';
    const reqMark = req ? ' *' : '';
    if (type === 'support') {
      const v = line ? line.has_support : null;
      return `<div class="gw-field"><label class="gw-label" for="${id}">${label}</label><select class="gw-input" id="${id}" name="${name}">
        <option value="" ${v == null ? 'selected' : ''}>Sin responder</option><option value="S" ${v === true ? 'selected' : ''}>Sí (S)</option><option value="N" ${v === false ? 'selected' : ''}>No (N)</option></select></div>`;
    }
    if (type === 'vehicle') {
      return `<div class="gw-field"><label class="gw-label" for="${id}">${label}</label><select class="gw-input" id="${id}" name="${name}">
        <option value="" ${!val ? 'selected' : ''}>Sin indicar</option><option value="taxi" ${val === 'taxi' ? 'selected' : ''}>Taxi</option><option value="otro" ${val === 'otro' ? 'selected' : ''}>Otro / transporte público</option></select></div>`;
    }
    if (type === 'count') {
      return `<div class="gw-field"><label class="gw-label" for="${id}">${label}</label><input class="gw-input" type="number" id="${id}" name="${name}" min="0" step="1" inputmode="numeric" placeholder="0" value="${val == null || val === 0 ? '' : esc(val)}"></div>`;
    }
    if (type === 'money') {
      return `<div class="gw-field"><label class="gw-label" for="${id}">${label}${reqMark}</label><input class="gw-input" type="number" id="${id}" name="${name}" min="0" step="0.01" inputmode="decimal" placeholder="0" value="${val == null ? '' : esc(val)}"></div>`;
    }
    const attrs = type === 'date' ? 'type="date"' : 'type="text" maxlength="300" autocomplete="off"';
    return `<div class="gw-field"><label class="gw-label" for="${id}">${label}${reqMark}</label><input class="gw-input" ${attrs} id="${id}" name="${name}" value="${esc(val)}"></div>`;
  }

  function detailOf(x) {
    const parts = [];
    if (x.origin || x.destination) parts.push(esc(x.origin || '—') + ' → ' + esc(x.destination || '—'));
    if (x.concept) parts.push(esc(x.concept));
    if (x.kind === 'alimentacion') {
      const legacy = !x.unit_value;          // gastos anteriores: cada comida traía su valor en pesos
      const m = [['Desayuno', x.breakfast], ['Almuerzo', x.lunch], ['Cena', x.dinner], ['Refrigerio', x.snack]].filter((p) => p[1]).map((p) => p[0] + ' ' + (legacy ? '$ ' + money(p[1]) : '× ' + p[1]));
      if (m.length) parts.push(m.join(' · '));
      if (!legacy) parts.push('Valor unitario $ ' + money(x.unit_value));
    }
    if (x.plate) parts.push('Placa ' + esc(x.plate));
    if (x.observation) parts.push(esc(x.observation));
    return parts.join('<br>') || '<span class="gw-muted">—</span>';
  }

  function reviewCell(x) {
    if (isDirector() && state.header.status === 'enviada' && !x.archived) {
      const v = x.approved === true ? 'S' : x.approved === false ? 'N' : '';
      return `<select class="gw-input gw-input--short" data-review="${x.id}" aria-label="Revisión del gasto">
        <option value="" ${v === '' ? 'selected' : ''}>Pendiente</option><option value="S" ${v === 'S' ? 'selected' : ''}>Aprobado</option><option value="N" ${v === 'N' ? 'selected' : ''}>No aprobado</option></select>`;
    }
    return x.approved === true ? '<span class="gw-badge gw-badge--ok">Aprobado</span>' : x.approved === false ? '<span class="gw-badge gw-badge--err">No aprobado</span>' : '<span class="gw-muted">Pendiente</span>';
  }

  function supportCell(x) {
    const flag = x.has_support === true ? '<span class="gw-badge gw-badge--ok">Con soporte</span>' : x.has_support === false ? '<span class="gw-badge gw-badge--warn">Sin soporte</span>' : '<span class="gw-muted">—</span>';
    const photo = x.has_evidence
      ? `<a href="${API}/expenses/${x.id}/evidence" target="_blank" rel="noopener" aria-label="Abrir la foto del soporte en una pestaña nueva"><img class="gw-card-row__thumb" src="${API}/expenses/${x.id}/evidence" alt="Foto del soporte" loading="lazy"></a>` : '';
    const attach = isEditable() && !x.archived ? `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-attach="${x.id}">${icon('camera')} ${x.has_evidence ? 'Cambiar foto' : 'Adjuntar foto'}</button>` : '';
    return `<div class="gw-leg-cell">${flag}${photo}${attach}</div>`;
  }

  function actionsCell(x) {
    const out = [];
    if (isEditable() && !x.archived) {
      out.push(`<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-edit="${x.id}">${icon('edit')} Editar</button>`);
      out.push(`<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-dup="${x.id}" title="Crea una copia debajo para cambiarle lo que haga falta">Duplicar</button>`);
      out.push(`<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-archive="${x.id}">Archivar</button>`);
    }
    if (x.archived) {
      out.push(`<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-restore="${x.id}">${icon('undo')} Restaurar</button>`);
      if (isSuper) out.push(`<button type="button" class="gw-btn gw-btn--danger-outline gw-btn--sm" data-del="${x.id}">${icon('trash')} Eliminar definitivamente</button>`);
    }
    return `<div class="gw-leg-cell gw-leg-cell--actions">${out.join('')}</div>`;
  }

  function paintPanel(kind) {
    const panel = $('panel_' + kind);
    if (!panel) return;
    const cfg = CONFIG[kind];
    const label = (state.kinds.find((k) => k.kind === kind) || {}).label || kind;
    const lines = state.lines.filter((x) => x.kind === kind);
    const line = editing ? lines.find((x) => x.id === editing) : null;
    const total = state.summary[SUMMARY_KEY[kind]] || 0;
    let html = `<div class="gw-tabpanel__head"><h2 class="gw-tabpanel__title">${esc(label)}</h2><p class="gw-tabpanel__lead">${esc(cfg.lead)} Total del rubro: <strong>$ ${money(total)}</strong>.</p></div>`;
    if (isEditable()) {
      html += `<form class="gw-stack" data-line-form="${kind}" novalidate>
        <h3 class="gw-section-title">${line ? 'Corregir el gasto' : 'Registrar un gasto'}</h3>
        <div class="gw-form-grid">${cfg.fields.map((f) => fieldHtml(kind, f, line)).join('')}</div>
        <div class="gw-field"><label class="gw-label" for="f_file">Foto del soporte (opcional)</label><input class="gw-input" type="file" id="f_file" name="evidence" accept="image/*" capture="environment"></div>
        <div class="gw-actions">
          <button type="submit" class="gw-btn gw-btn--primary">${line ? 'Guardar cambios' : icon('plus') + ' Registrar gasto'}</button>
          ${line ? '<button type="button" class="gw-btn gw-btn--secondary" data-cancel-edit>Cancelar</button>' : ''}
        </div>
      </form>`;
    }
    if (!lines.length) {
      html += `<div class="gw-state">${icon('form')}<p class="gw-state__title">Todavía no hay gastos en este rubro</p><p class="gw-state__text">${isEditable() ? 'Registra el primero con el formulario de arriba.' : 'No se registró ninguno.'}</p></div>`;
    } else {
      html += `<div class="gw-table-wrap"><table class="gw-table gw-leg-table"><thead><tr>${isEditable() ? '<th><span class="gw-sr-only">Orden</span></th>' : ''}<th>Fecha</th><th>Nombre</th><th>Detalle</th><th>Valor</th><th>Soporte</th><th>Revisión</th><th>Acciones</th></tr></thead><tbody>` +
        lines.map((x, i) => `<tr data-row="${x.id}" ${isEditable() && !x.archived ? 'draggable="true"' : ''} class="${[x.archived ? 'gw-muted' : '', x.approved === true ? 'gw-leg-row--ok' : x.approved === false ? 'gw-leg-row--no' : ''].filter(Boolean).join(' ')}">
          ${isEditable() ? `<td class="gw-leg-order">${x.archived ? '' : `<span class="gw-leg-grip" aria-hidden="true" title="Arrastra para cambiar el orden">⠿</span><button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-move="up" data-id="${x.id}" aria-label="Subir el gasto" ${i === 0 ? 'disabled' : ''}>↑</button><button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-move="down" data-id="${x.id}" aria-label="Bajar el gasto" ${i === lines.length - 1 ? 'disabled' : ''}>↓</button>`}</td>` : ''}
          <td>${esc(x.date || '')}</td><td>${esc(x.vendor_name) || '<span class="gw-muted">—</span>'}${x.tax_id ? '<br><span class="gw-text-sm gw-muted">' + esc(x.tax_id) + '</span>' : ''}${x.archived ? '<br><span class="gw-badge">Archivado</span>' : ''}</td>
          <td>${detailOf(x)}</td><td class="gw-leg-num">$ ${money(x.amount)}${x.iva ? '<br><span class="gw-text-sm gw-muted">IVA ' + money(x.iva) + '</span>' : ''}</td>
          <td>${supportCell(x)}</td><td>${reviewCell(x)}</td><td>${actionsCell(x)}</td></tr>`).join('') + '</tbody></table></div>';
    }
    panel.innerHTML = html;
  }

  function selectTab(kind, focus) {
    if (!CONFIG[kind]) return;
    activeKind = kind;
    if (editing && !state.lines.some((x) => x.id === editing && x.kind === kind)) editing = null;
    $('legTablist').querySelectorAll('.gw-tab').forEach((t) => {
      const on = t.dataset.kind === kind;
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      if (on) t.removeAttribute('tabindex'); else t.setAttribute('tabindex', '-1');
      if (on && focus) t.focus();
    });
    $('legPanels').querySelectorAll('.gw-tabpanel').forEach((p) => { p.hidden = p.dataset.kind !== kind; });
    pendingFile = null;
    paintPanel(kind);
  }

  /* ---------------------------------------------------------------- Formularios */
  function collect(form) {
    const body = { kind: form.dataset.lineForm };
    form.querySelectorAll('[name]').forEach((el) => {
      if (el.type === 'file') return;
      let v = el.value;
      if (el.name === 'has_support') v = v === 'S' ? true : v === 'N' ? false : null;
      else if (typeof v === 'string') v = v.trim();
      body[el.name] = v === '' ? null : v;
    });
    return body;
  }

  async function uploadEvidence(lineId, file) {
    const fd = new FormData();
    fd.append('evidence', file);
    const out = await DirectUpload.replaceFiles(fd, { evidence: ['evidence_upload', 'expense_evidence'] }, { body: { event_id: EVENT_ID } });
    await api('/legalization/lines/' + lineId + '/evidence', { method: 'POST', body: out });
  }

  $('legPanels').addEventListener('submit', (e) => {
    const form = e.target.closest('[data-line-form]');
    if (!form) return;
    e.preventDefault();
    const btn = form.querySelector('button[type="submit"]');
    const body = collect(form);
    const file = form.querySelector('input[type="file"]').files[0];
    busy(btn, async () => {
      const saved = await api(editing ? '/legalization/lines/' + editing : '/legalization/lines', jsonOpts(editing ? 'PUT' : 'POST', body));
      if (file) {
        try { await uploadEvidence(saved.id, file); } catch (err) { showToast('El gasto quedó guardado, pero la foto no subió: ' + err.message, 'error'); }
      }
    }).then(() => {
      showToast(editing ? 'Gasto actualizado' : 'Gasto registrado', 'success');
      editing = null;
      return load();
    }).catch((err) => showToast(err.message || 'No se pudo guardar el gasto', 'error'));
  });

  // El encabezado se guarda con la barra única («Guardar cambios», Ctrl/Cmd+S); los gastos siguen con su propio formulario.
  $('legHeadForm').addEventListener('input', () => { $('legHeadForm').dataset.dirty = '1'; });
  $('legHeadForm').addEventListener('submit', (e) => { e.preventDefault(); });
  GWParams.register({ key: 'leghead', label: 'Encabezado de la legalización', order: 10, save: async () => {
    await api('/legalization', jsonOpts('PUT', {
      responsible_name: $('hName').value, responsible_cc: $('hCc').value, advance_amount: $('hAdvance').value || null, legalization_date: $('hDate').value || null,
    }));
    delete $('legHeadForm').dataset.dirty;
    await load();
  } });

  /* ---------------------------------------------------------------- Clics (delegación) */
  $('legTablist').addEventListener('click', (e) => {
    const t = e.target.closest('[data-kind]');
    if (t) selectTab(t.dataset.kind);
  });
  $('legTablist').addEventListener('keydown', (e) => {
    if (!['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
    const kinds = state.kinds.map((k) => k.kind);
    let i = kinds.indexOf(activeKind);
    if (e.key === 'Home') i = 0; else if (e.key === 'End') i = kinds.length - 1;
    else i = (i + (['ArrowDown', 'ArrowRight'].includes(e.key) ? 1 : -1) + kinds.length) % kinds.length;
    e.preventDefault();
    selectTab(kinds[i], true);
  });

  /* Orden de los gastos: arrastrar la fila (o los botones ↑ ↓, para teclado y celular). Se guarda en el servidor y vale también para el Excel. */
  async function saveOrder(kind, ids) {
    const rank = new Map(ids.map((id, i) => [id, i]));
    state.lines = state.lines.filter((x) => x.kind !== kind).concat(state.lines.filter((x) => x.kind === kind).sort((a, b) => (rank.has(a.id) ? rank.get(a.id) : 1e6) - (rank.has(b.id) ? rank.get(b.id) : 1e6)));
    paintPanel(kind);
    try { await api('/legalization/lines/order', jsonOpts('PUT', { kind, ids })); } catch (err) { showToast(err.message || 'No se pudo guardar el orden', 'error'); load(); }
  }
  const visibleIds = (kind) => state.lines.filter((x) => x.kind === kind && !x.archived).map((x) => x.id);
  let dragId = null;
  $('legPanels').addEventListener('dragstart', (e) => { const tr = e.target.closest && e.target.closest('tr[data-row]'); if (!tr || tr.getAttribute('draggable') !== 'true') return; dragId = Number(tr.dataset.row); e.dataTransfer.effectAllowed = 'move'; try { e.dataTransfer.setData('text/plain', String(dragId)); } catch (err) { /* sin datos */ } tr.classList.add('gw-leg-row--drag'); });
  $('legPanels').addEventListener('dragover', (e) => { const tr = e.target.closest && e.target.closest('tr[data-row]'); if (dragId == null || !tr || tr.getAttribute('draggable') !== 'true') return; e.preventDefault(); $('legPanels').querySelectorAll('.gw-leg-row--over').forEach((r) => r.classList.remove('gw-leg-row--over')); if (Number(tr.dataset.row) !== dragId) tr.classList.add('gw-leg-row--over'); });
  $('legPanels').addEventListener('dragend', () => { dragId = null; $('legPanels').querySelectorAll('.gw-leg-row--drag, .gw-leg-row--over').forEach((r) => r.classList.remove('gw-leg-row--drag', 'gw-leg-row--over')); });
  $('legPanels').addEventListener('drop', (e) => {
    const tr = e.target.closest && e.target.closest('tr[data-row]');
    if (dragId == null || !tr) return;
    e.preventDefault();
    const target = Number(tr.dataset.row), from = dragId; dragId = null;
    if (target === from) { paintPanel(activeKind); return; }
    const ids = visibleIds(activeKind), a = ids.indexOf(from), b = ids.indexOf(target);
    if (a < 0 || b < 0) { paintPanel(activeKind); return; }
    ids.splice(a, 1); ids.splice(b, 0, from);          // cae en el lugar de la fila sobre la que se soltó
    saveOrder(activeKind, ids);
  });

  const ACTIONS = {
    archive: ['¿Archivar este gasto? Sale de la lista, del total y del Excel, pero se conserva (con su soporte) y se puede restaurar.', 'Archivar', 'Gasto archivado', 'POST', '/archive'],
    restore: ['¿Restaurar este gasto? Vuelve a la lista y a sumar en el total.', 'Restaurar', 'Gasto restaurado', 'POST', '/restore'],
    del: ['¿Eliminar definitivamente este gasto y su soporte? No se puede deshacer.', 'Eliminar definitivamente', 'Gasto eliminado definitivamente', 'DELETE', ''],
  };

  $('legPanels').addEventListener('click', async (e) => {
    if (e.target.closest('[data-retry]')) { load(); return; }
    if (e.target.closest('[data-cancel-edit]')) { editing = null; paintPanel(activeKind); return; }
    const mv = e.target.closest('[data-move]');
    if (mv) {
      const ids = visibleIds(activeKind), id = Number(mv.dataset.id), i = ids.indexOf(id), j = mv.dataset.move === 'up' ? i - 1 : i + 1;
      if (i >= 0 && j >= 0 && j < ids.length) { ids.splice(i, 1); ids.splice(j, 0, id); saveOrder(activeKind, ids); }
      return;
    }
    const dup = e.target.closest('[data-dup]');
    if (dup) {
      busy(dup, () => api('/legalization/lines/' + dup.dataset.dup + '/duplicate', jsonOpts('POST')))
        .then(() => { showToast('Gasto duplicado como «copia»: está justo debajo; corrígelo con «Editar»', 'success'); return load(); })
        .catch((err) => showToast(err.message || 'No se pudo duplicar el gasto', 'error'));
      return;
    }
    const edit = e.target.closest('[data-edit]');
    if (edit) { editing = Number(edit.dataset.edit); paintPanel(activeKind); const f = $('panel_' + activeKind).querySelector('form'); if (f) f.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
    const attach = e.target.closest('[data-attach]');
    if (attach) {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'image/*';
      input.addEventListener('change', () => {
        if (!input.files[0]) return;
        busy(attach, () => uploadEvidence(attach.dataset.attach, input.files[0])).then(() => { showToast('Soporte guardado', 'success'); return load(); })
          .catch((err) => showToast(err.message || 'No se pudo subir la foto', 'error'));
      });
      input.click();
      return;
    }
    const btn = e.target.closest('[data-archive], [data-restore], [data-del]');
    if (!btn) return;
    const act = btn.dataset.archive ? 'archive' : btn.dataset.restore ? 'restore' : 'del';
    const id = btn.dataset.archive || btn.dataset.restore || btn.dataset.del;
    const cfg = ACTIONS[act];
    if (!await showConfirm(cfg[0], { confirmLabel: cfg[1] })) return;
    try {
      await busy(btn, async () => {
        const res = await fetch(API + '/expenses/' + id + cfg[4], { method: cfg[3] });
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'No se pudo completar la acción');
      });
      showToast(cfg[2], 'success');
    } catch (err) { showToast(err.message || 'No se pudo completar la acción', 'error'); }
    editing = null;
    load();
  });

  $('legPanels').addEventListener('change', (e) => {
    const sel = e.target.closest('[data-review]');
    if (!sel) return;
    const approved = sel.value === 'S' ? true : sel.value === 'N' ? false : null;
    api('/legalization/lines/' + sel.dataset.review + '/review', jsonOpts('POST', { approved })).then(() => load())
      .catch((err) => { showToast(err.message || 'No se pudo guardar la revisión', 'error'); load(); });
  });

  /* ---------------------------------------------------------------- Envío y aprobación */
  $('legSubmit').addEventListener('click', async () => {
    if ($('legHeadForm').dataset.dirty) { showToast('Guarda los cambios del encabezado antes de enviar la legalización', 'error'); return; }
    if (!await showConfirm('¿Enviar la legalización al director? Quedará bloqueada para cambios hasta que la apruebe o te la devuelva.', { confirmLabel: 'Enviar a revisión', variant: 'warning' })) return;
    busy($('legSubmit'), () => api('/legalization/submit', { method: 'POST' })).then(() => { showToast('Legalización enviada a revisión', 'success'); return load(); })
      .catch((err) => showToast(err.message || 'No se pudo enviar la legalización', 'error'));
  });
  $('legApprove').addEventListener('click', async () => {
    if (!await showConfirm('¿Aprobar la legalización? Los gastos sin marcar quedan aprobados; los marcados «No aprobado» se conservan así.', { confirmLabel: 'Aprobar', variant: 'warning' })) return;
    busy($('legApprove'), () => api('/legalization/approve', { method: 'POST' })).then(() => { showToast('Legalización aprobada', 'success'); return load(); })
      .catch((err) => showToast(err.message || 'No se pudo aprobar', 'error'));
  });
  $('legReturn').addEventListener('click', async () => {
    const note = await showPrompt('¿Qué debe corregir el coordinador?', { title: 'Devolver la legalización', confirmLabel: 'Devolver' });
    if (!note) return;
    busy($('legReturn'), () => api('/legalization/return', jsonOpts('POST', { note }))).then(() => { showToast('Legalización devuelta al coordinador', 'success'); return load(); })
      .catch((err) => showToast(err.message || 'No se pudo devolver', 'error'));
  });

  if ($('showArchived')) $('showArchived').addEventListener('change', load);
  load();
})();
