/* Estado del sistema (/sistema). Sondeo cada 15 s con GW.poll (pausado con la pestaña oculta): mismas dos rutas de siempre, sin tocar nada más. */
(function () {
  'use strict';
  var LABEL = { green: 'Todo bien', yellow: 'Atención', red: 'Problema' };
  var ICON = { green: 'check', yellow: 'alert', red: 'error' };
  var BADGE = { green: 'gw-badge--ok', yellow: 'gw-badge--warn', red: 'gw-badge--err' };
  var ALERT = { green: 'gw-alert--ok', yellow: 'gw-alert--warn', red: 'gw-alert--err' };
  var last = null;
  var spriteUrl = (document.getElementById('grid') || document.body).getAttribute('data-icons') || '/static/img/icons.svg';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function icon(name) { return '<svg class="gw-icon" aria-hidden="true"><use href="' + spriteUrl + '#i-' + name + '"/></svg>'; }
  function badge(level) { return '<span class="gw-badge ' + BADGE[level] + '">' + icon(ICON[level]) + LABEL[level] + '</span>'; }
  function getJson(url) {
    return fetch(url, { headers: { Accept: 'application/json' } }).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    });
  }

  function render(status, deploy) {
    var banner = document.getElementById('banner');
    var bad = status.items.filter(function (i) { return i.level !== 'green'; });
    banner.className = 'gw-alert ' + ALERT[status.level];
    banner.innerHTML = icon(ICON[status.level]) + '<div><p class="gw-alert__title">' + LABEL[status.level] + '</p><p class="gw-alert__body">' +
      (bad.length ? bad.map(function (i) { return esc(i.title); }).join(' · ') : 'Todos los chequeos están en verde.') + '</p></div>';
    document.getElementById('grid').innerHTML = status.items.map(function (i) {
      return '<article class="gw-sistema__card gw-sistema__card--' + i.level + '"><div class="gw-sistema__head"><h3 class="gw-sistema__title">' + esc(i.title) + '</h3>' + badge(i.level) + '</div>' +
        '<p class="gw-sistema__value">' + esc(i.value) + '</p>' +
        (i.reason ? '<p class="gw-sistema__reason">' + esc(i.reason) + '</p>' : '') +
        (i.action ? '<p class="gw-sistema__action"><strong>Qué hacer:</strong> ' + esc(i.action) + '</p>' : '') + '</article>';
    }).join('');
    var d = document.getElementById('deploy');
    var lvl = deploy.allowed ? 'green' : 'red';
    d.className = 'gw-sistema__card gw-sistema__card--' + lvl;
    d.innerHTML = '<div class="gw-sistema__head"><h3 class="gw-sistema__title">¿Se puede desplegar ahora?</h3>' +
      '<span class="gw-badge ' + BADGE[lvl] + '">' + icon(ICON[lvl]) + (deploy.allowed ? 'Sí' : 'No, todavía') + '</span></div>' +
      '<p class="gw-sistema__value">' + (deploy.allowed ? 'No hay eventos en curso ni aperturas en las próximas ' + esc(deploy.hours) + ' h.' : 'Hay motivos para esperar.') + '</p>' +
      (deploy.reasons.length ? '<p class="gw-sistema__reason">' + deploy.reasons.map(esc).join('<br>') + '</p>' : '');
    last = Date.now();
    document.getElementById('updated').textContent = 'Actualizado hace 0 s';
  }

  function fail(e) {
    var banner = document.getElementById('banner');
    banner.className = 'gw-alert gw-alert--err';
    banner.innerHTML = icon('error') + '<div><p class="gw-alert__title">Problema</p><p class="gw-alert__body">No se pudo consultar el estado (' + esc(e.message) +
      '). Si esta pantalla no carga, la aplicación misma puede estar caída. Pulsa «Actualizar ahora» para reintentar.</p></div>';
  }

  function refresh() {
    return Promise.all([getJson('/api/ops/status'), getJson('/api/ops/deploy-allowed')]).then(function (r) { render(r[0], r[1]); }).catch(fail);
  }

  setInterval(function () { if (last) document.getElementById('updated').textContent = 'Actualizado hace ' + Math.round((Date.now() - last) / 1000) + ' s'; }, 1000);
  document.getElementById('refreshBtn').addEventListener('click', function (e) {
    var btn = e.currentTarget;
    if (window.GW && window.GW.busy) window.GW.busy(btn, refresh); else refresh();
  });
  refresh();
  if (window.GW && window.GW.poll) window.GW.poll(refresh, 15000); else setInterval(refresh, 15000);
})();
