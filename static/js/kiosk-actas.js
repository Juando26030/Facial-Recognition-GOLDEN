/* Acta de novedades (Fase 10): lista, escritura, firma dibujada y documento imprimible. API: app/routers/event_acts.py. */
(function () {
  'use strict';
  const main = document.querySelector('main[data-event-id]');
  if (!main) return;
  const EVENT_ID = main.dataset.eventId, ICONS = main.dataset.icons;
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const icon = (n) => '<svg class="gw-icon gw-icon--sm" aria-hidden="true"><use href="' + ICONS + '#i-' + n + '"/></svg>';
  const busy = (btn, work) => (window.GW && GW.busy ? GW.busy(btn, work) : Promise.resolve(work()));
  const base = '/api/events/' + EVENT_ID + '/acts';
  const BADGE = { borrador: 'gw-badge', firma_pendiente: 'gw-badge gw-badge--warn', firmada: 'gw-badge gw-badge--ok' };
  let canWrite = false, isClient = false, openId = null, editing = null, drawn = false;

  const when = (iso) => (iso ? new Date(iso).toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' }) : '');
  async function api(url, opts) {
    const res = await fetch(url, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { const e = new Error(data.detail || 'No se pudo completar la acción'); e.status = res.status; throw e; }
    return data;
  }
  const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  function setList(html, loading) { $('actList').innerHTML = html; $('actList').setAttribute('aria-busy', loading ? 'true' : 'false'); }

  async function loadList() {
    let data;
    try { data = await api(base); } catch (err) {
      setList('<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">No se pudieron cargar las actas</p><p class="gw-state__text">Revisa tu conexión e inténtalo de nuevo.</p><button type="button" class="gw-btn gw-btn--secondary" data-retry>Reintentar</button></div>');
      return;
    }
    canWrite = data.can_write; isClient = data.is_client;
    $('actForm').hidden = !canWrite;
    $('actCount').textContent = data.acts.length ? '(' + data.acts.length + ')' : '';
    if (!data.acts.length) {
      setList('<div class="gw-state"><p class="gw-state__title">Todavía no hay actas</p><p class="gw-state__text">' + (canWrite ? 'Escribe la primera arriba y pídele al cliente que la firme.' : 'Cuando el coordinador escriba un acta, la verás aquí para firmarla.') + '</p></div>', false);
      return;
    }
    setList(data.acts.map((a) => `
      <article class="gw-card-row">
        <div class="gw-card-row__head"><h3 class="gw-card-row__title">${esc(a.title)}</h3><span class="${BADGE[a.status] || 'gw-badge'}">${esc(a.status_label)}</span></div>
        <p class="gw-card-row__meta">${esc(when(a.created_at))} · Coordinador: ${a.coordinator_signed ? 'firmó' : 'falta'} · Cliente: ${a.client_signed ? 'firmó' : 'falta'}</p>
        <div class="gw-card-row__actions">
          <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-open="${a.id}">${icon('form')} ${(isClient && !a.client_signed) || (canWrite && !a.coordinator_signed) ? 'Abrir y firmar' : 'Abrir'}</button>
          <a class="gw-btn gw-btn--secondary gw-btn--sm" href="${base}/${a.id}/print" target="_blank" rel="noopener">${icon('download')} Imprimir</a>
          <a class="gw-btn gw-btn--secondary gw-btn--sm" href="${base}/${a.id}/print?download=1">${icon('download')} Descargar</a>
          ${a.status === 'firmada' && a.pdf ? `<a class="gw-btn gw-btn--primary gw-btn--sm" href="${base}/${a.id}/pdf">${icon('download')} Descargar PDF</a>` : ''}
          ${a.status === 'firmada' && !a.pdf && canWrite ? `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-pdf="${a.id}">Generar PDF</button>` : ''}
        </div>
      </article>`).join(''), false);
  }

  function sigBlock(el, label, side, act) {
    const signed = act[side + '_signed'], mine = isClient ? side === 'client' : canWrite;          // el coordinador firma la suya y, en su tableta, la del cliente sin cuenta
    let html = '<h3 class="gw-card__title">' + label + '</h3>';
    if (signed) {
      html += '<img class="gw-acta-img" alt="Firma del ' + label.toLowerCase() + '" src="' + base + '/' + act.id + '/signature/' + side + '?t=' + encodeURIComponent(act[side + '_signed_at'] || '') + '">' +
        '<p class="gw-acta-sig__name">' + esc(act[side + '_name'] || '') + ' · ' + esc(when(act[side + '_signed_at'])) + '</p>';
    } else if (mine) {
      if (side === 'client' && !isClient) html += '<div class="gw-field"><label class="gw-label" for="signerName">Nombre de quien firma por el cliente *</label><input class="gw-input" type="text" id="signerName" maxlength="160" autocomplete="off"></div>';
      html += '<canvas class="gw-acta-pad" data-pad="' + side + '" role="img" aria-label="Espacio para dibujar tu firma con el dedo o el mouse"></canvas>' +
        '<div class="gw-actions"><button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-pad-clear>Borrar y repetir</button>' +
        '<button type="button" class="gw-btn gw-btn--primary gw-btn--sm" data-pad-sign="' + side + '">Firmar</button></div>' +
        '<p class="gw-hint">Dibuja tu firma en el recuadro y pulsa «Firmar».</p>';
    } else {
      html += '<div class="gw-acta-pending">Pendiente de firma</div>';
    }
    el.innerHTML = html;
  }

  function initPad(canvas) {
    const ratio = window.devicePixelRatio || 1, rect = canvas.getBoundingClientRect();
    canvas.width = Math.round(rect.width * ratio); canvas.height = Math.round(rect.height * ratio);
    const ctx = canvas.getContext('2d');
    ctx.scale(ratio, ratio); ctx.lineWidth = 2.5; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = 'rgb(0, 0, 0)';
    drawn = false;
    let down = false, last = null;
    const pos = (e) => { const r = canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
    canvas.addEventListener('pointerdown', (e) => { down = true; last = pos(e); canvas.setPointerCapture(e.pointerId); ctx.beginPath(); ctx.arc(last.x, last.y, 1.2, 0, 7); ctx.fill(); drawn = true; e.preventDefault(); });
    canvas.addEventListener('pointermove', (e) => { if (!down) return; const p = pos(e); ctx.beginPath(); ctx.moveTo(last.x, last.y); ctx.lineTo(p.x, p.y); ctx.stroke(); last = p; });
    ['pointerup', 'pointercancel'].forEach((ev) => canvas.addEventListener(ev, () => { down = false; }));
    canvas._clear = () => { ctx.clearRect(0, 0, canvas.width, canvas.height); drawn = false; };
  }

  async function openAct(id) {
    $('actDetail').hidden = false;
    $('actDetailTitle').textContent = 'Abriendo…';
    let a;
    try { a = await api(base + '/' + id); } catch (err) { showToast(err.message, 'error'); $('actDetail').hidden = true; return; }
    openId = a.id;
    $('actDetailTitle').textContent = a.title;
    const st = $('actDetailStatus'); st.className = BADGE[a.status] || 'gw-badge'; st.textContent = a.status_label;
    $('actDetailBody').innerHTML = a.format === 'list' ? '<ul>' + a.body.split('\n').map((l) => '<li>' + esc(l) + '</li>').join('') + '</ul>' : esc(a.body);
    sigBlock($('sigCoordinator'), 'Coordinador', 'coordinator', a);
    sigBlock($('sigClient'), 'Cliente', 'client', a);
    $('actDetailActions').innerHTML =
      (canWrite && a.status !== 'firmada' ? '<button type="button" class="gw-btn gw-btn--secondary" data-edit="' + a.id + '">Editar el texto</button>' : '') +
      (canWrite && a.status === 'borrador' ? '<button type="button" class="gw-btn gw-btn--danger-outline" data-del="' + a.id + '">' + icon('trash') + ' Borrar el acta</button>' : '') +
      (a.status === 'firmada' && a.pdf ? '<a class="gw-btn gw-btn--primary" href="' + base + '/' + a.id + '/pdf">' + icon('download') + ' Descargar PDF</a>' : '') +
      (a.status === 'firmada' && !a.pdf && canWrite ? '<button type="button" class="gw-btn gw-btn--secondary" data-pdf="' + a.id + '">Generar el PDF</button>' : '') +
      '<button type="button" class="gw-btn gw-btn--secondary" data-close>Cerrar</button>';
    document.querySelectorAll('[data-pad]').forEach(initPad);
    $('actDetail').scrollIntoView({ behavior: 'smooth', block: 'start' });
    $('actDetail').dataset.act = JSON.stringify({ id: a.id, title: a.title, format: a.format, body: a.body, status: a.status });
  }

  function closeDetail() { openId = null; $('actDetail').hidden = true; }
  function resetForm() { editing = null; $('actForm').reset(); $('actFormTitle').textContent = 'Nueva acta'; $('actSave').textContent = 'Guardar acta'; $('actCancel').hidden = true; }

  $('actForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const body = { title: $('actTitle').value, format: $('actFormat').value, body: $('actBody').value };
    const send = async (confirmReset) => {
      if (editing) return api(base + '/' + editing, json('PUT', { ...body, confirm_reset: confirmReset }));
      return api(base, json('POST', body));
    };
    busy($('actSave'), async () => {
      try { return await send(false); } catch (err) {
        if (err.status === 409 && editing) {
          if (!(await showConfirm(err.message, { confirmLabel: 'Cambiar y quitar la firma' }))) return null;
          return send(true);
        }
        throw err;
      }
    }).then((a) => {
      if (!a) return;
      showToast(editing ? 'Acta actualizada' : 'Acta guardada. Ahora falta firmarla.', 'success');
      resetForm(); loadList(); openAct(a.id);
    }).catch((err) => showToast(err.message, 'error'));
  });
  $('actCancel').addEventListener('click', resetForm);

  document.addEventListener('click', async (e) => {
    const t = e.target;
    if (!(t instanceof Element)) return;
    const open = t.closest('[data-open]'), edit = t.closest('[data-edit]'), del = t.closest('[data-del]'), clear = t.closest('[data-pad-clear]'), sign = t.closest('[data-pad-sign]');
    const pdf = t.closest('[data-pdf]');
    if (pdf) {
      busy(pdf, () => api(base + '/' + pdf.dataset.pdf + '/pdf/regenerate', { method: 'POST' }))
        .then(() => { showToast('PDF listo', 'success'); loadList(); if (openId) openAct(openId); }).catch((err) => showToast(err.message, 'error'));
      return;
    }
    if (t.closest('[data-retry]')) { loadList(); return; }
    if (open) { openAct(open.dataset.open); return; }
    if (t.closest('[data-close]')) { closeDetail(); return; }
    if (edit) {
      const a = JSON.parse($('actDetail').dataset.act || '{}');
      editing = a.id; $('actTitle').value = a.title; $('actFormat').value = a.format; $('actBody').value = a.body;
      $('actFormTitle').textContent = 'Editar el acta'; $('actSave').textContent = 'Guardar cambios'; $('actCancel').hidden = false;
      $('actForm').hidden = false; $('actForm').scrollIntoView({ behavior: 'smooth', block: 'start' }); $('actTitle').focus();
      return;
    }
    if (del) {
      if (!(await showConfirm('¿Borrar esta acta? No se puede recuperar.', { confirmLabel: 'Sí, borrarla' }))) return;
      busy(del, () => api(base + '/' + del.dataset.del, { method: 'DELETE' })).then(() => { showToast('Acta borrada', 'success'); closeDetail(); loadList(); }).catch((err) => showToast(err.message, 'error'));
      return;
    }
    if (clear) { const c = clear.closest('.gw-acta-sig').querySelector('canvas'); if (c && c._clear) c._clear(); return; }
    if (sign) {
      const canvas = sign.closest('.gw-acta-sig').querySelector('canvas');
      if (sign.dataset.padSign === 'client' && !isClient && $('signerName') && $('signerName').value.trim().length < 3) { showToast('Escribe el nombre de quien firma por el cliente', 'error'); $('signerName').focus(); return; }
      if (!drawn) { showToast('Dibuja tu firma en el recuadro antes de firmar', 'error'); return; }
      if (!(await showConfirm('Al firmar confirmas que el texto del acta es correcto. ¿Firmar ahora?', { confirmLabel: 'Sí, firmar' }))) return;
      busy(sign, () => api(base + '/' + openId + '/sign', json('POST', { signature: canvas.toDataURL('image/png'), side: sign.dataset.padSign, signer_name: ($('signerName') || {}).value || '' })))
        .then(() => { showToast('Firma guardada', 'success'); loadList(); openAct(openId); })
        .catch((err) => showToast(err.message, 'error'));
    }
  });

  loadList();
})();
