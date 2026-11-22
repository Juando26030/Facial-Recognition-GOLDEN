/* Pantalla /plataforma (SaaS, pieza 1; docs/27_SAAS_EMPRESAS.md): empresas, plan, límites propios, primer administrador y consumo. Solo super_admin.
   Delegación de eventos, todo el texto que viene del servidor entra con textContent, mensajes con showToast/showConfirm. Las ventanas de datos NO se cierran al hacer clic afuera. */
(function () {
  'use strict';
  const box = document.getElementById('orgs');
  if (!box) return;
  const orgModal = document.getElementById('orgModal');
  const adminModal = document.getElementById('adminModal');
  const passModal = document.getElementById('passModal');
  const orgForm = document.getElementById('orgForm');
  const adminForm = document.getElementById('adminForm');
  const planSelect = document.getElementById('orgPlan');
  const limitFields = document.getElementById('limitFields');
  let orgs = [];
  let plans = [];
  let keys = [];
  let accountsReady = false;
  let editingId = null;
  let adminOrgId = null;

  async function api(path, opts) {
    const res = await fetch(path, Object.assign({ credentials: 'same-origin' }, opts));
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo completar la acción. Intenta de nuevo.');
    return data;
  }
  const send = (method, path, body) => api(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  const fail = (err) => showToast(err.message, 'error');

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  const open = (modal) => { modal.setAttribute('data-open', 'true'); const first = modal.querySelector('input, select, textarea, button.gw-btn--primary'); if (first) first.focus(); };
  const close = (modal) => modal.setAttribute('data-open', 'false');
  const number = (n) => Number(n || 0).toLocaleString('es-CO');
  const planOf = (key) => plans.find((p) => p.key === key);

  function limitText(value, numeric) {
    if (!numeric) return value ? 'Sí' : 'No';
    return value == null ? 'Sin límite' : number(value);
  }

  function usageLine(label, used, limit) {
    const row = el('li');
    row.append(el('span', null, label + ': '));
    row.append(el('strong', null, number(used) + (limit === undefined ? '' : ' de ' + (limit == null ? 'sin límite' : number(limit)))));
    if (limit != null && limit !== undefined && used >= limit) {
      row.append(document.createTextNode(' '));
      row.append(el('span', 'gw-badge gw-badge--warn', 'Llegó al tope'));
    }
    return row;
  }

  function card(org) {
    const node = el('article', 'gw-card gw-stack');
    node.dataset.org = org.id;
    const head = el('div', 'gw-row gw-row--between');
    const title = el('div', 'gw-row');
    title.append(el('h3', 'gw-card__title', org.name));
    title.append(el('span', 'gw-badge gw-badge--info', org.internal ? 'Cuenta interna' : 'Plan ' + org.plan_label));
    if (org.status === 'suspended') title.append(el('span', 'gw-badge gw-badge--err', 'Suspendida'));
    head.append(title);
    const actions = el('div', 'gw-row');
    const button = (action, text, cls) => { const b = el('button', 'gw-btn gw-btn--sm ' + (cls || 'gw-btn--secondary'), text); b.type = 'button'; b.dataset.action = action; b.dataset.id = org.id; return b; };
    actions.append(button('edit-org', 'Editar'));
    const adminBtn = button('new-admin', 'Crear administrador');
    if (!org.internal && !accountsReady) { adminBtn.disabled = true; adminBtn.title = 'Bloqueado: el aislamiento entre empresas está apagado'; }
    actions.append(adminBtn);
    if (!org.internal) actions.append(org.status === 'suspended' ? button('reactivate', 'Reactivar') : button('suspend', 'Suspender', 'gw-btn--danger-outline'));
    head.append(actions);
    node.append(head);

    const meta = [org.legal_name, org.nit ? 'NIT ' + org.nit : '', org.contact_email, org.contact_phone].filter(Boolean).join(' · ');
    if (meta) node.append(el('p', 'gw-hint', meta));

    const u = org.usage || {};
    const e = org.entitlements || {};
    const list = el('ul', 'gw-stack');
    list.append(usageLine('Eventos este mes', u.events_per_month, e.events_per_month));
    list.append(usageLine('Usuarios activos', u.users, e.users));
    list.append(usageLine('Evento más grande (asistentes)', u.attendees_per_event, e.attendees_per_event));
    list.append(usageLine('Asistentes en total', u.attendees_total));
    list.append(usageLine('Eventos en total', u.events_total));
    list.append(usageLine('Clientes', u.clients));
    node.append(list);

    if (!org.internal) {
      const features = keys.filter((k) => !k.numeric).map((k) => k.label + ': ' + limitText(e[k.key], false)).join(' · ');
      node.append(el('p', 'gw-hint', features));
    }
    if (org.notes) node.append(el('p', 'gw-hint', 'Notas: ' + org.notes));
    return node;
  }

  function render() {
    box.replaceChildren();
    box.setAttribute('aria-busy', 'false');
    if (!orgs.length) { box.append(el('p', 'gw-hint', 'Todavía no hay empresas. Usa «Nueva empresa» para crear la primera.')); return; }
    orgs.forEach((org) => box.append(card(org)));
    document.getElementById('isolationAlert').hidden = accountsReady;
  }

  async function load() {
    try {
      const data = await api('/api/platform/orgs');
      orgs = data.orgs || [];
      plans = data.plans || [];
      keys = data.keys || [];
      accountsReady = !!data.external_accounts_ready;
      render();
    } catch (err) {
      box.replaceChildren(el('p', 'gw-hint', 'No se pudieron cargar las empresas. Recarga la página.'));
      box.setAttribute('aria-busy', 'false');
      fail(err);
    }
  }

  // ---------- formulario de empresa ----------
  function planSummary() {
    const plan = planOf(planSelect.value);
    const target = document.getElementById('planSummary');
    if (!plan) { target.textContent = ''; return; }
    target.textContent = 'De fábrica: ' + keys.map((k) => k.label + ' ' + limitText(plan.values[k.key], k.numeric).toLowerCase()).join(' · ');
  }

  function buildLimitFields(own) {
    limitFields.replaceChildren();
    keys.forEach((k) => {
      const field = el('div', 'gw-field');
      const id = 'lim_' + k.key;
      const label = el('label', 'gw-label', k.label);
      label.htmlFor = id;
      field.append(label);
      const select = el('select', 'gw-select');
      select.id = id;
      select.dataset.limit = k.key;
      const options = k.numeric ? [['plan', 'Lo del plan'], ['own', 'Valor propio'], ['none', 'Sin límite']] : [['plan', 'Lo del plan'], ['yes', 'Sí'], ['no', 'No']];
      options.forEach(([value, text]) => { const o = el('option', null, text); o.value = value; select.append(o); });
      field.append(select);
      const has = Object.prototype.hasOwnProperty.call(own, k.key);
      if (k.numeric) {
        const input = el('input', 'gw-input');
        input.type = 'number'; input.min = '0'; input.step = '1'; input.inputMode = 'numeric';
        input.dataset.limitValue = k.key;
        input.setAttribute('aria-label', k.label + ': valor propio');
        select.value = !has ? 'plan' : (own[k.key] == null ? 'none' : 'own');
        input.value = has && own[k.key] != null ? own[k.key] : '';
        input.hidden = select.value !== 'own';
        field.append(input);
      } else {
        select.value = !has ? 'plan' : (own[k.key] ? 'yes' : 'no');
      }
      field.append(el('p', 'gw-hint', k.help));
      limitFields.append(field);
    });
  }

  function readLimits() {
    const out = {};
    limitFields.querySelectorAll('select[data-limit]').forEach((select) => {
      const key = select.dataset.limit;
      if (select.value === 'plan') return;
      if (select.value === 'none') out[key] = null;
      else if (select.value === 'yes') out[key] = true;
      else if (select.value === 'no') out[key] = false;
      else {
        const raw = limitFields.querySelector('input[data-limit-value="' + key + '"]').value.trim();
        if (!/^\d+$/.test(raw)) throw new Error('Escribe un número entero (0 o más) en «' + select.previousElementSibling.textContent + '», o elige «Lo del plan».');
        out[key] = parseInt(raw, 10);
      }
    });
    return out;
  }

  function openOrgForm(org) {
    editingId = org ? org.id : null;
    orgForm.reset();
    document.getElementById('orgModalTitle').textContent = org ? 'Editar empresa' : 'Nueva empresa';
    planSelect.replaceChildren();
    plans.filter((p) => p.sellable).forEach((p) => { const o = el('option', null, p.label); o.value = p.key; planSelect.append(o); });
    const internal = !!(org && org.internal);
    orgModal.querySelector('[data-not-internal]').hidden = internal;
    if (org) {
      ['name', 'legal_name', 'nit', 'contact_email', 'contact_phone', 'notes'].forEach((f) => { orgForm.elements[f].value = org[f] || ''; });
      if (!internal) planSelect.value = org.plan;
    }
    buildLimitFields(org && !internal ? (org.own_entitlements || {}) : {});
    planSummary();
    open(orgModal);
  }

  orgForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = {};
    ['name', 'legal_name', 'nit', 'contact_email', 'contact_phone', 'notes'].forEach((f) => { body[f] = orgForm.elements[f].value.trim(); });
    if (body.name.length < 2) { showToast('Escribe el nombre de la empresa.', 'error'); orgForm.elements.name.focus(); return; }
    const current = orgs.find((o) => o.id === editingId);
    const save = document.getElementById('orgSave');
    try {
      if (!(current && current.internal)) { body.plan = planSelect.value; body.entitlements = readLimits(); }
      save.disabled = true;
      if (editingId) await send('PATCH', '/api/platform/orgs/' + editingId, body);
      else await send('POST', '/api/platform/orgs', body);
      close(orgModal);
      showToast(editingId ? 'Empresa actualizada.' : 'Empresa creada. Ahora puedes crear su administrador.', 'success');
      await load();
    } catch (err) { fail(err); } finally { save.disabled = false; }
  });

  planSelect.addEventListener('change', planSummary);
  limitFields.addEventListener('change', (e) => {
    const select = e.target.closest('select[data-limit]');
    if (!select) return;
    const input = limitFields.querySelector('input[data-limit-value="' + select.dataset.limit + '"]');
    if (input) { input.hidden = select.value !== 'own'; if (!input.hidden) input.focus(); }
  });

  // ---------- administrador ----------
  adminForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = {};
    ['username', 'full_name', 'email', 'phone'].forEach((f) => { body[f] = adminForm.elements[f].value.trim(); });
    const missing = ['username', 'full_name', 'email', 'phone'].find((f) => !body[f]);
    if (missing) { showToast('Completa todos los datos del administrador.', 'error'); adminForm.elements[missing].focus(); return; }
    const save = document.getElementById('adminSave');
    save.disabled = true;
    try {
      const out = await send('POST', '/api/platform/orgs/' + adminOrgId + '/admin', body);
      close(adminModal);
      adminForm.reset();
      document.getElementById('passUser').textContent = out.username;
      document.getElementById('passValue').textContent = out.temp_password;
      open(passModal);
      await load();
    } catch (err) { fail(err); } finally { save.disabled = false; }
  });

  async function setStatus(org, action) {
    const suspend = action === 'suspend';
    const ok = await showConfirm(suspend
      ? '¿Suspender a «' + org.name + '»? No podrá crear eventos ni cuentas nuevas. No se borra nada y se puede reactivar cuando quieras.'
      : '¿Reactivar a «' + org.name + '»? Vuelve a poder crear eventos y cuentas según su plan.',
      suspend ? { variant: 'warning', confirmLabel: 'Suspender' } : { confirmLabel: 'Reactivar' });
    if (!ok) return;
    try {
      await send('POST', '/api/platform/orgs/' + org.id + '/' + action);
      showToast(suspend ? 'Empresa suspendida.' : 'Empresa reactivada.', 'success');
      await load();
    } catch (err) { fail(err); }
  }

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    const org = orgs.find((o) => String(o.id) === btn.dataset.id);
    if (action === 'new-org') openOrgForm(null);
    else if (action === 'edit-org' && org) openOrgForm(org);
    else if (action === 'new-admin' && org) {
      adminOrgId = org.id;
      adminForm.reset();
      document.getElementById('adminOrgName').textContent = org.name;
      open(adminModal);
    } else if ((action === 'suspend' || action === 'reactivate') && org) setStatus(org, action);
    else if (action === 'close-modal') close(btn.closest('.gw-modal-backdrop'));
    else if (action === 'close-pass') {
      document.getElementById('passValue').textContent = '';          // la contraseña no queda en la página
      close(passModal);
    } else if (action === 'copy-pass') {
      const value = document.getElementById('passValue').textContent;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value).then(() => showToast('Contraseña copiada.', 'success'), () => showToast('No se pudo copiar: selecciónala y cópiala a mano.', 'error'));
      } else showToast('Selecciona la contraseña y cópiala a mano.', 'info');
    }
  });

  load();
})();
