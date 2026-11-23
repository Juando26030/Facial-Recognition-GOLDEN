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
  var row = el('div', 'gw-share__row');
  var daysWrap = el('div', 'gw-field'); var daysLabel = el('label', 'gw-label', 'Vence en'); daysLabel.htmlFor = 'statsShareDays';
  var days = el('select', 'gw-select'); days.id = 'statsShareDays';
  DAYS.forEach(function (d) { var o = el('option', null, d[1]); o.value = d[0]; if (d[0] === 7) o.selected = true; days.appendChild(o); });
  daysWrap.append(daysLabel, days);
  var labelWrap = el('div', 'gw-field'); var labelLabel = el('label', 'gw-label', 'Para quién (opcional)'); labelLabel.htmlFor = 'statsShareLabel';
  var label = el('input', 'gw-input'); label.id = 'statsShareLabel'; label.type = 'text'; label.maxLength = 80; label.placeholder = 'Ej. Cliente, reunión del lunes';
  labelWrap.append(labelLabel, label);
  var create = el('button', 'gw-btn gw-btn--secondary', 'Crear enlace'); create.type = 'button';
  row.append(daysWrap, labelWrap, create);
  var result = el('div', 'gw-share__result'); result.setAttribute('aria-live', 'polite');
  var listBox = el('div', 'gw-share__list');
  root.append(title, hint, row, result, listBox);

  function api(method, url, body) {
    return fetch(url, { method: method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, data: j }; }); });
  }

  function showCreated(d) {
    result.textContent = '';
    var box = el('div', 'gw-alert gw-alert--ok'); box.setAttribute('role', 'status');
    box.appendChild(el('strong', null, 'Enlace listo. Cópialo ahora: por seguridad no se vuelve a mostrar.'));
    var line = el('div', 'gw-share__line');
    var input = el('input', 'gw-input'); input.type = 'text'; input.readOnly = true; input.value = d.url; input.setAttribute('aria-label', 'Enlace de solo lectura');
    var btn = el('button', 'gw-btn gw-btn--secondary', 'Copiar enlace'); btn.type = 'button';
    btn.addEventListener('click', function () { copy(d.url).then(function (ok) { if (ok) toast('Enlace copiado', 'success'); else { input.focus(); input.select(); toast('Selecciona el enlace y cópialo', 'info'); } }); });
    var qrBtn = el('button', 'gw-btn gw-btn--secondary', 'Generar QR'); qrBtn.type = 'button'; qrBtn.setAttribute('data-qr-link', d.url); qrBtn.setAttribute('data-qr-title', 'Estadísticas');
    line.append(input, btn, qrBtn);
    box.append(line);
    if (d.tv_url) {          // la misma credencial abre la pantalla de TV (ingreso en vivo para proyectar)
      var tvLine = el('div', 'gw-share__line');
      var tvIn = el('input', 'gw-input'); tvIn.type = 'text'; tvIn.readOnly = true; tvIn.value = d.tv_url; tvIn.setAttribute('aria-label', 'Enlace de la pantalla de TV');
      var tvBtn = el('button', 'gw-btn gw-btn--secondary', 'Copiar enlace de TV'); tvBtn.type = 'button';
      tvBtn.addEventListener('click', function () { copy(d.tv_url).then(function (ok) { if (ok) toast('Enlace de TV copiado', 'success'); else { tvIn.focus(); tvIn.select(); toast('Selecciona el enlace y cópialo', 'info'); } }); });
      var tvQr = el('button', 'gw-btn gw-btn--secondary', 'Generar QR'); tvQr.type = 'button'; tvQr.setAttribute('data-qr-link', d.tv_url); tvQr.setAttribute('data-qr-title', 'Pantalla de TV');
      tvLine.append(tvIn, tvBtn, tvQr);
      box.append(el('p', 'gw-hint', 'Para proyectar en un televisor (ingreso en vivo):'), tvLine);
    }
    box.append(el('p', 'gw-hint', 'Vence el ' + d.expires_local + '. Solo muestra estadísticas' + (d.tv_url ? ' y el ingreso en vivo' : '') + '.'));
    result.appendChild(box);
    input.focus(); input.select();
  }

  function renderList(links) {
    listBox.textContent = '';
    var mine = links.filter(function (l) { return l.scope === scope && (scope === 'event' || String(l.form_id) === String(formId)); });
    if (!mine.length) { listBox.appendChild(el('p', 'gw-hint', 'No hay enlaces vigentes.')); return; }
    listBox.appendChild(el('h4', 'gw-label', 'Enlaces vigentes'));
    var table = el('table', 'gw-table gw-table-cards'); var thead = el('thead'); var hr = el('tr');
    ['Para quién', 'Vence', 'Último uso', ''].forEach(function (h) { var th = el('th', null, h); th.scope = 'col'; hr.appendChild(th); });
    thead.appendChild(hr); table.appendChild(thead);
    var tb = el('tbody');
    mine.forEach(function (l) {
      var tr = el('tr');
      var c1 = el('td', null, l.label || '—'); c1.dataset.label = 'Para quién'; tr.appendChild(c1);
      var c2 = el('td', null, l.expires_local); c2.dataset.label = 'Vence'; tr.appendChild(c2);
      var c3 = el('td', null, l.last_seen_at ? new Date(l.last_seen_at).toLocaleString('es-CO') : 'Sin abrir'); c3.dataset.label = 'Último uso'; tr.appendChild(c3);
      var td = el('td', 'gw-table-cards__actions'); var b = el('button', 'gw-btn gw-btn--secondary gw-btn--sm', 'Cancelar enlace'); b.setAttribute('aria-label', 'Cancelar el enlace de ' + (l.label || 'sin nombre')); b.type = 'button'; b.dataset.id = l.id; td.appendChild(b); tr.appendChild(td);
      tb.appendChild(tr);
    });
    table.appendChild(tb); listBox.appendChild(table);
  }

  function load() {
    return api('GET', base).then(function (r) { if (r.ok) renderList(r.data.links || []); else listBox.textContent = ''; });
  }

  create.addEventListener('click', function () {
    var body = { scope: scope, days: parseInt(days.value, 10), label: label.value };
    if (scope === 'form') body.form_id = formId;
    var work = function () {
      return api('POST', base, body).then(function (r) {
        if (!r.ok) { toast((r.data && r.data.detail) || 'No se pudo crear el enlace. Intenta de nuevo.', 'error'); return; }
        showCreated(r.data); label.value = ''; load();
      });
    };
    (window.GW && window.GW.busy ? window.GW.busy(create, work) : work()).catch(function () { toast('Sin conexión. Intenta de nuevo.', 'error'); });
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
