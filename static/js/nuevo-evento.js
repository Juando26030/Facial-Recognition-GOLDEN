/* Nuevo evento (Fase 1.5): asistente de 4 pasos sobre el mismo POST /api/events de siempre.
   La configuración llega por data-* de #nuevoEventoRoot (nada de código en la plantilla). Delegación de eventos; mensajes con showToast/showPrompt. */
(function () {
  'use strict';
  const root = document.getElementById('nuevoEventoRoot');
  const form = document.getElementById('newEventForm');
  if (!root || !form) return;

  let TENANT_ID = root.dataset.tenantId;
  const PICK_TENANT = root.dataset.pickTenant === 'true';          // entrada desde la pestaña Eventos: el cliente se elige en el primer campo
  const AFTER_URL = root.dataset.afterUrl || '/clientes';
  const tenantInput = PICK_TENANT ? document.getElementById('neTenant') : null;
  const tenantBox = tenantInput && window.GWCombobox ? GWCombobox.attach(tenantInput, { options: [] }) : null;
  const STAFF_ROLE = root.dataset.staffRole;
  const PURE_COORDINATOR = root.dataset.pureCoordinator === 'true';
  const STAFF_ID = root.dataset.staffId ? parseInt(root.dataset.staffId, 10) : null;
  const COUNTRIES = ['Colombia', 'México', 'Argentina', 'Chile', 'Perú', 'Ecuador', 'Venezuela', 'Bolivia', 'Paraguay', 'Uruguay', 'Brasil', 'Panamá', 'Costa Rica', 'Guatemala', 'Honduras', 'El Salvador', 'Nicaragua', 'República Dominicana', 'Cuba', 'Puerto Rico', 'España', 'Estados Unidos', 'Canadá', 'Francia', 'Alemania', 'Italia', 'Reino Unido', 'Portugal', 'Países Bajos', 'Bélgica', 'Suiza', 'China', 'Japón', 'Corea del Sur', 'India', 'Australia'];

  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const field = (name) => form.querySelector('[name="' + name + '"]');
  const panels = () => Array.prototype.slice.call(form.querySelectorAll('[data-gw-wizard-panel]'));
  const currentStep = () => parseInt(form.getAttribute('data-gw-step') || '0', 10);
  const busy = (btn, work) => (window.GW && GW.busy ? GW.busy(btn, work) : work());

  document.getElementById('countryList').innerHTML = COUNTRIES.map((c) => '<option value="' + esc(c) + '">').join('');
  document.querySelectorAll('.clock-time').forEach((input) => {
    attachClockPicker(input);
    // El reloj se abre con clic; con teclado, Enter o Espacio hacen lo mismo.
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
  });
  field('bandana_color').value = '#D4AF37';            // dorado Golden por defecto (la plantilla no lleva colores escritos)
  ColorLibrary.attach(field('bandana_color'), field('bandana_color_name'));

  async function loadCitiesFor(country) {
    const cityDatalist = document.getElementById('cityList');
    if (!country) { cityDatalist.innerHTML = ''; return; }
    try {
      const res = await fetch('/api/cities?country=' + encodeURIComponent(country));
      const cities = res.ok ? await res.json() : [];
      cityDatalist.innerHTML = cities.map((c) => '<option value="' + esc(c) + '">').join('');
    } catch (e) { cityDatalist.innerHTML = ''; }
  }
  document.getElementById('countryField').addEventListener('change', (e) => loadCitiesFor(e.target.value.trim()));
  // País/Ciudad por defecto (2026-09-17, pedido explícito): Colombia/Bogotá, editables; solo se precargan las sugerencias de ciudades.
  loadCitiesFor(document.getElementById('countryField').value.trim());

  let coordinatorsByLabel = {};
  async function loadCoordinatorOptions() {
    try {
      const res = await fetch('/api/staff/coordinators');
      const coords = res.ok ? await res.json() : [];
      coordinatorsByLabel = {};
      document.getElementById('coordinatorList').innerHTML = coords.map((c) => {
        const label = (c.full_name || c.username) + ' (' + c.username + ')';
        coordinatorsByLabel[label] = c.id;
        return '<option value="' + esc(label) + '">';
      }).join('');
      if (PURE_COORDINATOR) {          // coordinador puro: el evento queda a su nombre
        const self = coords.find((c) => c.id === STAFF_ID);
        if (self) field('coordinator_label').value = (self.full_name || self.username) + ' (' + self.username + ')';
      }
    } catch (e) { showToast('No se pudo cargar la lista de coordinadores. Recarga la página.', 'error'); }
  }
  loadCoordinatorOptions();

  // 2026-09-16 (pedido explícito): si quien crea es comercial, se preselecciona a sí misma (editable); admin+ tiene que elegir.
  let commercialsByLabel = {};
  async function loadCommercialOptions() {
    try {
      const res = await fetch('/api/staff/commercials');
      const commercials = res.ok ? await res.json() : [];
      commercialsByLabel = {};
      document.getElementById('commercialList').innerHTML = commercials.map((c) => {
        const label = (c.full_name || c.username) + ' (' + c.username + ')';
        commercialsByLabel[label] = c.id;
        return '<option value="' + esc(label) + '">';
      }).join('');
      if (STAFF_ROLE === 'comercial') {
        const self = commercials.find((c) => c.id === STAFF_ID);
        if (self) field('commercial_label').value = (self.full_name || self.username) + ' (' + self.username + ')';
      }
    } catch (e) { showToast('No se pudo cargar la lista de comerciales. Recarga la página.', 'error'); }
  }
  if (!PURE_COORDINATOR) loadCommercialOptions();

  async function loadSuperEvents(selectedId) {
    const select = document.getElementById('superEventSelect');
    let list = [];
    if (!TENANT_ID) { select.innerHTML = '<option value="">— Ninguno —</option>'; select.value = ''; return; }      // sin cliente elegido todavía
    try {
      const res = await fetch('/api/super-events?tenant_id=' + encodeURIComponent(TENANT_ID));
      list = res.ok ? await res.json() : [];
    } catch (e) { list = []; }
    select.innerHTML = '<option value="">— Ninguno —</option>' + list.map((s) => '<option value="' + esc(s.id) + '">' + esc(s.name) + ' (' + esc(s.events) + ' eventos)</option>').join('');
    select.value = selectedId ? String(selectedId) : '';
  }
  loadSuperEvents();

  // Entrada desde Eventos: la lista de clientes es la misma de siempre (GET /api/tenants), ya limitada a lo que el rol puede ver.
  async function loadTenantOptions() {
    if (!tenantBox) return;
    try {
      const res = await fetch('/api/tenants');
      if (!res.ok) throw new Error('tenants');
      const tenants = await res.json();
      tenantBox.setOptions(tenants.map((t) => ({ value: t.id, label: t.name, hint: t.client_code || '' })));
      if (tenants.length === 1) tenantBox.setValue(tenants[0].id);          // un solo cliente visible: ya viene elegido
    } catch (e) { showToast('No se pudo cargar la lista de clientes. Recarga la página.', 'error'); }
  }
  if (tenantInput) {
    tenantInput.addEventListener('gw:combobox-change', (e) => { TENANT_ID = String(e.detail.value || ''); loadSuperEvents(); });
    loadTenantOptions();
  }

  async function createSuperEvent(btn) {
    if (!TENANT_ID) { GW.wizard.go(form, 0); focusPanelTitle(); showToast('Primero elige el cliente del evento.', 'error'); return; }
    const name = await showPrompt('Nombre del superevento (ej. Congreso X):', { confirmLabel: 'Crear' });
    if (!name) return;
    await busy(btn, async () => {
      const res = await fetch('/api/super-events', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tenant_id: TENANT_ID, name }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { showToast(data.detail || 'No se pudo crear el superevento', 'error'); return; }
      await loadSuperEvents(data.id);
      showToast('Superevento creado y seleccionado', 'success');
    });
  }

  // ---- Validación por paso. Los campos del reloj son de solo lectura (el navegador no los valida), así que se revisan aquí.
  function validatePanel(panel) {
    const inputs = Array.prototype.slice.call(panel.querySelectorAll('input[name], select[name]'));
    for (const el of inputs) {
      if (el === tenantInput && !TENANT_ID) {                // el cliente debe ser uno de la lista, no cualquier texto
        el.setAttribute('aria-invalid', 'true');
        el.focus();
        showToast('Elige un cliente de la lista.', 'error');
        return false;
      }
      const empty = el.required && !String(el.value).trim();
      if (empty) {
        el.setAttribute('aria-invalid', 'true');
        el.focus();
        showToast('Completa este campo: ' + ((panel.querySelector('label[for="' + el.id + '"]') || {}).textContent || '').replace('*', '').trim(), 'error');
        return false;
      }
      if (!el.readOnly && !el.checkValidity()) {
        el.setAttribute('aria-invalid', 'true');
        el.reportValidity();
        return false;
      }
      el.removeAttribute('aria-invalid');
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
    if (e.key !== 'Enter' || !e.target.matches('input:not([type="color"]):not(.clock-time):not([list])')) return;
    e.preventDefault();                       // Enter avanza el asistente en vez de enviar a medias
    document.getElementById('neNext').click();
  });

  // ---- Resumen del último paso.
  function labelOf(name) { const v = (field(name) || {}).value || ''; return v.trim() || '—'; }
  function renderSummary() {
    const sel = document.getElementById('superEventSelect');
    const superLabel = sel && sel.value ? sel.options[sel.selectedIndex].textContent : 'Ninguno';
    const color = (field('bandana_color').value || '').trim();
    const colorName = labelOf('bandana_color_name');
    const groups = [
      { step: 0, title: 'Datos', rows: (PICK_TENANT ? [['Cliente', labelOf('tenant_label')]] : []).concat([['Código', labelOf('event_code')], ['Nombre', labelOf('name')], ['País y ciudad', labelOf('country') + ', ' + labelOf('city')], ['Lugar', labelOf('location')], ['Dirección', labelOf('address')]]) },
      { step: 1, title: 'Fechas', rows: [['Evento', labelOf('start_date') + ' a ' + labelOf('end_date') + ', ' + labelOf('event_time_start') + ' a ' + labelOf('event_time_end')], ['Montaje', labelOf('setup_date') + ', ' + labelOf('setup_time_start') + ' a ' + labelOf('setup_time_end')]] },
      { step: 2, title: 'Responsables', rows: [['Coordinador', labelOf('coordinator_label')]].concat(PURE_COORDINATOR ? [] : [['Comercial', labelOf('commercial_label')]]).concat([['Superevento', superLabel]]) },
    ];
    const box = document.getElementById('neSummary');
    box.innerHTML = groups.map((g) =>
      '<div class="gw-nuevo__sumcard"><div class="gw-nuevo__sumhead"><span>' + esc(g.title) + '</span>' +
      '<button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-ne-goto="' + g.step + '" aria-label="Cambiar ' + esc(g.title.toLowerCase()) + '">Cambiar</button></div>' +
      '<dl class="gw-nuevo__dl">' + g.rows.map((r) => '<dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd>').join('') + '</dl></div>'
    ).join('') +
      '<div class="gw-nuevo__sumcard"><dl class="gw-nuevo__dl"><dt>Pañoleta</dt><dd>' + esc(colorName === '—' ? color : colorName + ' (' + color + ')') + '</dd></dl></div>';
  }

  // Delegación: «Cambiar» del resumen vuelve al paso; «Nuevo superevento».
  form.addEventListener('click', (e) => {
    const go = e.target.closest('[data-ne-goto]');
    if (go) { GW.wizard.go(form, parseInt(go.getAttribute('data-ne-goto'), 10)); focusPanelTitle(); return; }
    const sup = e.target.closest('#newSuperBtn');
    if (sup) createSuperEvent(sup);
  });

  // ---- Crear el evento (el último «Continuar» emite gw:wizard-finish).
  async function submitEvent() {
    if (!validateUpTo(panels().length - 1)) return;
    const payload = Object.fromEntries(new FormData(form).entries());
    payload.tenant_id = TENANT_ID;
    delete payload.tenant_label;
    payload.super_event_id = payload.super_event_id ? parseInt(payload.super_event_id, 10) : null;

    const coordinatorId = coordinatorsByLabel[payload.coordinator_label];
    if (!coordinatorId) { GW.wizard.go(form, 2); focusPanelTitle(); showToast('Selecciona un coordinador válido de la lista.', 'error'); return; }
    payload.coordinator_staff_id = coordinatorId;
    delete payload.coordinator_label;

    if (!PURE_COORDINATOR) {
      const commercialId = commercialsByLabel[payload.commercial_label];
      if (!commercialId) { GW.wizard.go(form, 2); focusPanelTitle(); showToast('Selecciona una comercial válida de la lista.', 'error'); return; }
      payload.commercial_staff_id = commercialId;
    }
    delete payload.commercial_label;

    const btn = document.getElementById('neNext');
    await busy(btn, async () => {
      let res;
      try {
        res = await fetch('/api/events', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      } catch (e) { showToast('Sin conexión: no se pudo crear el evento. Revisa tu red e inténtalo de nuevo.', 'error'); return; }
      if (res.ok) {
        showToast('Evento creado', 'success');
        window.location.href = AFTER_URL;
        return;
      }
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || 'No se pudo crear el evento', 'error');
    });
  }
  form.addEventListener('gw:wizard-finish', submitEvent);
  form.addEventListener('submit', (e) => { e.preventDefault(); });
  form.addEventListener('input', (e) => { if (e.target.getAttribute && e.target.getAttribute('aria-invalid')) e.target.removeAttribute('aria-invalid'); });
})();
