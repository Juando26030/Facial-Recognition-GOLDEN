/* Estadísticas de un formulario (templates/form_stats.html). Dibuja lo que entrega GET .../stats (app/form_stats.py): cifras grandes, cupos con barras de progreso, una tarjeta por variable
   con la cantidad y el porcentaje de CADA opción a la vista, y la curva de inscripciones. Todo lo escrito por personas se inserta como texto (nunca como HTML). Eventos por delegación. */
(function () {
  'use strict';
  var root = document.getElementById('fs-root');
  if (!root) return;
  var body = document.getElementById('fs-body');
  var updated = document.getElementById('fs-updated');
  var stateBadge = document.getElementById('fs-state');
  var testsBox = document.getElementById('fs-tests');
  var chart = null;
  var last = null;
  var nf = new Intl.NumberFormat('es-CO');

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function tone(pct, full) { return full || pct >= 100 ? 'err' : (pct >= 80 ? 'warn' : ''); }

  function kpi(label, value, hint, toneName) {
    var c = el('div', 'gw-card fs-kpi' + (toneName ? ' fs-kpi--' + toneName : ''));
    c.appendChild(el('div', 'fs-kpi__label', label));
    var isText = typeof value === 'string' && value.length > 9;
    c.appendChild(el('div', 'fs-kpi__value' + (isText ? ' fs-kpi__value--text' : ''), typeof value === 'number' ? nf.format(value) : value));
    if (hint) c.appendChild(el('div', 'fs-kpi__hint', hint));
    return c;
  }

  function track(pct, cls, label) {
    var t = el('div', 'fs-track');
    t.setAttribute('role', 'progressbar');
    t.setAttribute('aria-valuemin', '0'); t.setAttribute('aria-valuemax', '100'); t.setAttribute('aria-valuenow', String(pct));
    t.setAttribute('aria-label', label);
    var f = el('div', 'fs-fill' + (cls ? ' fs-fill--' + cls : ''));
    f.style.width = Math.max(0, Math.min(100, pct)) + '%';
    t.appendChild(f);
    return t;
  }

  function capacityCard(cap) {
    var card = el('div', 'gw-card fs-cap');
    card.appendChild(el('h3', 'fs-cap__title', 'Cupo total del formulario'));
    var nums = el('div', 'fs-cap__nums');
    var main = el('div', 'fs-cap__main', nf.format(cap.used));
    main.appendChild(el('small', null, ' de ' + nf.format(cap.total) + ' usados (' + cap.pct + '%)'));
    nums.appendChild(main);
    nums.appendChild(el('div', 'fs-cap__left', cap.full ? 'Cupo lleno' : 'Faltan ' + nf.format(cap.left)));
    card.appendChild(nums);
    card.appendChild(track(cap.pct, tone(cap.pct, cap.full), 'Cupo total usado'));
    return card;
  }

  function when(iso) {      // 'YYYY-MM-DDTHH:MM' en hora local → «7 nov 2026, 5:00 p. m.»
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso || '');
    if (!m) return iso || '';
    return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]).toLocaleString('es-CO', { day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' });
  }

  // Alerta de la fecha de cierre de un cupo: verde si faltan más de 5 días, amarillo entre 2 y 5, rojo con 1 día o menos (o si ya pasó). El color nunca va solo: signo ⚠ y texto.
  function closeAlert(sc) {
    var d = sc.days_left, tone = d > 5 ? 'ok' : d > 1 ? 'warn' : 'err';
    var txt = d < 0 ? 'Ya cerró el ' + when(sc.closes) : (sc.enforced === false ? 'Fecha de cierre prevista: ' : 'Cierra el ') + when(sc.closes) + ' · ' + (d < 1 ? 'falta menos de 1 día' : 'faltan ' + Math.ceil(d) + (Math.ceil(d) === 1 ? ' día' : ' días'));
    var b = el('p', 'gw-badge gw-badge--' + tone + ' fs-alert', '⚠ ' + txt);
    b.setAttribute('role', 'status');
    return b;
  }

  function quotaCard(q) {
    var card = el('div', 'gw-card fs-quota');
    card.appendChild(el('h3', 'fs-cap__title', q.label));
    if (q.rule) card.appendChild(el('p', 'fs-cap__rule', 'Aplica a: ' + q.rule));
    var nums = el('div', 'fs-cap__nums');
    var main = el('div', 'fs-cap__main', nf.format(q.used));
    main.appendChild(el('small', null, ' de ' + nf.format(q.limit) + ' (' + q.pct + '%)'));
    nums.appendChild(main);
    var sc = q.schedule, NAMES = { cerrado: 'Cerrado', finalizado: 'Finalizado', pruebas: 'En pruebas' };
    nums.appendChild(el('div', 'fs-cap__left', q.limit === 0 && !(sc && sc.state !== 'abierto') ? 'Cerrado temporalmente' : (sc && sc.state !== 'abierto') ? NAMES[sc.state] : q.full ? 'Lleno' : 'Faltan ' + nf.format(q.left)));
    card.appendChild(nums);
    if (sc && sc.closes && typeof sc.days_left === 'number') card.appendChild(closeAlert(sc));
    else if (sc && sc.state === 'cerrado') card.appendChild(el('p', 'fs-cap__rule', sc.opens ? 'Abre el ' + when(sc.opens) : 'Cerrado por ahora'));
    card.appendChild(track(q.pct, tone(q.pct, q.full), 'Cupo ' + q.label));
    return card;
  }

  function distCard(d) {
    var card = el('div', 'gw-card fs-dist');
    var head = el('div');
    head.appendChild(el('h3', 'fs-dist__title', d.label));
    head.appendChild(el('p', 'fs-dist__sub', nf.format(d.answered) + (d.answered === 1 ? ' respuesta' : ' respuestas')));
    card.appendChild(head);
    var max = Math.max.apply(null, d.items.map(function (i) { return i.count; }).concat([1]));
    var list = el('ul', 'fs-bars');
    d.items.forEach(function (i) {
      var li = el('li', 'fs-bar');
      var row = el('div', 'fs-bar__row');
      row.appendChild(el('span', 'fs-bar__label', i.label));
      var num = el('span', 'fs-bar__num', nf.format(i.count));
      num.appendChild(el('small', null, ' · ' + i.pct + '%'));
      row.appendChild(num);
      li.appendChild(row);
      li.appendChild(track(Math.round(100 * i.count / max), '', i.label + ': ' + i.count));
      list.appendChild(li);
    });
    card.appendChild(list);
    return card;
  }

  function section(title, hint) {
    var s = el('section', 'fs-section');
    s.appendChild(el('h2', null, title));
    if (hint) s.appendChild(el('p', 'gw-hint', hint));
    return s;
  }

  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  function drawTimeline(spec, canvas) {
    if (chart) { chart.destroy(); chart = null; }
    if (!window.Chart || !canvas) return;
    var narrow = window.matchMedia && window.matchMedia('(max-width: 720px)').matches;          // celular: pocas marcas en el eje, sin rotar
    var text = css('--gw-text'), muted = css('--gw-text-muted'), grid = css('--gw-border'), gold = css('--gw-viz-2') || css('--gw-gold-1'), navy = css('--gw-viz-1') || css('--gw-link');
    chart = new window.Chart(canvas, {
      type: 'line',
      data: { labels: spec.labels, datasets: [
        { label: spec.datasets[0].label, data: spec.datasets[0].data, borderColor: gold, backgroundColor: gold + '33', fill: true, tension: 0.3, borderWidth: 3, pointRadius: spec.labels.length > 40 ? 0 : 4 },
        { label: 'Acumulado', data: spec.datasets[1].data, borderColor: navy, backgroundColor: navy, tension: 0.3, borderWidth: 3, pointRadius: 0, borderDash: [6, 4] }] },
      options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        plugins: { legend: { position: 'bottom', labels: { color: text, font: { size: 14 }, boxWidth: 18 } }, tooltip: { titleFont: { size: 14 }, bodyFont: { size: 14 } } },
        scales: { x: { ticks: { color: muted, font: { size: 13 }, maxRotation: narrow ? 0 : 45, maxTicksLimit: narrow ? 5 : undefined, autoSkip: true }, grid: { color: grid } },
                  y: { beginAtZero: true, ticks: { color: muted, font: { size: 13 }, precision: 0 }, grid: { color: grid } } } },
    });
  }

  function paint(d) {
    last = d;
    body.style.minHeight = body.offsetHeight + 'px';        // sin saltos de pantalla al repintar (cada 60 s)
    body.textContent = '';
    stateBadge.hidden = false;
    stateBadge.textContent = d.form.state_label;
    stateBadge.className = 'gw-badge ' + (d.form.state === 'activo' ? 'gw-badge--ok' : (d.form.state === 'cupo_lleno' ? 'gw-badge--err' : 'gw-badge--info'));
    updated.textContent = 'Actualizado ' + new Date(d.generated_at).toLocaleTimeString('es-CO') + (d.includes_tests ? ' · incluye pruebas' : '');

    var s = d.summary, kp = el('div', 'fs-kpis');
    kp.appendChild(kpi('Inscritos', s.registered, s.companions != null ? 'más ' + nf.format(s.companions) + ' acompañantes: ' + nf.format(s.people_total) + ' personas' : 'inscripciones confirmadas', 'ok'));
    if (d.origin) {      // solo el personal: el servidor no lo manda al cliente ni al enlace público
      kp.appendChild(kpi('Ya estaban en la base', d.origin.known, 'personas que el evento ya tenía cargadas'));
      kp.appendChild(kpi('Personas nuevas', d.origin.new, 'se inscribieron sin estar en la base', d.origin.new ? 'warn' : ''));
      if (d.origin.unknown) kp.appendChild(kpi('Sin cédula', d.origin.unknown, 'no se puede saber si estaban en la base'));
    }
    if (d.capacity) {
      kp.appendChild(kpi('Cupos usados', d.capacity.used + ' / ' + d.capacity.total, d.capacity.pct + '% del cupo total', tone(d.capacity.pct, d.capacity.full)));
      kp.appendChild(kpi('Cupos faltantes', d.capacity.left, d.capacity.full ? 'el cupo está lleno' : 'disponibles ahora', d.capacity.full ? 'err' : ''));
    } else {
      kp.appendChild(kpi('Cupo', 'Sin límite', 'este formulario no tiene cupo total'));
    }
    if (s.visits) kp.appendChild(kpi('Visitas', s.visits, s.conversion_pct != null ? s.conversion_pct + '% se inscribió' : 'personas que abrieron el formulario'));
    if (s.last_at) kp.appendChild(kpi('Última inscripción', s.last_at, 'hora local'));
    body.appendChild(kp);

    if (d.capacity || d.quotas.length) {
      var sec = section('Cupos', 'Usados, porcentaje y cuántos faltan. Incluye a quien está pagando en este momento.');
      if (d.capacity) { var one = el('div', 'fs-cap-one'); one.appendChild(capacityCard(d.capacity)); sec.appendChild(one); }
      if (d.quotas.length) {
        var grid = el('div', 'fs-quotas');
        d.quotas.forEach(function (q) { grid.appendChild(quotaCard(q)); });
        sec.appendChild(grid);
      }
      body.appendChild(sec);
    }

    if (d.distributions.length) {
      var ds = section('Inscritos por variable', 'Cuántas personas eligieron cada opción.');
      var dg = el('div', 'fs-dists');
      d.distributions.forEach(function (x) { dg.appendChild(distCard(x)); });
      ds.appendChild(dg);
      body.appendChild(ds);
    }

    if (d.timeline) {
      var ts = section('Inscripciones en el tiempo');
      var card = el('div', 'gw-card'), box = el('div', 'fs-chart'), canvas = document.createElement('canvas');
      canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', 'Inscripciones en el tiempo, por periodo y acumuladas. ' + d.timeline.labels.slice(-12).map(function (l, i, arr) { var k = d.timeline.labels.length - arr.length + i; return l + ': ' + d.timeline.datasets[0].data[k] + ' nuevas, ' + d.timeline.datasets[1].data[k] + ' acumuladas'; }).join('; '));
      box.appendChild(canvas); card.appendChild(box); ts.appendChild(card); body.appendChild(ts);
      drawTimeline(d.timeline, canvas);
    }

    if (!s.registered && !d.capacity && !d.quotas.length) {
      var empty = el('div', 'gw-state fs-empty');
      empty.appendChild(el('p', 'gw-lead', 'Todavía no hay inscripciones. Las cifras aparecen aquí apenas llegue la primera.'));
      body.appendChild(empty);
    }
    body.style.minHeight = '';
  }

  function fail(message) {
    body.textContent = '';
    var box = el('div', 'gw-state gw-state--error');
    box.setAttribute('role', 'alert');
    box.appendChild(el('p', 'gw-lead', message));
    body.appendChild(box);
    updated.textContent = '';
  }

  function load() {
    var url = root.dataset.api + (testsBox && testsBox.checked ? '?include_tests=true' : '');
    updated.textContent = 'Actualizando…';
    return fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } }).then(function (res) {
      if (res.status === 401) { location.href = '/login'; return null; }
      return res.json().then(function (j) {
        if (!res.ok) throw new Error(j.detail || 'No se pudieron cargar las estadísticas');
        return j;
      });
    }).then(function (j) { if (j) paint(j); }).catch(function (e) { fail(e.message || 'No se pudieron cargar las estadísticas'); });
  }

  document.addEventListener('click', function (e) {
    if (e.target.closest('[data-fs-refresh]')) load();
  });
  if (testsBox) testsBox.addEventListener('change', load);
  new MutationObserver(function () { if (last && last.timeline) { var c = body.querySelector('.fs-chart canvas'); if (c) drawTimeline(last.timeline, c); } })
    .observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  if (window.matchMedia) { var narrowMq = window.matchMedia('(max-width: 720px)'), onNarrow = function () { if (last && last.timeline) { var c = body.querySelector('.fs-chart canvas'); if (c) drawTimeline(last.timeline, c); } }; if (narrowMq.addEventListener) narrowMq.addEventListener('change', onNarrow); }
  load();
  var again = function () { if (!document.hidden) load(); };
  if (window.GW && window.GW.poll) window.GW.poll(again, 60000); else setInterval(again, 60000);      // pausado mientras la pestaña no se usa (GW.idle)
})();
