/* Certificados del evento (Fase 1.5): asistente de 3 pasos + enlace público. Genera un PDF por persona (BadgeRender + html2canvas + jsPDF) y los junta en un ZIP (JSZip).
   La generación es la de siempre; cambió solo la pantalla. Lee window.EVENT_ID / EVENT_CODE / EVENT_FINALIZED / CERT_ENABLED que pone la plantilla. */
(function () {
  'use strict';
  if (!window.CERT_ENABLED) return;
  var EVENT_ID = window.EVENT_ID, EVENT_CODE = window.EVENT_CODE, FINALIZED = window.EVENT_FINALIZED;
  var $ = function (id) { return document.getElementById(id); };
  var STEPS = [
    { title: 'Revisa la plantilla', count: 'Paso 1 de 3' },
    { title: 'Revisa quién recibe', count: 'Paso 2 de 3' },
    { title: 'Genera el ZIP', count: 'Paso 3 de 3' },
  ];
  var safe = function (s) { return String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^\w\-]+/g, '_').replace(/^_+|_+$/g, ''); };
  var state = { step: 0, recipients: [], total: 0, usersOk: false, tplOk: false, generating: false };
  var stage = $('renderStage');
  var main = $('genBtn'), back = $('certBack');

  function show(id, on) { var el = $(id); if (el) el.hidden = !on; }

  // ------------------------------------------------------------------ asistente
  function canAdvance() {
    if (state.step === 0) return state.tplOk;
    if (state.step === 1) return FINALIZED && state.usersOk && state.recipients.length > 0;
    return state.recipients.length > 0;
  }
  function render() {
    var s = state.step;
    for (var i = 0; i < 3; i++) show('certPanel' + (i + 1), i === s);
    $('certStepTitle').textContent = STEPS[s].title;
    $('certCount').textContent = STEPS[s].count;
    $('certBar').style.width = ((s + 1) / 3 * 100) + '%';
    $('certBar').parentNode.setAttribute('aria-valuenow', String(s + 1));
    back.hidden = s === 0 || state.generating;
    if (!main.hasAttribute('aria-busy')) main.textContent = main.getAttribute(s === 2 ? 'data-label-last' : 'data-label');
    main.disabled = !canAdvance();
  }
  function go(n) { state.step = Math.max(0, Math.min(2, n)); render(); $('certStepTitle').scrollIntoView({ block: 'nearest' }); }

  main.addEventListener('click', function () {
    if (state.step < 2) { go(state.step + 1); return; }
    state.generating = true; render();
    GW.busy(main, function () { return generate(state.recipients); }).catch(function () { /* generate() ya avisó */ }).then(function () { state.generating = false; render(); });
  });
  back.addEventListener('click', function () { go(state.step - 1); });

  // ------------------------------------------------------------------ paso 1: plantilla
  function loadTemplate() {
    show('tplLoading', true); show('tplError', false); show('tplInfo', false);
    return fetch('/api/events/' + EVENT_ID + '/badge-template?kind=certificate').then(function (r) {
      if (!r.ok) throw new Error('No se pudo cargar la plantilla del certificado');
      return r.json();
    }).then(function (t) {
      $('tplName').textContent = t.name || 'Certificado';
      $('tplSize').textContent = t.width_mm + ' × ' + t.height_mm + ' mm';
      $('tplOrient').textContent = t.width_mm >= t.height_mm ? 'Horizontal' : 'Vertical';
      var d = t.updated_at ? new Date(t.updated_at) : null;
      $('tplUpdated').textContent = d && !isNaN(d) ? d.toLocaleString('es-CO') : 'Sin ediciones todavía (diseño por defecto)';
      state.tplOk = true; show('tplLoading', false); show('tplInfo', true);
    }).catch(function (e) {
      state.tplOk = false; show('tplLoading', false); $('tplErrorText').textContent = e.message || 'Intenta de nuevo.'; show('tplError', true);
    }).then(render);
  }
  $('tplRetry').addEventListener('click', function () { GW.busy($('tplRetry'), loadTemplate); });

  // ------------------------------------------------------------------ paso 2: personas
  function loadUsers() {
    if (!FINALIZED) { render(); return Promise.resolve(); }
    show('usersLoading', true); show('usersError', false); show('usersEmpty', false); show('usersInfo', false);
    return fetch('/api/users?event_id=' + EVENT_ID).then(function (r) {
      if (!r.ok) throw new Error('No se pudo cargar la lista de personas');
      return r.json();
    }).then(function (users) {
      state.total = users.length;
      state.recipients = users.filter(function (u) { return u.certificate; });
      state.usersOk = true; show('usersLoading', false);
      if (!state.recipients.length) { show('usersEmpty', true); return; }
      $('recipCount').textContent = state.recipients.length; $('totalCount').textContent = state.total;
      var ul = $('recipNames'); ul.textContent = '';
      state.recipients.slice(0, 8).forEach(function (u) {
        var li = document.createElement('li'); li.textContent = ((u.first_name || '') + ' ' + (u.last_name || '')).trim() || String(u.id); ul.appendChild(li);
      });
      var more = state.recipients.length - 8; show('recipMore', more > 0);
      if (more > 0) $('recipMore').textContent = 'y ' + more + (more === 1 ? ' persona más.' : ' personas más.');
      show('usersInfo', true);
    }).catch(function (e) {
      state.usersOk = false; show('usersLoading', false); $('usersErrorText').textContent = e.message || 'Intenta de nuevo.'; show('usersError', true);
    }).then(render);
  }
  if ($('usersRetry')) $('usersRetry').addEventListener('click', function () { GW.busy($('usersRetry'), loadUsers); });

  // ------------------------------------------------------------------ paso 3: generar el ZIP (lógica de siempre)
  async function generate(recipients) {
    var host = $('progressHost'); host.innerHTML = '';
    var pb = ProgressBar.create(host, { title: 'Generando certificados', stage: 'Preparando…' });
    try {
      var tplRes = await fetch('/api/events/' + EVENT_ID + '/badge-template?kind=certificate');
      if (!tplRes.ok) throw new Error('No se pudo cargar la plantilla del certificado');
      var template = await tplRes.json();
      var jsPDF = window.jspdf.jsPDF;
      var zip = new JSZip();
      var used = new Set();
      for (var i = 0; i < recipients.length; i++) {
        var u = recipients[i];
        pb.update(i / recipients.length, 'Generando ' + (i + 1) + ' de ' + recipients.length + ': ' + (u.first_name || '') + ' ' + (u.last_name || ''));
        var data = await (await fetch('/api/users/' + encodeURIComponent(u.id) + '/badge-print-data?certificate=1&event_id=' + EVENT_ID)).json();
        BadgeRender.renderBadge(stage, template, data, { eventId: EVENT_ID });
        await document.fonts.ready;
        await Promise.all(Array.from(stage.querySelectorAll('img')).map(function (img) { return img.decode ? img.decode().catch(function () {}) : null; }));
        var canvas = await html2canvas(stage, { scale: 2, useCORS: true, backgroundColor: '#ffffff' });
        var w = template.width_mm, h = template.height_mm;
        var pdf = new jsPDF({ orientation: w >= h ? 'landscape' : 'portrait', unit: 'mm', format: [w, h] });
        pdf.addImage(canvas.toDataURL('image/jpeg', 0.92), 'JPEG', 0, 0, w, h);
        var name = safe(u.id) + '_' + safe(u.first_name) + '_' + safe(u.last_name) + '.pdf';
        for (var n = 2; used.has(name); n++) name = name.replace(/(_\d+)?\.pdf$/, '_' + n + '.pdf');
        used.add(name);
        zip.file(name, pdf.output('arraybuffer'));
      }
      pb.update(0.99, 'Comprimiendo…');
      var blob = await zip.generateAsync({ type: 'blob' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'Certificados_' + EVENT_CODE + '.zip';
      a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 5000);
      pb.finish('Listo: ' + recipients.length + ' certificados en el ZIP.');
      showToast('ZIP de certificados generado', 'success');
    } catch (e) {
      showToast(e.message || 'No se pudieron generar los certificados', 'error');
      pb.fail(e.message || 'No se pudieron generar los certificados');
    } finally {
      stage.innerHTML = '';
    }
  }

  // ------------------------------------------------------------------ enlace público (mismo servicio que usa el diseñador)
  var linkApi = '/api/events/' + EVENT_ID + '/certificates/public-link';
  function linkError(msg) { $('linkErrorText').textContent = msg || ''; show('linkError', !!msg); }
  function loadLink() {
    show('linkLoading', true); show('linkNone', false); show('linkHave', false); linkError('');
    return fetch(linkApi).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }).then(function (d) {
      show('linkLoading', false);
      if (d && d.url) { $('clInput').value = d.url; $('clOpen').href = d.url; show('linkHave', true); } else { show('linkNone', true); }
    });
  }
  function postLink(regenerate) {
    return fetch(linkApi + (regenerate ? '?regenerate=true' : ''), { method: 'POST' }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) { if (!r.ok) throw new Error(d.detail || 'No se pudo generar el enlace'); return d; });
    });
  }
  $('clGenerate').addEventListener('click', function () {
    GW.busy($('clGenerate'), function () { return postLink(false).then(function () { showToast('Enlace generado', 'success'); return loadLink(); }); })
      .catch(function (e) { linkError(e.message); showToast(e.message, 'error'); });
  });
  $('clCopy').addEventListener('click', function () {
    var input = $('clInput');
    var done = function () { showToast('Enlace copiado', 'success'); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(input.value).then(done, function () { input.select(); document.execCommand('copy'); done(); });
    else { input.select(); document.execCommand('copy'); done(); }
  });
  $('clRegen').addEventListener('click', async function () {
    var ok = await showConfirm('Se creará un enlace nuevo y el anterior dejará de funcionar. Quien tenga el enlace actual ya no podrá descargar su certificado con él. ¿Continuar?', { variant: 'danger', confirmLabel: 'Sí, cambiar enlace' });
    if (!ok) return;
    GW.busy($('clRegen'), function () { return postLink(true).then(function () { showToast('Enlace cambiado', 'success'); return loadLink(); }); })
      .catch(function (e) { linkError(e.message); showToast(e.message, 'error'); });
  });

  render();
  loadTemplate();
  loadUsers();
  loadLink();
})();
