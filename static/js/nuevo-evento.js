/* Nuevo evento (Fase 2): asistente cuyos pasos y campos los define la PLANTILLA DE EVENTO (GET /api/event-template; la diseña un admin en Configuración › Diseñar plantilla para eventos).
   La de fábrica pide lo mismo que antes. El POST /api/events es el de siempre: los campos base y los interruptores van en el nivel superior (columnas de events, las mismas de Parámetros) y los campos
   personalizados dentro de `extra`. El servidor vuelve a validar todo. Los controles los pinta static/js/event-field-render.js (todo texto del administrador va escapado).
   Contrato para quien agregue el selector de cliente (f2/evento-desde-eventos): el campo «client» se pinta de solo lectura con el nombre del cliente; el cliente que se envía es SIEMPRE el de `#nuevoEventoRoot` →
   data-tenant-id (se lee al enviar, así que basta con actualizarlo). Al terminar de pintar se emite el evento `gw:newevent-rendered` en `document` ({form, template}).
   Delegación de eventos; mensajes con showToast/showPrompt. */
(function () {
  'use strict';
  const root = document.getElementById('nuevoEventoRoot');
  const form = document.getElementById('newEventForm');
  if (!root || !form || !window.EventFields) return;
  const EF = window.EventFields;

  const STAFF_ROLE = root.dataset.staffRole;
  const PURE_COORDINATOR = root.dataset.pureCoordinator === 'true';
  const STAFF_ID = root.dataset.staffId ? parseInt(root.dataset.staffId, 10) : null;
  const tenantId = () => root.dataset.tenantId;
  const PICK_TENANT = root.dataset.pickTenant === 'true';          // entrada desde la pestaña Eventos (/eventos/nuevo): el cliente se elige en el campo «Cliente»
  const AFTER_URL = root.dataset.afterUrl || '/clientes';
  let tenantBox = null;
  const COUNTRIES = ['Colombia', 'México', 'Argentina', 'Chile', 'Perú', 'Ecuador', 'Venezuela', 'Bolivia', 'Paraguay', 'Uruguay', 'Brasil', 'Panamá', 'Costa Rica', 'Guatemala', 'Honduras', 'El Salvador', 'Nicaragua', 'República Dominicana', 'Cuba', 'Puerto Rico', 'España', 'Estados Unidos', 'Canadá', 'Francia', 'Alemania', 'Italia', 'Reino Unido', 'Portugal', 'Países Bajos', 'Bélgica', 'Suiza', 'China', 'Japón', 'Corea del Sur', 'India', 'Australia'];
  const CODE_RE = /^[A-Za-z0-9._-]+$/;
  const CODE_HELP = 'El código del evento solo puede tener letras sin tilde, números, punto (.), guion (-) y guion bajo (_), sin espacios. Ejemplo: FERIA-2026.';
  const esc = EF.esc;
  const host = document.getElementById('nePanels');
  const nextBtn = document.getElementById('neNext');
  const busy = (btn, work) => (window.GW && GW.busy ? GW.busy(btn, work) : work());
  const panels = () => Array.prototype.slice.call(form.querySelectorAll('[data-gw-wizard-panel]'));
  const currentStep = () => parseInt(form.getAttribute('data-gw-step') || '0', 10);

  let tpl = null;                  // plantilla vigente
  let fields = {};                 // clave -> campo
  let sections = [];               // [{id, title, keys[]}] ya sin los campos ocultos para este usuario
  let ctx = {};
  let workdayRefresh = null;

  async function citiesFor(country) {
    try {
      const res = await fetch('/api/cities?country=' + encodeURIComponent(country));
      return res.ok ? await res.json() : [];
    } catch (e) { return []; }
  }
  async function superEventList() {
    if (!tenantId()) return [];                      // sin cliente elegido todavía
    try {
      const res = await fetch('/api/super-events?tenant_id=' + encodeURIComponent(tenantId()));
      return res.ok ? await res.json() : [];
    } catch (e) { return []; }
  }

  // ---- Pintar el asistente a partir de la plantilla.
  function hiddenForUser() {
    // El coordinador «puro» no elige comercial (el servidor se la deja vacía) y su coordinador es él mismo; las demás reglas las aplica el servidor.
    return PURE_COORDINATOR ? { commercial_staff_id: true } : {};
  }
  function build() {
    const hidden = hiddenForUser();
    sections = tpl.creation_layout.sections.map((s) => ({ id: s.id, title: s.title, keys: s.keys.filter((k) => fields[k] && !hidden[k]) })).filter((s) => s.keys.length);
    ctx.hidden = hidden;
    ctx.readonly = PURE_COORDINATOR ? { coordinator_staff_id: true } : {};
    host.innerHTML = sections.map((s, i) => {
      const last = i === sections.length - 1;
      return '<section class="gw-wizard__panel" data-gw-wizard-panel aria-labelledby="neT' + i + '"' + (i ? ' hidden' : '') + '>' +
        '<h3 class="gw-nuevo__panel-title" id="neT' + i + '" tabindex="-1">' + esc(s.title) + '</h3>' +
        '<div class="gw-fields-row gw-fields-row--2 gw-nuevo__cols3">' + s.keys.map((k) => EF.renderField(fields[k], { ctx: ctx })).join('') + '</div>' +
        (last ? '<div id="neContactsWrap"><h4 class="gw-nuevo__section">Contactos del cliente</h4><p class="gw-hint">Por defecto entra el contacto principal del cliente en el CRM; puedes elegir otros, agregar uno a mano o poner varios. El principal recibe el informe final y la encuesta.</p><div id="neContacts"></div></div><div id="neInvWrap"><h4 class="gw-nuevo__section">Inventario</h4><p class="gw-hint">Productos del catálogo que pide este evento. Almacén registra después lo que sale, vuelve y se consume.</p><div id="neInventory"></div></div><h4 class="gw-nuevo__section">Resumen</h4><div class="gw-nuevo__summary" id="neSummary" aria-live="polite"></div>' : '') +
        '</section>';
    }).join('');
    const mounted = EF.afterMount(form, { loadCities: citiesFor, geoUrl: root.dataset.geoUrl, fields: fields });          // país/ciudad con la lista fija de la plataforma (GWGeo); si no carga, sugerencias del servidor
    EF.bind(form, { fields: fields, loadCities: citiesFor });
    if (!workdayRefresh) workdayRefresh = EF.bindWorkday(form); else workdayRefresh();          // Jornada en vivo (Fase 5): se recalcula al digitar las horas; el enganche se hace UNA vez
    applyDefaults();                // los valores por defecto se ponen en el campo de texto; el combobox los toma al engancharse (Colombia/Bogotá)
    addSuperEventButton();
    mountInventory();
    mountContacts();
    nextBtn.disabled = false;
    if (window.GW && GW.wizard) GW.wizard.go(form, 0);
    document.dispatchEvent(new CustomEvent('gw:newevent-rendered', { detail: { form: form, template: tpl, enhanced: mounted } }));
  }
  // Inventario (Fase 5): los productos activos del catálogo se piden aquí como cantidades; se guardan justo después de crear el evento (PUT /api/events/<id>/inventory-plan).
  let invCtrl = null;
  async function mountInventory() {
    invCtrl = null;
    const box = document.getElementById('neInventory'), wrap = document.getElementById('neInvWrap');
    if (!box || !window.GWInvPlan) { if (wrap) wrap.hidden = true; return; }
    try { invCtrl = await GWInvPlan.mount(box, { eventId: null, saveButton: false, icons: root.dataset.icons || undefined }); } catch (e) { invCtrl = null; }
    if (!invCtrl || !invCtrl.visible || invCtrl.empty) { wrap.hidden = true; invCtrl = null; }
  }
  // Contactos del cliente (16-nov-2026): se envían dentro del POST /api/events; cambian solos al cambiar de cliente.
  let contactsCtrl = null;
  async function mountContacts() {
    contactsCtrl = null;
    const box = document.getElementById('neContacts'), wrap = document.getElementById('neContactsWrap');
    if (!box || !window.GWEventContacts) { if (wrap) wrap.hidden = true; return; }
    try { contactsCtrl = await GWEventContacts.mount(box, { eventId: null, tenantId: tenantId() || null }); } catch (e) { contactsCtrl = null; }
    if (!contactsCtrl) wrap.hidden = true;
  }
  const control = (key, part) => form.querySelector('[data-evf-key="' + key + '"][data-evf-part="' + (part || 'v') + '"]');
  function setIfEmpty(key, value) { const c = control(key); if (c && !c.value) c.value = value; }
  function applyDefaults() {
    setIfEmpty('country', 'Colombia');          // País/Ciudad por defecto (2026-09-17, pedido explícito): Colombia/Bogotá, editables
    setIfEmpty('city', 'Bogotá');
    const country = control('country');
    if (country) country.dispatchEvent(new Event('change', { bubbles: true }));          // carga las ciudades del país inicial
    if (PURE_COORDINATOR && STAFF_ID) { const c = control('coordinator_staff_id'); if (c) c.value = String(STAFF_ID); }
    if (STAFF_ROLE === 'comercial' && STAFF_ID) setIfEmpty('commercial_staff_id', String(STAFF_ID));          // la comercial que crea queda como comercial (editable)
  }

  // ---- Superevento: lista del cliente y botón «Nuevo superevento» junto al campo.
  function addSuperEventButton() {
    const holder = form.querySelector('[data-evf-field="super_event_id"]');
    if (!holder || holder.querySelector('#newSuperBtn')) return;
    holder.insertAdjacentHTML('beforeend', '<button type="button" id="newSuperBtn" class="gw-btn gw-btn--secondary gw-btn--sm">Nuevo superevento</button> <button type="button" id="manageSuperBtn" class="gw-btn gw-btn--secondary gw-btn--sm">Administrar</button>');
    loadSuperEvents();
  }
  async function loadSuperEvents(selectedId) {
    const select = control('super_event_id');
    if (!select) return;
    const list = await superEventList();
    select.innerHTML = '<option value="">— Ninguno —</option>' + list.map((s) => '<option value="' + esc(s.id) + '">' + esc(s.name) + ' (' + esc(s.events) + ' eventos)</option>').join('');
    select.value = selectedId ? String(selectedId) : '';
  }
  async function createSuperEvent(btn) {
    if (!tenantId()) { GW.wizard.go(form, 0); focusPanelTitle(); showToast('Primero elige el cliente del evento.', 'error'); return; }
    const name = await showPrompt('Nombre del superevento (ej. Congreso X):', { confirmLabel: 'Crear' });
    if (!name) return;
    await busy(btn, async () => {
      const res = await fetch('/api/super-events', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tenant_id: tenantId(), name }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { showToast(data.detail || 'No se pudo crear el superevento', 'error'); return; }
      await loadSuperEvents(data.id);
      showToast('Superevento creado y seleccionado', 'success');
    });
  }

  // ---- Valores y validación por paso (el servidor valida de nuevo).
  const readKey = (key) => EF.readField(fields[key], form);
  function labelOfControl(el) { const l = el && el.id ? form.querySelector('label[for="' + el.id + '"]') : null; return l ? l.textContent.replace('*', '').replace('(opcional)', '').trim() : ''; }
  function markInvalid(holder, on) {
    Array.prototype.forEach.call(holder.querySelectorAll('input, select, textarea'), (el) => { if (on) el.setAttribute('aria-invalid', 'true'); else el.removeAttribute('aria-invalid'); });
  }
  function validatePanel(panel) {
    const keys = Array.prototype.map.call(panel.querySelectorAll('[data-evf-field]'), (n) => n.getAttribute('data-evf-field'));
    for (const key of keys) {
      const f = fields[key];
        if (f && f.type === 'client') {
        if (PICK_TENANT && !tenantId()) {                      // el cliente debe ser uno de la lista, no cualquier texto
          const inp = panel.querySelector('[data-evf-field="client"] input');
          if (inp) { inp.setAttribute('aria-invalid', 'true'); inp.focus(); }
          showToast('Elige un cliente de la lista.', 'error');
          return false;
        }
        continue;
      }
      if (!f) continue;
      const holder = panel.querySelector('[data-evf-field="' + key + '"]');
      const first = holder.querySelector('input, select, textarea');
      const v = readKey(key);
      let msg = EF.validateValue(f, v);
      if (!msg && key === 'event_code' && v && !CODE_RE.test(v)) msg = CODE_HELP;
      if (msg) {
        markInvalid(holder, true);
        if (first) first.focus();
        showToast(msg.indexOf('es obligatorio') > -1 ? 'Completa este campo: ' + (labelOfControl(first) || f.title) : msg, 'error');
        return false;
      }
      markInvalid(holder, false);
    }
    return true;
  }
  function validateUpTo(last) {
    const ps = panels();
    for (let i = 0; i <= last && i < ps.length; i++) {
      if (!validatePanel(ps[i])) { GW.wizard.go(form, i); focusPanelTitle(); return false; }
    }
    return true;
  }
  function focusPanelTitle() {
    window.setTimeout(() => {
      const p = panels()[currentStep()];
      const h = p && p.querySelector('.gw-nuevo__panel-title');
      if (h) h.focus({ preventScroll: false });
      if (currentStep() === panels().length - 1) renderSummary();
    }, 0);
  }

  // En captura: se revisa el paso ANTES de que gw-ui.js avance. Si hay un campo mal, el asistente no se mueve.
  form.addEventListener('click', (e) => {
    const next = e.target.closest('[data-gw-wizard-next]');
    if (next) {
      const idx = currentStep();
      if (!validatePanel(panels()[idx])) { e.stopPropagation(); return; }
      if (next.getAttribute('data-last') === 'true' && !validateUpTo(idx)) { e.stopPropagation(); return; }
      if (next.getAttribute('data-last') !== 'true') focusPanelTitle();
      return;
    }
    if (e.target.closest('[data-gw-wizard-prev]')) focusPanelTitle();
  }, true);

  form.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || !e.target.matches('input:not([type="color"]):not(.clock-time):not([list]):not([type="checkbox"])')) return;
    e.preventDefault();                       // Enter avanza el asistente en vez de enviar a medias
    nextBtn.click();
  });

  // ---- Resumen del último paso (todo escapado).
  function summaryText(f, key) {
    if (f.type === 'client') return (PICK_TENANT ? (control('client') && control('client').value || '') : (root.dataset.tenantName || '')).trim() || '—';
    if (f.type === 'workday') return EF.workdayText(control('event_time_start') && control('event_time_start').value, control('event_time_end') && control('event_time_end').value);
    if (f.type === 'commercial' || f.type === 'coordinator' || f.type === 'super_event' || f.type === 'event_type') {
      const c = control(key); const o = c && c.options && c.options[c.selectedIndex];
      return c && c.value && o ? o.textContent.replace(/ \(\d+ eventos\)$/, '') : '—';
    }
    return EF.formatValue(f, readKey(key), ctx) || '—';
  }
  function renderSummary() {
    const box = document.getElementById('neSummary');
    if (!box) return;
    box.innerHTML = sections.map((s, i) =>
      '<div class="gw-nuevo__sumcard"><div class="gw-nuevo__sumhead"><span>' + esc(s.title) + '</span>' +
      '<button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-ne-goto="' + i + '" aria-label="Cambiar ' + esc(s.title.toLowerCase()) + '">Cambiar</button></div>' +
      '<dl class="gw-nuevo__dl">' + s.keys.map((k) => '<dt>' + esc(fields[k].title) + '</dt><dd>' + esc(summaryText(fields[k], k)) + '</dd>').join('') + '</dl></div>'
    ).join('');
  }

  // Delegación: «Cambiar» del resumen vuelve al paso; «Nuevo superevento».
  form.addEventListener('click', (e) => {
    const go = e.target.closest('[data-ne-goto]');
    if (go) { GW.wizard.go(form, parseInt(go.getAttribute('data-ne-goto'), 10)); focusPanelTitle(); return; }
    const sup = e.target.closest('#newSuperBtn');
    if (sup) createSuperEvent(sup);
    if (e.target.closest('#manageSuperBtn') && window.GWSuper) GWSuper.manage({ tenantId: tenantId(), role: STAFF_ROLE, onChange: () => loadSuperEvents(control('super_event_id') && control('super_event_id').value) });
  });

  // ---- Armar el cuerpo del POST /api/events: base y interruptores en el nivel superior (sus columnas), personalizados en `extra`.
  function buildPayload() {
    const payload = { tenant_id: tenantId() }, extra = {};
    sections.forEach((s) => s.keys.forEach((key) => {
      const f = fields[key];
      if (f.type === 'client') return;
      const v = readKey(key);
      if (f.type === 'switch') { payload[f.config.switch] = !!v; return; }
      if (v == null) return;
      if (key === 'bandana') { payload.bandana_color = v[0].hex; payload.bandana_color_name = v[0].name || null; return; }
      if (key.indexOf('c_') === 0) { extra[key] = f.type === 'commercial' || f.type === 'coordinator' ? Number(v) : v; return; }
      payload[key] = v;
    }));
    if (Object.keys(extra).length) payload.extra = extra;
    const contacts = contactsCtrl ? contactsCtrl.value() : null;          // null = no cargaron: el servidor pone el contacto principal del CRM
    if (contacts) payload.contacts = contacts;
    return payload;
  }

  // ---- Crear el evento (el último «Continuar» emite gw:wizard-finish).
  async function submitEvent() {
    if (!validateUpTo(panels().length - 1)) return;
    if (contactsCtrl && !contactsCtrl.valid()) { const pr = GWEventContacts.problem(contactsCtrl.value()); showToast(pr || 'Revisa los contactos del cliente.', 'error'); return; }
    const payload = buildPayload();
    await busy(nextBtn, async () => {
      let res;
      try {
        res = await fetch('/api/events', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      } catch (e) { showToast('Sin conexión: no se pudo crear el evento. Revisa tu red e inténtalo de nuevo.', 'error'); return; }
      if (res.ok) {
        const created = await res.json().catch(() => ({}));
        if (invCtrl && created.id && invCtrl.dirty()) {
          const inv = await invCtrl.save(created.id);
          if (!inv.ok) {
            showToast('El evento se creó, pero el inventario no se guardó: ' + inv.error + ' Ábrelo desde el calendario para reintentarlo.', 'error');
            window.setTimeout(() => { window.location.href = AFTER_URL; }, 4000);
            return;
          }
        }
        showToast('Evento creado', 'success');
        window.location.href = AFTER_URL;
        return;
      }
      const err = await res.json().catch(() => ({}));
      showToast(typeof err.detail === 'string' ? err.detail : 'No se pudo crear el evento', 'error');
    });
  }
  form.addEventListener('gw:wizard-finish', submitEvent);
  form.addEventListener('submit', (e) => { e.preventDefault(); });
  form.addEventListener('input', (e) => { if (e.target.getAttribute && e.target.getAttribute('aria-invalid')) e.target.removeAttribute('aria-invalid'); });

  // Entrada desde Eventos: la lista de clientes es la de siempre (GET /api/tenants, ya limitada a lo que el rol puede ver). Un solo cliente visible = ya viene elegido.
  async function setupTenantPicker() {
    const input = control('client');
    if (!input || !window.GWCombobox) return;
    tenantBox = GWCombobox.attach(input, { options: [] });
    input.addEventListener('gw:combobox-change', (e) => {
      root.dataset.tenantId = String(e.detail.value || '');
      root.dataset.tenantName = (e.detail.label || input.value || '').trim();
      loadSuperEvents();
      if (contactsCtrl) contactsCtrl.setTenant(root.dataset.tenantId || null);
    });
    try {
      const res = await fetch('/api/tenants');
      if (!res.ok) throw new Error('tenants');
      const tenants = await res.json();
      tenantBox.setOptions(tenants.map((t) => ({ value: t.id, label: t.name, hint: t.client_code || '' })));
      if (tenants.length === 1) tenantBox.setValue(tenants[0].id);
    } catch (e) { showToast('No se pudo cargar la lista de clientes. Recarga la página.', 'error'); }
  }

  // ---- Arranque: leer la plantilla.
  async function init() {
    const loading = document.getElementById('neLoading'), err = document.getElementById('neError');
    err.hidden = true; loading.hidden = false; nextBtn.disabled = true;
    try {
      const res = await fetch('/api/event-template', { cache: 'no-store' });
      if (!res.ok) throw new Error('http ' + res.status);
      tpl = await res.json();
    } catch (e) {
      loading.hidden = true; err.hidden = false;
      return;
    }
    fields = {};
    tpl.fields.forEach((f) => { if (!f.retired) fields[f.key] = f; });
    let eventTypes = [];          // lista de tipos de evento (Configuración › Tipos de evento); si no carga, el campo queda con «Sin categoría» y el evento se crea igual
    try { const tr = await fetch('/api/event-types', { cache: 'no-store' }); if (tr.ok) eventTypes = (await tr.json()).types || []; } catch (e) { eventTypes = []; }
    ctx = { countries: COUNTRIES, people: tpl.people || {}, superEvents: [], eventTypes: eventTypes, tenantName: root.dataset.tenantName || '', pickTenant: PICK_TENANT };
    loading.hidden = true;
    build();
    if (PICK_TENANT) setupTenantPicker();
  }
  document.getElementById('neRetry').addEventListener('click', init);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
