/* Turnos y filas — consola del operador (Fase 8). Delegación de eventos; sondeo suave cada 4 s (pausado con la pestaña oculta). */
(function () {
  var EID = window.EVENT_ID || document.querySelector('[data-event-id]').dataset.eventId;
  var base = '/api/events/' + EID + '/queue';
  var lanesBox = document.getElementById('tqLanes');
  if (!lanesBox) return;
  var state = null, timer = null;

  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
  function post(url, body) {
    return fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(j.detail || 'No se pudo'); return j; }); });
  }
  function fail(e) { showToast(e.message || 'No se pudo', 'error'); }

  function render() {
    if (!state) return;
    var hint = { arrival: 'Por llegada: el turno se da cuando la persona escanea el QR. No hace falta asignar.', form: 'Por inscripción: asigna los turnos en el orden en que se inscribieron.',
      alpha: 'Alfabético: asigna los turnos por apellido y nombre.', manual: 'Manual: sube el Excel con el orden.' }[state.mode] || '';
    document.getElementById('tqModeHint').textContent = hint + ' Total de turnos: ' + state.total + '.';
    document.getElementById('tqUploadBox').hidden = state.mode !== 'manual';
    var assign = document.querySelector('[data-act="assign"]'); if (assign) assign.hidden = state.mode === 'manual';
    var L = state.listing || { waiting: [], skipped: [], called: [] };
    lanesBox.innerHTML = state.lanes.map(function (l) {
      var w = L.waiting.filter(function (t) { return t.lane === l.letter; });
      var s = L.skipped.filter(function (t) { return t.lane === l.letter; });
      var now = l.serving ? l.serving.label : '—';
      return '<div class="tq-lane" data-lane="' + esc(l.letter) + '">' +
        '<div class="tq-lane__name">Fila ' + esc(l.letter) + (l.name && l.name !== l.letter ? ' · ' + esc(l.name) : '') + '</div>' +
        '<div class="tq-lane__now">' + esc(now) + '</div>' +
        '<div class="tq-lane__meta">Esperan: ' + l.waiting + '</div>' +
        '<div class="gw-actions"><button type="button" class="gw-btn gw-btn--primary" data-act="call">Llamar siguiente</button>' +
        '<button type="button" class="gw-btn gw-btn--secondary" data-act="repeat">Repetir</button></div>' +
        '<ul class="tq-list">' + w.slice(0, 15).map(function (t) {
          return '<li><span><b>' + esc(t.label) + '</b> ' + esc(t.name) + ' <span class="tq-lane__meta">' + esc(t.user_id) + '</span></span><button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-act="skip" data-id="' + t.id + '">Saltar</button></li>';
        }).join('') + '</ul>' +
        (s.length ? '<div class="tq-lane__meta">Saltados</div><ul class="tq-list">' + s.map(function (t) {
          return '<li><span><b>' + esc(t.label) + '</b> ' + esc(t.name) + '</span><button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-act="requeue" data-id="' + t.id + '">Volver a la fila</button></li>';
        }).join('') + '</ul>' : '') + '</div>';
    }).join('');
  }

  function load() {
    return fetch(base, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (j) { state = j; render(); }).catch(function () {});
  }
  function loop() { clearTimeout(timer); timer = setTimeout(function () { (document.hidden ? Promise.resolve() : load()).then(loop); }, 4000); }

  function desk() { return (document.getElementById('tqDesk').value || '').trim(); }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-act]'); if (!b) return;
    var act = b.getAttribute('data-act'), laneEl = b.closest('[data-lane]'), lane = laneEl ? laneEl.getAttribute('data-lane') : '';
    var done = function () { return load(); };
    if (act === 'call') post(base + '/call', { lane: lane, desk: desk() }).then(function (j) { showToast(j.called ? 'Llamaste al ' + j.called : 'No hay nadie esperando en la fila ' + lane, j.called ? 'success' : 'info'); return done(); }).catch(fail);
    else if (act === 'repeat') post(base + '/repeat', { lane: lane }).then(function (j) { showToast(j.called ? 'Repetido: ' + j.called : 'No hay un turno llamado', j.called ? 'success' : 'info'); return done(); }).catch(fail);
    else if (act === 'skip' || act === 'requeue') post(base + '/turns/' + b.getAttribute('data-id') + '/' + act).then(done).catch(fail);
    else if (act === 'assign') post(base + '/assign', {}).then(function (j) { showToast('Turnos nuevos: ' + j.created, 'success'); return done(); }).catch(fail);
    else if (act === 'rebuild') {
      showConfirm('Se borran los turnos que siguen esperando y se vuelven a dar. Los ya llamados se conservan. ¿Continuar?').then(function (ok) {
        if (ok) post(base + '/assign', { rebuild: true }).then(function (j) { showToast('Turnos nuevos: ' + j.created, 'success'); return done(); }).catch(fail);
      });
    } else if (act === 'print-qr') window.print();
    else if (act === 'copy-url') { var u = document.getElementById('tqUrl').textContent; if (navigator.clipboard) navigator.clipboard.writeText(u).then(function () { showToast('Enlace copiado', 'success'); }); }
  });

  document.getElementById('tqFile').addEventListener('change', function (e) {
    var f = e.target.files[0]; if (!f) return;
    var fd = new FormData(); fd.append('file', f);
    fetch(base + '/upload', { method: 'POST', credentials: 'same-origin', body: fd })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.detail || 'No se pudo leer el Excel'); return j; }); })
      .then(function (j) {
        var out = 'Turnos creados: ' + j.created + (j.unknown ? ' · ' + j.unknown + ' cédulas no están en el evento y se omitieron' : '') + (j.errors_total ? ' · ' + j.errors_total + ' filas con problemas' : '');
        document.getElementById('tqResult').textContent = out + (j.errors && j.errors.length ? '. ' + j.errors.slice(0, 5).join(' | ') : '');
        showToast('Excel cargado', 'success'); e.target.value = ''; return load();
      }).catch(fail);
  });

  var url = location.origin + '/turno/' + EID;
  document.getElementById('tqUrl').textContent = url;
  try { var qr = qrcode(0, 'M'); qr.addData(url); qr.make(); document.getElementById('tqQr').innerHTML = qr.createSvgTag(5); } catch (err) {}
  document.addEventListener('visibilitychange', function () { if (!document.hidden) load(); });
  load().then(loop);
})();
