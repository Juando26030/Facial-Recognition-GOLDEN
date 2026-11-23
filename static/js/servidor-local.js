/* Pantalla /servidor-local (Fase 6, solo en un servidor local): lista de TODOS los eventos de la nube (solo metadatos) agrupados por cliente o por calendario, y «Descargar a local» en un paso.
   Delegación de eventos, texto escapado, mensajes con showToast / showConfirm. */
(function () {
  'use strict';
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const STATUS = { creado: 'Creado', en_proceso: 'En proceso', finalizado: 'Finalizado' };
  const MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  const list = document.getElementById('slEvents');
  const search = document.getElementById('slSearch');
  const alertBox = document.getElementById('slAlert');
  let events = [], group = 'client', timer = null;

  const norm = (t) => String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  function say(kind, text) {
    alertBox.hidden = !text;
    alertBox.className = 'gw-alert gw-alert--' + (kind || 'warn');
    alertBox.textContent = text || '';
  }
  const ICONS = (document.currentScript && document.currentScript.dataset.icons) || '';
  const icon = (n, cls) => `<svg class="gw-icon ${cls || ''}" aria-hidden="true"><use href="${ICONS}#i-${n}"/></svg>`;
  const STATUS_BADGE = { creado: 'gw-badge--info', en_proceso: 'gw-badge--ok', finalizado: '' };
  const fmtDate = (d) => { if (!d) return '-'; const x = new Date(d + 'T00:00:00'); return isNaN(x) ? d : x.toLocaleDateString(); };
  function fmtShort(e) {
    if (!e.end_date || e.end_date === e.start_date) return fmtDate(e.start_date);
    const a = new Date(e.start_date + 'T00:00:00'), b = new Date(e.end_date + 'T00:00:00');
    if (isNaN(a) || isNaN(b) || a.getFullYear() !== b.getFullYear()) return `${fmtDate(e.start_date)} al ${fmtDate(e.end_date)}`;
    return `${a.toLocaleDateString(undefined, { day: '2-digit', month: '2-digit' })} – ${fmtDate(e.end_date)}`;
  }
  // Informe final: aquí no se descarga (el archivo vive en la nube), solo se muestra si está enviado o pendiente, igual que en Eventos.
  function bulb(e, compact) {
    const on = !!e.report_uploaded;
    const label = on ? 'Informe final enviado' : 'Informe final pendiente de subir';
    if (compact) return on ? `<span class="gw-bulb gw-bulb--dot gw-bulb--on" title="${label}" role="img" aria-label="${label}">${icon('check')}</span>` : `<span class="gw-bulb gw-bulb--dot" title="${label}" role="img" aria-label="${label}"></span>`;
    return on ? `<span class="gw-badge gw-badge--ok gw-bulb">${icon('check')}Informe enviado</span>` : `<span class="gw-badge gw-badge--warn gw-bulb">${icon('info')}Informe pendiente</span>`;
  }
  function stateBadge(e) {
    const shared = (e.local || {}).shared ? ' <span class="gw-badge gw-badge--info" title="Varios servidores locales trabajan este evento a la vez y se ven entre sí por internet">Compartido</span>' : '';
    if (e.leased_elsewhere) return ` <span class="gw-badge gw-badge--warn" title="Este evento está en otro servidor local">En «${esc((e.local || {}).node_name)}»</span>${shared}`;
    if (e.downloaded || e.leased_here) return ' <span class="gw-badge gw-badge--ok">En este servidor</span>' + shared;
    if (shared) return shared;
    return '';
  }
  // Misma tarjeta que la lista de Eventos (clases gw-event-card y p-cli__*); sin «Editar» ni cambio de estado: eso se hace dentro del evento, ya descargado.
  function row(e) {
    const where = [e.location, e.city].filter(Boolean).join(' · ');
    const can = !e.downloaded && !e.leased_here && (!e.leased_elsewhere || e.can_join);          // compartido (0160): también se puede sumar si ya está en otro servidor
    const action = can
      ? `<button type="button" class="gw-btn gw-btn--primary gw-btn--sm p-cli__act" data-download="${e.id}" data-name="${esc(e.name)}">${icon('download', 'gw-icon--sm')} ${e.can_join ? 'Sumarse (compartido)' : 'Descargar a local'}</button>`
      : (e.local_event_id ? `<a class="gw-btn gw-btn--primary gw-btn--sm p-cli__act" href="/kiosk/${e.local_event_id}">${icon('home', 'gw-icon--sm')} Ingresar</a>` : '');
    return `<div class="gw-card-row gw-event-card" aria-label="${esc(e.name)}">
      <div class="gw-card-row__head">
        <span class="gw-card-row__title" title="${esc(e.name)}${e.event_code ? ' (' + esc(e.event_code) + ')' : ''}"><span class="p-cli__rep p-cli__rep--full">${bulb(e)}</span><span class="p-cli__rep p-cli__rep--dot">${bulb(e, true)}</span> <span class="p-cli__nm"><span class="p-cli__name">${esc(e.name)}</span> ${e.event_code ? `<span class="gw-event-code"><span class="p-cli__paren">(</span><span class="p-cli__pfx">Código: </span>${esc(e.event_code)}<span class="p-cli__paren">)</span></span>` : ''}</span></span>
        <span class="gw-badge ${STATUS_BADGE[e.status] || ''}">${esc(STATUS[e.status] || e.status)}</span>${stateBadge(e)}
      </div>
      <p class="gw-card-row__meta p-cli__meta"><span class="p-cli__loc" title="${esc([e.tenant_name, where].filter(Boolean).join(' · '))}"><strong>${esc(e.tenant_name || 'Sin cliente')}</strong>${where ? ' · ' + esc(where) : ''}</span><span class="p-cli__sep"> · </span><span class="p-cli__date"><span class="p-cli__pfx">Fecha: </span>${fmtShort(e)}</span><span class="p-cli__sep"> · </span><span class="p-cli__coord"><span class="p-cli__pfx">Comercial: </span>${esc(e.commercial_name || '—')}<span class="p-cli__sep"> · </span><span class="p-cli__pfx">Coordinador: </span>${esc(e.coordinator_name || '—')}</span></p>
      <div class="gw-card-row__actions p-cli__acts">${action}</div>
    </div>`;
  }
  const EV_COLS = '<div class="p-cli__cols" aria-hidden="true"><span class="p-cli__c1">Evento</span><span class="p-cli__c2">Cliente · lugar</span><span class="p-cli__c3">Fecha</span><span class="p-cli__c4">Comercial / coordinador</span><span class="p-cli__c5">Estado</span><span class="p-cli__c6">Acciones</span></div>';
  function keyOf(e) {
    if (group === 'client') return e.tenant_name || e.tenant_id || 'Sin cliente';
    if (!e.start_date) return 'Sin fecha';
    const [y, m] = e.start_date.split('-');
    return MONTHS[Number(m) - 1] + ' ' + y;
  }
  function draw() {
    const q = norm(search.value.trim());
    const shown = events.filter((e) => !q || norm(e.name + ' ' + e.event_code + ' ' + (e.tenant_name || '')).includes(q));
    if (!shown.length) { list.innerHTML = '<div class="gw-state" role="status"><p class="gw-state__title">No hay eventos para mostrar</p></div>'; return; }
    const groups = new Map();
    shown.forEach((e) => { const k = keyOf(e); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(e); });
    let keys = [...groups.keys()];
    if (group === 'client') keys.sort((a, b) => a.localeCompare(b, 'es'));
    else keys = keys.sort((a, b) => (groups.get(b)[0].start_date || '').localeCompare(groups.get(a)[0].start_date || ''));
    list.innerHTML = keys.map((k) => `<section class="gw-stack"><h2 class="gw-section-title">${esc(k)}</h2><div class="gw-event-list">${EV_COLS}${groups.get(k).map(row).join('')}</div></section>`).join('');
  }
  async function load() {
    list.setAttribute('aria-busy', 'true');
    try {
      const res = await fetch('/api/local/cloud-events');
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'No se pudo cargar la lista');
      document.getElementById('slNode').textContent = d.node_name || '—';
      events = d.events || [];
      if (!d.configured) say('warn', 'Este servidor todavía no está conectado a la nube (faltan la dirección y el token del servidor). Pídele a quien lo instaló que lo configure.');
      else if (d.offline) say('warn', (d.error || 'No hay conexión con la nube') + ' Revisa el internet: la lista se carga sola al reconectar con «Actualizar lista».');
      else say('', '');
      draw();
    } catch (err) {
      list.innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">${esc(err.message)}</p></div>`;
    } finally { list.setAttribute('aria-busy', 'false'); }
  }
  async function download(btn) {
    const id = btn.dataset.download;
    if (!(await showConfirm(`Se llevará «${esc(btn.dataset.name)}» a este servidor. Desde ese momento en la nube solo se podrá ver (se libera con «Pasar a internet»). ¿Descargar a local?`, { variant: 'warning', confirmLabel: 'Sí, descargar' }))) return;
    btn.disabled = true; const old = btn.textContent; btn.textContent = 'Descargando…';
    try {
      const res = await fetch(`/api/local/cloud-events/${encodeURIComponent(id)}/download`, { method: 'POST' });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) { showToast(typeof d.detail === 'string' ? d.detail : 'No se pudo descargar el evento', 'error'); return; }
      showToast(d.message || 'Evento descargado', 'success');
      await load();
    } catch (err) {
      showToast('No se pudo descargar el evento. Revisa la conexión.', 'error');
    } finally { btn.disabled = false; btn.textContent = old; }
  }

  list.addEventListener('click', (e) => { const b = e.target.closest('[data-download]'); if (b) download(b); });
  search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(draw, 200); });
  document.addEventListener('click', (e) => {
    if (e.target.closest('#slReload')) load();
  });
  const groupSel = document.getElementById('slGroup');
  if (groupSel) groupSel.addEventListener('change', () => { group = groupSel.value === 'calendar' ? 'calendar' : 'client'; draw(); });
  load();
})();
