/* Pantalla de ingreso para TV: pide los datos cada `data-poll` segundos (nunca más seguido; se detiene si la pestaña está oculta) y repinta con textContent (nada de HTML
   armado con datos). Si falla la red, deja lo último que se vio y lo avisa abajo. */
(function () {
  'use strict';
  var body = document.body;
  var api = body.dataset.api;
  if (!api) return;
  var every = Math.max(5, parseInt(body.dataset.poll, 10) || 10) * 1000;
  var $ = function (id) { return document.getElementById(id); };
  var timer = null, failures = 0;

  function paintList(items) {
    var ol = $('tvList');
    ol.textContent = '';
    if (!items.length) { var e = document.createElement('li'); e.className = 'gw-tv__empty'; e.textContent = 'Esperando los primeros ingresos…'; ol.appendChild(e); return; }
    items.forEach(function (p) {
      var li = document.createElement('li');
      var who = document.createElement('span'); who.className = 'gw-tv__who'; who.textContent = p.name;
      var at = document.createElement('span'); at.className = 'gw-tv__at'; at.textContent = p.at;
      li.append(who, at);
      if (p.entity) { var ent = document.createElement('span'); ent.className = 'gw-tv__ent'; ent.textContent = p.entity; li.appendChild(ent); }
      ol.appendChild(li);
    });
  }

  function paint(d) {
    $('tvRegistered').textContent = d.registered;
    $('tvExpected').textContent = d.expected;
    $('tvPct').textContent = d.percent + ' %';
    $('tvFill').style.width = d.percent + '%';
    $('tvBar').setAttribute('aria-valuenow', String(d.percent));
    paintList(d.recent || []);
    var st = $('tvStatus'); st.textContent = 'Actualizado ' + d.updated_at; st.parentNode.classList.remove('is-off');
  }

  function tick() {
    fetch(api, { credentials: 'same-origin', headers: { Accept: 'application/json' }, cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(function (d) { failures = 0; paint(d); })
      .catch(function () { failures++; var st = $('tvStatus'); st.textContent = failures > 2 ? 'Sin conexión: se muestra lo último que llegó. Reintentando…' : 'Reintentando…'; st.parentNode.classList.add('is-off'); })
      .then(schedule);
  }
  function schedule() { clearTimeout(timer); if (document.hidden) return; timer = setTimeout(tick, every); }
  document.addEventListener('visibilitychange', function () { if (!document.hidden) { clearTimeout(timer); tick(); } });
  tick();
}());
