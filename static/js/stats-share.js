/* Compartir estadísticas con un enlace de solo lectura (sin usuario ni contraseña). Se monta en #statsShare (evento o formulario). Todo se pinta con textContent. */
(function () {
  'use strict';
  var root = document.getElementById('statsShare');
  if (!root) return;
  var eventId = root.dataset.eventId, scope = root.dataset.scope, formId = root.dataset.formId || '';
  var base = '/api/events/' + encodeURIComponent(eventId) + '/stats-links';
  var DAYS = [[1, '1 día'], [3, '3 días'], [7, '7 días'], [15, '15 días'], [30, '30 días']];

  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function toast(msg, kind) { if (window.showToast) window.showToast(msg, kind || 'info'); }
  function copy(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return false; });
    return Promise.resolve(false);
  }

  var title = el('h3', 'gw-subtitle', scope === 'form' ? 'Compartir estadísticas de este formulario' : 'Compartir estadísticas del evento');
  var hint = el('p', 'gw-hint', 'Crea un enlace que muestra solo las estadísticas. Quien lo abre no necesita usuario ni contraseña, no puede descargar nada ni ver personas, y el enlace vence solo.');
  var row = el('div', null); row.style.cssText = 'display:flex; gap:var(--gw-sp-3); flex-wrap:wrap; align-items:flex-end;';
  var daysWrap = el('div', 'gw-field'); var daysLabel = el('label', 'gw-label', 'Vence en'); daysLabel.htmlFor = 'statsShareDays';
  var days = el('select', 'gw-select'); days.id = 'statsShareDays';
  DAYS.forEach(function (d) { var o = el('option', null, d[1]); o.value = d[0]; if (d[0] === 7) o.selected = true; days.appendChild(o); });
  daysWrap.append(daysLabel, days);
  var labelWrap = el('div', 'gw-field'); var labelLabel = el('label', 'gw-label', 'Para quién (opcional)'); labelLabel.htmlFor = 'statsShareLabel';
  var label = el('input', 'gw-input'); label.id = 'statsShareLabel'; label.type = 'text'; label.maxLength = 80; label.placeholder = 'Ej. Cliente, reunión del lunes';
  labelWrap.append(labelLabel, label);
  var create = el('button', 'gw-btn', 'Crear enlace'); create.type = 'button';
  row.append(daysWrap, labelWrap, create);
  var result = el('div', null); result.setAttribute('aria-live', 'polite'); result.style.marginTop = 'var(--gw-sp-3)';
  var listBox = el('div', null); listBox.style.marginTop = 'var(--gw-sp-4)';
  root.append(title, hint, row, result, listBox);

  function api(method, url, body) {
    return fetch(url, { method: method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, data: j }; }); });
  }

  function showCreated(d) {
    result.textContent = '';
    var box = el('div', 'gw-alert gw-alert--ok'); box.setAttribute('role', 'status');
    box.appendChild(el('strong', null, 'Enlace listo. Cópialo ahora: por seguridad no se vuelve a mostrar.'));
    var line = el('div', null); line.style.cssText = 'display:flex; gap:var(--gw-sp-2); flex-wrap:wrap; margin-top:var(--gw-sp-2);';
    var input = el('input', 'gw-input'); input.type = 'text'; input.readOnly = true; input.value = d.url; input.setAttribute('aria-label', 'Enlace de solo lectura'); input.style.flex = '1 1 18rem';
    var btn = el('button', 'gw-btn gw-btn--secondary', 'Copiar enlace'); btn.type = 'button';
    btn.addEventListener('click', function () { copy(d.url).then(function (ok) { if (ok) toast('Enlace copiado', 'success'); else { input.focus(); input.select(); toast('Selecciona el enlace y cópialo', 'info'); } }); });
    line.append(input, btn);
    box.append(line, el('p', 'gw-hint', 'Vence el ' + d.expires_local + '. Solo muestra estadísticas.'));
    result.appendChild(box);
    input.focus(); input.select();
  }

  function renderList(links) {
    listBox.textContent = '';
    var mine = links.filter(function (l) { return l.scope === scope && (scope === 'event' || String(l.form_id) === String(formId)); });
    if (!mine.length) { listBox.appendChild(el('p', 'gw-hint', 'No hay enlaces vigentes.')); return; }
    listBox.appendChild(el('h4', 'gw-label', 'Enlaces vigentes'));
    var table = el('table', 'gw-table'); var thead = el('thead'); var hr = el('tr');
    ['Para quién', 'Vence', 'Último uso', ''].forEach(function (h) { var th = el('th', null, h); th.scope = 'col'; hr.appendChild(th); });
    thead.appendChild(hr); table.appendChild(thead);
    var tb = el('tbody');
    mine.forEach(function (l) {
      var tr = el('tr');
      tr.appendChild(el('td', null, l.label || '—'));
      tr.appendChild(el('td', null, l.expires_local));
      tr.appendChild(el('td', null, l.last_seen_at ? new Date(l.last_seen_at).toLocaleString('es-CO') : 'Sin abrir'));
      var td = el('td'); var b = el('button', 'gw-btn gw-btn--secondary gw-btn--sm', 'Cancelar enlace'); b.type = 'button'; b.dataset.id = l.id; td.appendChild(b); tr.appendChild(td);
      tb.appendChild(tr);
    });
    table.appendChild(tb); listBox.appendChild(table);
  }

  function load() {
    return api('GET', base).then(function (r) { if (r.ok) renderList(r.data.links || []); else listBox.textContent = ''; });
  }

  create.addEventListener('click', function () {
    create.disabled = true;
    var body = { scope: scope, days: parseInt(days.value, 10), label: label.value };
    if (scope === 'form') body.form_id = formId;
    api('POST', base, body).then(function (r) {
      create.disabled = false;
      if (!r.ok) { toast((r.data && r.data.detail) || 'No se pudo crear el enlace. Intenta de nuevo.', 'error'); return; }
      showCreated(r.data); label.value = ''; load();
    }).catch(function () { create.disabled = false; toast('Sin conexión. Intenta de nuevo.', 'error'); });
  });

  listBox.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-id]'); if (!b) return;
    var go = window.showConfirm ? window.showConfirm('¿Cancelar este enlace? Quien lo tenga ya no podrá abrirlo.', { confirmLabel: 'Sí, cancelar' }) : Promise.resolve(true);
    Promise.resolve(go).then(function (yes) {
      if (!yes) return;
      api('DELETE', base + '/' + encodeURIComponent(b.dataset.id)).then(function (r) { if (r.ok) { toast('Enlace cancelado', 'success'); load(); } else toast('No se pudo cancelar el enlace.', 'error'); });
    });
  });

  load();
})();
