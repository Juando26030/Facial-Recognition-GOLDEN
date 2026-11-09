/* Parámetros → Turnos y filas (Fase 8). Módulo propio: guarda con su botón, no entra en el «Sin guardar» del resto. */
(function () {
  var box = document.getElementById('queueBox');
  if (!box) return;
  var eventId = box.getAttribute('data-event');
  var $ = function (id) { return document.getElementById(id); };
  var api = '/api/events/' + eventId + '/queue/config';

  function lanesToText(lanes) {
    return (lanes || []).map(function (l) { return l.name && l.name !== l.letter ? l.letter + '=' + l.name : l.letter; }).join(', ');
  }
  function textToLanes(text) {
    return String(text || '').split(',').map(function (part) {
      var p = part.trim(); if (!p) return null;
      var i = p.indexOf('=');
      var letter = (i < 0 ? p : p.slice(0, i)).trim().toUpperCase();
      var name = i < 0 ? '' : p.slice(i + 1).trim();
      return { letter: letter, name: name };
    }).filter(Boolean);
  }
  function fill(data) {
    var c = data.config || {};
    $('queueMode').value = c.mode || 'arrival';
    $('queueLanes').value = lanesToText(c.lanes);
    $('queueShowName').checked = !!c.show_name;
    $('queueRequireReg').checked = !!c.require_registered;
  }

  fetch(api, { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) { if (d) fill(d); });

  box.addEventListener('change', function (e) {
    if (e.target.id === 'queueEnabled') $('queueConfig').hidden = !e.target.checked;
  });
  box.addEventListener('click', function (e) {
    if (!e.target.closest('#queueSave')) return;
    var body = { enabled: $('queueEnabled').checked, config: {
      mode: $('queueMode').value, lanes: textToLanes($('queueLanes').value),
      show_name: $('queueShowName').checked, require_registered: $('queueRequireReg').checked } };
    fetch(api, { method: 'PUT', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) { showToast(res.j.detail || 'No se pudo guardar', 'error'); return; }
        fill(res.j); showToast('Turnos y filas guardado', 'success');
      })
      .catch(function () { showToast('No se pudo guardar. Revisa la conexión.', 'error'); });
  });
})();
