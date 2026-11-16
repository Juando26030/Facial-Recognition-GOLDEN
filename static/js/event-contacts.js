/* Bloque «Contactos del cliente» del evento (16-nov-2026): varios contactos, cada uno con nota de quién es y para qué; UNO principal, que recibe el informe final y la encuesta.
   Se eligen de los contactos del CRM del cliente (el principal de la cuenta viene elegido por defecto) o se escriben a mano (nombre y teléfono; el correo es opcional, pero sin correo no recibe nada).
   Dos modos, como GWInvPlan: con evento (eventId: lee y guarda en /api/events/<id>/contacts) y borrador (sin eventId: «Nuevo evento»; value() va dentro del POST /api/events).
   API: GWEventContacts.mount(contenedor, { eventId, tenantId, onChange }) -> Promise<controlador { dirty(), value(), valid(), save(eventId?), setTenant(id), loaded }>.
   Sin innerHTML con datos de personas: todo se arma con el DOM y .value / textContent. Mensajes con showToast. Pura: GWEventContacts.normalize (se prueba con Node). */
(function (root) {
  'use strict';
  const MAX = 10;
  const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

  /* Pura: la lista tal como se envía: sin filas vacías, con exactamente un principal (si ninguno lo es, el primero). */
  function normalize(rows) {
    const out = (rows || []).filter((r) => r && (String(r.name || '').trim() || String(r.phone || '').trim() || String(r.email || '').trim())).map((r) => ({
      crm_contact_id: r.crm_contact_id || null, name: String(r.name || '').trim(), phone: String(r.phone || '').trim(), email: String(r.email || '').trim(), note: String(r.note || '').trim(), is_primary: !!r.is_primary }));
    let seen = false;
    out.forEach((r) => { if (r.is_primary && !seen) seen = true; else r.is_primary = false; });
    if (out.length && !seen) out[0].is_primary = true;
    return out;
  }
  /* Pura: primer problema de la lista o '' si está bien. */
  function problem(rows) {
    const list = normalize(rows);
    for (let i = 0; i < list.length; i++) {
      if (!list[i].name) return 'El contacto ' + (i + 1) + ' necesita un nombre.';
      if (list[i].email && !EMAIL.test(list[i].email)) return 'El correo de «' + list[i].name + '» no parece un correo válido.';
    }
    return list.length > MAX ? 'Un evento admite hasta ' + MAX + ' contactos.' : '';
  }

  function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }

  async function mount(box, opts) {
    opts = opts || {};
    if (!box) return null;
    let eventId = opts.eventId || null, tenantId = opts.tenantId || null;
    let rows = [], options = [], dirtyFlag = false, loaded = false, uid = 0;
    const ctrl = { loaded: false, dirty: () => dirtyFlag, value: () => (loaded ? normalize(rows) : null), valid: () => !loaded || !problem(rows), save, setTenant };
    const touch = () => { dirtyFlag = true; if (opts.onChange) opts.onChange(); };

    async function fetchOptions() {
      try {
        const url = eventId ? '/api/events/' + eventId + '/contacts' : (tenantId ? '/api/event-contacts/options?tenant_id=' + encodeURIComponent(tenantId) : null);
        if (!url) return { contacts: [], options: [], ok: !eventId };
        const r = await fetch(url, { cache: 'no-store' });
        if (!r.ok) return { contacts: [], options: [], ok: false };
        const d = await r.json();
        return { contacts: eventId ? (d.contacts || []) : [], options: eventId ? (d.crm_options || []) : (d.contacts || []), ok: true };
      } catch (e) { return { contacts: [], options: [], ok: false }; }
    }
    async function load() {
      const d = await fetchOptions();
      options = d.options; loaded = d.ok; ctrl.loaded = d.ok;
      rows = d.contacts.map((c) => Object.assign({ _id: ++uid }, c));
      if (!eventId && !rows.length && options.length) {          // por defecto: el contacto principal de la cuenta en el CRM
        const o = options[0]; rows = [{ _id: ++uid, crm_contact_id: o.crm_contact_id, name: o.name, phone: o.phone, email: o.email, note: '', is_primary: true }];
      }
      dirtyFlag = false; paint();
    }
    async function setTenant(id) {
      if (eventId || id === tenantId) return;
      tenantId = id || null; await load();
    }

    function field(labelText, input) {
      const w = el('label', 'gw-field gw-evc__field'); w.appendChild(el('span', 'gw-label', labelText)); w.appendChild(input); return w;
    }
    function textInput(value, max, type, onInput) {
      const i = el('input', 'gw-input'); i.type = type || 'text'; i.maxLength = max; i.value = value || ''; i.addEventListener('input', () => { onInput(i.value); touch(); }); return i;
    }
    function card(r, idx) {
      const c = el('li', 'gw-evc__card' + (r.is_primary ? ' is-primary' : ''));
      const head = el('div', 'gw-evc__head');
      const rad = el('label', 'gw-check'), radio = el('input'); radio.type = 'radio'; radio.name = 'evcPrimary' + (eventId || 'new'); radio.checked = !!r.is_primary;
      radio.addEventListener('change', () => { rows.forEach((x) => { x.is_primary = x._id === r._id; }); touch(); paint(); });
      rad.appendChild(radio); rad.appendChild(el('span', 'gw-choice__text', r.is_primary ? 'Contacto principal (recibe el informe y la encuesta)' : 'Hacer principal'));
      const rm = el('button', 'gw-btn gw-btn--secondary gw-btn--sm', 'Quitar'); rm.type = 'button'; rm.setAttribute('aria-label', 'Quitar el contacto ' + (r.name || (idx + 1)));
      rm.addEventListener('click', () => { rows = rows.filter((x) => x._id !== r._id); if (rows.length && !rows.some((x) => x.is_primary)) rows[0].is_primary = true; touch(); paint(); });
      head.appendChild(rad); head.appendChild(rm); c.appendChild(head);
      const grid = el('div', 'gw-evc__grid');
      grid.appendChild(field('Nombre *', textInput(r.name, 200, 'text', (v) => { r.name = v; })));
      grid.appendChild(field('Teléfono', textInput(r.phone, 60, 'tel', (v) => { r.phone = v; })));
      grid.appendChild(field('Correo', textInput(r.email, 200, 'email', (v) => { r.email = v; })));
      grid.appendChild(field('Quién es en este evento (opcional)', textInput(r.note, 200, 'text', (v) => { r.note = v; })));
      c.appendChild(grid);
      if (r.is_primary && !EMAIL.test(String(r.email || '').trim())) c.appendChild(el('p', 'gw-hint gw-evc__warn', 'Sin correo no recibirá el informe ni la encuesta.'));
      return c;
    }
    function paint() {
      box.replaceChildren();
      if (!loaded) { box.appendChild(el('p', 'gw-hint', 'No se pudieron cargar los contactos del cliente. Se guardarán los que escribas aquí; si no escribes ninguno, el evento usa el contacto principal del CRM.')); }
      const list = el('ol', 'gw-evc__list');
      if (!rows.length) list.appendChild(el('li', 'gw-hint', options.length ? 'Este evento todavía no tiene contactos.' : 'Este cliente no tiene contactos en el CRM: agrega uno a mano.'));
      rows.forEach((r, i) => list.appendChild(card(r, i)));
      box.appendChild(list);
      const bar = el('div', 'gw-evc__bar');
      const free = options.filter((o) => !rows.some((r) => r.crm_contact_id === o.crm_contact_id));
      if (free.length) {
        const sel = el('select', 'gw-select'); sel.setAttribute('aria-label', 'Agregar un contacto del CRM');
        const first = el('option', null, 'Agregar un contacto del CRM…'); first.value = ''; sel.appendChild(first);
        free.forEach((o) => { const op = el('option', null, o.name + (o.job_title ? ' · ' + o.job_title : '') + (o.is_primary ? ' (principal en el CRM)' : '')); op.value = String(o.crm_contact_id); sel.appendChild(op); });
        sel.addEventListener('change', () => {
          const o = free.find((x) => String(x.crm_contact_id) === sel.value); if (!o) return;
          if (rows.length >= MAX) { showToast('Un evento admite hasta ' + MAX + ' contactos.', 'error'); return; }
          rows.push({ _id: ++uid, crm_contact_id: o.crm_contact_id, name: o.name, phone: o.phone, email: o.email, note: '', is_primary: !rows.length }); touch(); paint();
        });
        bar.appendChild(sel);
      }
      const add = el('button', 'gw-btn gw-btn--secondary', 'Agregar otro contacto (a mano)'); add.type = 'button';
      add.addEventListener('click', () => {
        if (rows.length >= MAX) { showToast('Un evento admite hasta ' + MAX + ' contactos.', 'error'); return; }
        rows.push({ _id: ++uid, crm_contact_id: null, name: '', phone: '', email: '', note: '', is_primary: !rows.length }); touch(); paint();
      });
      bar.appendChild(add); box.appendChild(bar);
    }

    async function save(id) {
      const target = id || eventId; if (!target || !loaded) return { ok: true };
      const msg = problem(rows); if (msg) return { ok: false, error: msg };
      try {
        const r = await fetch('/api/events/' + target + '/contacts', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ contacts: normalize(rows) }) });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) return { ok: false, error: typeof d.detail === 'string' ? d.detail : 'No se pudieron guardar los contactos.' };
        dirtyFlag = false; return { ok: true };
      } catch (e) { return { ok: false, error: 'Sin conexión: no se pudieron guardar los contactos.' }; }
    }
    await load();
    return ctrl;
  }
  const api = { mount, normalize, problem };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.GWEventContacts = api;
})(typeof window !== 'undefined' ? window : globalThis);
