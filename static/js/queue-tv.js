/* Pantalla de TV de turnos (Fase 8). Sondeo cada 3 s mientras hay movimiento; si nada cambia en 5 min pasa a 10 s y en 30 min a 30 s (una TV olvidada de noche no mantiene despierta la base); resalta y (si se activó el sonido) hace sonar un aviso cuando cambia el turno llamado. */
(function () {
  var lanesEl = document.getElementById('tvLanes'), recentEl = document.getElementById('tvRecent'), soundBtn = document.getElementById('tvSound');
  var url = '/api/events/' + (window.EVENT_ID || document.body.dataset.eventId) + '/queue/tv';
  var last = {}, sound = false, ctx = null, lastSig = '', lastChange = Date.now(), timer = null;
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
  function beep() {
    if (!sound || !ctx) return;
    try { var o = ctx.createOscillator(), g = ctx.createGain(); o.frequency.value = 880; g.gain.value = 0.2; o.connect(g); g.connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.4); } catch (e) {}
  }
  soundBtn.addEventListener('click', function () {
    try { ctx = ctx || new (window.AudioContext || window.webkitAudioContext)(); sound = !sound; soundBtn.textContent = sound ? 'Sonido activado' : 'Activar sonido'; beep(); } catch (e) {}
  });
  function draw(d) {
    var changed = false, sig = JSON.stringify(d.lanes || []) + JSON.stringify(d.recent || []);
    if (sig !== lastSig) { lastSig = sig; lastChange = Date.now(); }
    lanesEl.innerHTML = d.lanes.map(function (l) {
      var s = l.serving, label = s ? s.label : '—', key = s ? (s.label + '|' + (s.seq || '')) : '';
      var flash = key && last[l.letter] !== undefined && last[l.letter] !== key;
      if (flash) changed = true;
      last[l.letter] = key;
      return '<div class="tq-tv__lane' + (flash ? ' tq-tv__lane--flash' : '') + '"><div class="tq-tv__name">' + esc(l.name && l.name !== l.letter ? l.name : 'Fila ' + l.letter) + '</div>' +
        '<div class="tq-tv__label">' + esc(label) + '</div><div class="tq-tv__desk">' + esc(s && s.desk ? s.desk : '') + '</div></div>';
    }).join('');
    recentEl.innerHTML = (d.recent || []).slice(0, 6).map(function (c) { return '<span>' + esc(c.label) + (c.desk ? ' · ' + esc(c.desk) : '') + '</span>'; }).join('');
    if (changed) beep();
  }
  function delay() { var q = Date.now() - lastChange; return q > 30 * 60000 ? 30000 : q > 5 * 60000 ? 10000 : 3000; }
  function tick() {
    var next = function () { clearTimeout(timer); timer = setTimeout(tick, delay()); };
    if (document.hidden) { next(); return; }
    fetch(url, { credentials: 'same-origin', cache: 'no-store', headers: { 'X-Gw-Passive': '1' } }).then(function (r) { if (r.status === 401 || r.status === 403) { location.href = '/login'; throw new Error(); } return r.json(); }).then(draw).catch(function () {}).then(next);
  }
  document.addEventListener('visibilitychange', function () { if (!document.hidden) { lastChange = Date.now(); tick(); } });
  tick();
})();
