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
  function badge(level, text) { return '<span class="gw-badge ' + BADGE[level] + '">' + icon(ICON[level]) + (text || LABEL[level]) + '</span>'; }
  function getJson(url) {
    return fetch(url, { headers: { Accept: 'application/json' } }).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    });
  }

  // Criterio de prioridad (solo de presentación, en el cliente): 1) ¿está vivo?, 2) ¿se puede desplegar?, 3) lo demás.
  var GROUPS = [
    { key: 'vivo', title: 'Funcionamiento', ids: ['database', 'connections', 'queue', 'errors', 'payments', 'emails'] },
    { key: 'deploy', title: 'Despliegue', ids: ['events', 'version'], deploy: true },
    { key: 'otros', title: 'Respaldos y otros datos', ids: [] }
  ];
  var RANK = { red: 0, yellow: 1, green: 2 };
  var OVERALL = { green: 'Sistema funcionando', yellow: 'Sistema con atención', red: 'Sistema con problema' };
  var userOpen = {};

  function groupOf(id) {
    for (var g = 0; g < GROUPS.length; g++) if (GROUPS[g].ids.indexOf(id) !== -1) return g;
    return GROUPS.length - 1;
  }
  function isOpen(id, level) { return Object.prototype.hasOwnProperty.call(userOpen, id) ? userOpen[id] : level !== 'green'; }
  function card(id, level, title, value, body, badgeText) {
    var head = '<span class="gw-sistema__head"><span class="gw-sistema__title">' + esc(title) + '</span>' + badge(level, badgeText) + '</span>' +
      (value ? '<span class="gw-sistema__value">' + esc(value) + '</span>' : '');
    var cls = 'gw-sistema__card gw-sistema__card--' + level;
    if (!body) return '<article class="' + cls + '" data-card="' + esc(id) + '"><div class="gw-sistema__sum">' + head + '</div></article>';
    return '<details class="' + cls + '" data-card="' + esc(id) + '" data-level="' + level + '"' + (isOpen(id, level) ? ' open' : '') + '><summary class="gw-sistema__sum">' + head +
      '<span class="gw-sistema__more" aria-hidden="true">' + icon('chevron') + '</span></summary><div class="gw-sistema__body">' + body + '</div></details>';
  }

  function render(status, deploy) {
    var banner = document.getElementById('banner');
    var bad = status.items.filter(function (i) { return i.level !== 'green'; });
    banner.className = 'gw-alert gw-sistema__overall ' + ALERT[status.level];
    banner.innerHTML = icon(ICON[status.level]) + '<div><p class="gw-alert__title gw-sistema__overall-title">' + OVERALL[status.level] + '</p><p class="gw-alert__body">' +
      (bad.length ? bad.map(function (i) { return esc(i.title); }).join(' · ') : 'Todos los chequeos están en verde.') + '</p></div>';

    var lvl = deploy.allowed ? 'green' : 'red';
    var deployHtml = '<div id="deploy" aria-live="polite" class="gw-sistema__deploy">' + card('deploy', lvl, '¿Se puede desplegar ahora?', '',
      '<p class="gw-sistema__reason">' + (deploy.allowed ? 'No hay eventos en curso ni aperturas en las próximas ' + esc(deploy.hours) + ' h.' : 'Hay motivos para esperar.') + '</p>' +
      (deploy.reasons.length ? '<p class="gw-sistema__reason">' + deploy.reasons.map(esc).join('<br>') + '</p>' : ''), deploy.allowed ? 'Sí' : 'No, todavía') + '</div>';
    var buckets = GROUPS.map(function () { return []; });
    status.items.forEach(function (i, n) { buckets[groupOf(i.id)].push({ i: i, n: n }); });
    document.getElementById('grid').innerHTML = GROUPS.map(function (g, gi) {
      var list = buckets[gi].sort(function (x, y) { return (RANK[x.i.level] - RANK[y.i.level]) || (x.n - y.n); });
      var cards = list.map(function (o) {
        var i = o.i;
        var body = (i.reason ? '<p class="gw-sistema__reason">' + esc(i.reason) + '</p>' : '') +
          (i.action ? '<p class="gw-sistema__action"><strong>Qué hacer:</strong> ' + esc(i.action) + '</p>' : '');
        return card(i.id, i.level, i.title, i.value, body);
      }).join('');
      if (g.deploy) cards = deployHtml + cards;
      if (!cards) return '';
      return '<section class="gw-sistema__group" aria-labelledby="gw-sis-g-' + g.key + '"><h2 class="gw-sistema__group-title" id="gw-sis-g-' + g.key + '">' + g.title + '</h2><div class="gw-sistema__cards">' + cards + '</div></section>';
    }).join('');
    last = Date.now();
    document.getElementById('updated').textContent = 'Actualizado hace 0 s';
  }

  function fail(e) {
    var banner = document.getElementById('banner');
    banner.className = 'gw-alert gw-alert--err';
    banner.innerHTML = icon('error') + '<div><p class="gw-alert__title">Problema</p><p class="gw-alert__body">No se pudo consultar el estado (' + esc(e.message) +
      '). Si esta pantalla no carga, la aplicación misma puede estar caída. Pulsa «Actualizar ahora» para reintentar.</p></div>';
    var grid = document.getElementById('grid');
    if (grid.querySelector('[data-gw-sk]')) grid.innerHTML = '';      // sin el esqueleto: el aviso de arriba dice qué pasó
  }

  function refresh() {
    return Promise.all([getJson('/api/ops/status'), getJson('/api/ops/deploy-allowed')]).then(function (r) { render(r[0], r[1]); }).catch(fail);
  }

  setInterval(function () { if (last) document.getElementById('updated').textContent = 'Actualizado hace ' + Math.round((Date.now() - last) / 1000) + ' s'; }, 1000);
  document.getElementById('refreshBtn').addEventListener('click', function (e) {
    var btn = e.currentTarget;
    if (window.GW && window.GW.busy) window.GW.busy(btn, refresh); else refresh();
  });
  document.getElementById('grid').addEventListener('click', function (e) {
    var sum = e.target.closest && e.target.closest('summary');
    var det = sum && sum.parentNode;
    if (det && det.getAttribute && det.getAttribute('data-card')) setTimeout(function () { userOpen[det.getAttribute('data-card')] = det.open; }, 0);
  });
  refresh();
  if (window.GW && window.GW.poll) window.GW.poll(refresh, 15000); else setInterval(refresh, 15000);
})();
