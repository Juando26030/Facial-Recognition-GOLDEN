/* Turno en el celular (Fase 8). Sondeo suave cada ~6 s con variación; se frena si la pestaña está oculta y se espacia si hay errores. No hay websockets. */
(function () {
  var cfg = window.TQ || { event_id: document.getElementById('tqPub').dataset.eventId, token: document.getElementById('tqPub').dataset.token || '' }, base = '/turno/' + cfg.event_id;
  var $ = function (id) { return document.getElementById(id); };
  var fails = 0, timer = null, wasCalled = false;
  try { cfg.token = cfg.token || localStorage.getItem('tq_' + cfg.event_id) || ''; } catch (e) {}

  function show(v) {
    $('tqAsk').hidden = true; $('tqShow').hidden = false;
    $('tqLabel').textContent = v.label;
    var pub = $('tqPub');
    if (v.your_turn) {
      pub.classList.add('tq-pub--called');
      $('tqMsg').textContent = 'Eres el ' + v.label + ', ya puedes seguir' + (v.desk ? ' · ' + v.desk : '') + (v.name ? ', ' + v.name : '');
      $('tqSub').textContent = '';
      if (!wasCalled && navigator.vibrate) { try { navigator.vibrate([300, 150, 300]); } catch (e) {} }
    } else {
      pub.classList.remove('tq-pub--called');
      if (v.status === 'skipped') { $('tqMsg').textContent = 'Tu turno fue saltado. Acércate a la mesa de ayuda.'; $('tqSub').textContent = ''; }
      else if (v.status === 'done') { $('tqMsg').textContent = 'Tu turno ya fue atendido. ¡Gracias!'; $('tqSub').textContent = ''; }
      else {
        $('tqMsg').textContent = (v.name ? v.name + ', ' : '') + (v.ahead === 0 ? 'eres el siguiente' : 'faltan ' + v.ahead + (v.ahead === 1 ? ' persona' : ' personas') + ' antes que tú');
        $('tqSub').textContent = v.serving ? 'Ahora atienden el ' + v.serving : 'Todavía no han llamado a nadie en tu fila';
      }
    }
    wasCalled = !!v.your_turn;
  }
  function ask(msg) { $('tqShow').hidden = true; $('tqAsk').hidden = false; $('tqErr').textContent = msg || ''; }

  function poll() {
    clearTimeout(timer);
    if (!cfg.token) return;
    var next = function () { timer = setTimeout(poll, Math.min(60000, (6000 + Math.random() * 2000) * (1 + fails))); };
    if (document.hidden) { next(); return; }
    fetch(base + '/' + encodeURIComponent(cfg.token) + '/state', { cache: 'no-store' }).then(function (r) {
      if (r.status === 404) { try { localStorage.removeItem('tq_' + cfg.event_id); } catch (e) {} cfg.token = ''; ask('No encontramos tu turno. Escribe tu documento de nuevo.'); throw new Error('gone'); }
      if (!r.ok) throw new Error('http'); return r.json();
    }).then(function (v) { fails = 0; show(v); next(); }).catch(function (e) { if (e.message === 'gone') return; fails = Math.min(fails + 1, 5); next(); });
  }

  $('tqForm').addEventListener('submit', function (e) {
    e.preventDefault();
    var ced = $('tqCed').value.trim(); if (!ced) return;
    fetch(base + '/buscar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cedula: ced }) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.detail || 'No se pudo consultar'); return j; }); })
      .then(function (j) { cfg.token = j.token; try { localStorage.setItem('tq_' + cfg.event_id, j.token); } catch (x) {} $('tqCed').value = ''; poll(); })
      .catch(function (err) { ask(err.message); });
  });
  document.addEventListener('visibilitychange', function () { if (!document.hidden) poll(); });
  if (cfg.token) { poll(); } else { ask(''); }
})();
