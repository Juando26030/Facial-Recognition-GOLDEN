/* Pantalla /cuentas-de-cobro (Fase 8): cuentas de Wompi de terceros, asignación a formularios y QR. Las llaves secretas solo viajan al guardar; nunca se muestran de vuelta.
   Delegación de eventos, texto escapado, mensajes con showToast/showConfirm. El QR se dibuja en el navegador (qrcode-generator). */
(function () {
  'use strict';
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const accBox = document.getElementById('accounts');
  const frmBox = document.getElementById('forms');
  let accounts = [];
  let formsData = [];
  let eventsData = [];
  async function api(path, opts) {
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo completar la acción');
    return data;
  }
  const send = (method, path, body) => api(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  const fail = (err) => showToast(err.message, 'error');

  function qrSvg(text, size) {
    const qr = qrcode(0, 'M');
    qr.addData(text);
    qr.make();
    return qr.createSvgTag({ cellSize: size || 6, margin: 2, scalable: true });
  }

  function scopeText(a) {
    if (a.scope === 'evento') return 'Pertenece al evento: ' + (a.event_name || 'evento eliminado');
    if (a.scope === 'formulario') return 'Pertenece al formulario: ' + (a.form_name || 'formulario eliminado') + (a.event_name ? ' (' + a.event_name + ')' : '');
    if (a.scope === 'panelista') return 'Cuenta de panelista: ' + (a.panelist_ref || '') + (a.event_name ? ' · evento ' + a.event_name : '');
    return 'De uso general: se puede asignar a cualquier formulario';
  }
  // Mismo criterio que app/payment_accounts.usable_for_form (el servidor vuelve a validar).
  function usable(a, f) {
    if (a.scope === 'evento') return a.event_id != null && a.event_id === f.event_id;
    if (a.scope === 'formulario') return a.form_id != null && a.form_id === f.id;
    if (a.scope === 'panelista' && a.event_id != null) return a.event_id === f.event_id;
    return true;
  }
  const opt = (v, t, sel) => `<option value="${esc(v)}"${sel ? ' selected' : ''}>${esc(t)}</option>`;
  function ownerFields(a) {
    a = a || { scope: 'general' };
    const ev = eventsData.map((e) => opt(e.id, e.name, a.event_id === e.id)).join('');
    const fm = formsData.map((f) => opt(f.id, f.name + ' · ' + f.event, a.form_id === f.id)).join('');
    return `<div class="gw-field"><label class="gw-label" for="ownScope">¿A qué pertenece esta cuenta?</label>
      <select class="gw-input" id="ownScope" name="scope" data-scope>${[['general', 'A nada en particular (la puede usar cualquier formulario)'], ['evento', 'A un evento'], ['formulario', 'A un formulario'], ['panelista', 'A un panelista']].map((o) => opt(o[0], o[1], a.scope === o[0])).join('')}</select></div>
      <div class="gw-field" data-own="evento panelista"><label class="gw-label" for="ownEvent">Evento</label><select class="gw-input" id="ownEvent" name="event_id"><option value="">Elige un evento</option>${ev}</select></div>
      <div class="gw-field" data-own="formulario"><label class="gw-label" for="ownForm">Formulario</label><select class="gw-input" id="ownForm" name="form_id"><option value="">Elige un formulario</option>${fm}</select></div>
      <div class="gw-field" data-own="panelista"><label class="gw-label" for="ownPanel">Panelista (nombre o correo)</label><input class="gw-input" id="ownPanel" name="panelist_ref" maxlength="120" value="${esc(a.panelist_ref || '')}"></div>`;
  }
  function syncOwner(root) {
    const sc = root.querySelector('[data-scope]');
    if (!sc) return;
    root.querySelectorAll('[data-own]').forEach((el) => { el.hidden = !el.dataset.own.split(' ').includes(sc.value); });
    const evSel = root.querySelector('#ownEvent');
    if (evSel) evSel.required = sc.value === 'evento';
    const fmSel = root.querySelector('#ownForm');
    if (fmSel) fmSel.required = sc.value === 'formulario';
    const pn = root.querySelector('#ownPanel');
    if (pn) pn.required = sc.value === 'panelista';
  }

  function accountRow(a) {
    const env = a.env === 'test' ? 'Pruebas' : 'Producción';
    const warn = !a.keys_readable ? '<br><span class="gw-text-danger">Las llaves no se pueden leer (cambió la llave de cifrado del servidor). Vuelve a pegarlas.</span>' : '';
    return `<li class="gw-list__item" data-id="${a.id}"><div><strong>${esc(a.name)}</strong> <span class="gw-badge">${env}</span> ${a.active ? '' : '<span class="gw-badge">Desactivada</span>'}
      <br><span class="gw-hint">${esc(scopeText(a))}</span>
      <br><span class="gw-hint">${a.holder ? 'Titular: ' + esc(a.holder) + ' · ' : ''}Llave pública ${esc(a.public_key_masked)} · ${a.forms} formulario(s) · ${a.has_private ? 'con llave privada (reembolsos y enlaces)' : 'sin llave privada'}</span>
      <br><span class="gw-hint">URL de eventos para pegar en Wompi: <code>${esc(a.webhook_url)}</code></span>${warn}</div>
      <div class="gw-card-row__actions">
        <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-check="${a.id}">Probar</button>
        ${a.has_private ? `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-link="${a.id}">Crear enlace de pago</button>` : ''}
        <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-owner="${a.id}">A qué pertenece</button>
        <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-edit="${a.id}">Cambiar llaves</button>
        <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-toggle="${a.id}">${a.active ? 'Desactivar' : 'Activar'}</button>
        <button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-del="${a.id}" data-name="${esc(a.name)}">Borrar</button></div></li>`;
  }

  async function load() {
    try {
      const d = await api('/api/payment-accounts');
      accounts = d.accounts;
      const warn = d.encryption_ready ? '' : '<div class="gw-alert gw-alert--warn" role="status">Falta la llave de cifrado de cuentas de cobro en el servidor: no se pueden guardar cuentas nuevas. Avísale al administrador técnico.</div>';
      accBox.innerHTML = warn + (accounts.length ? `<ul class="gw-list">${accounts.map(accountRow).join('')}</ul>` : '<div class="gw-state" role="status"><p class="gw-state__title">Todavía no hay cuentas de terceros</p></div>');
    } catch (err) { accBox.innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">${esc(err.message)}</p></div>`; }
    finally { accBox.setAttribute('aria-busy', 'false'); }
    await loadForms();
  }

  async function loadForms() {
    try {
      const d = await api('/api/payment-accounts-forms');
      formsData = d.forms;
      eventsData = d.events || [];
      const opts = (sel, f) => '<option value="">Cuenta de Golden</option>' + accounts.filter((a) => (a.active && usable(a, f)) || a.id === sel).map((a) => `<option value="${a.id}"${a.id === sel ? ' selected' : ''}>${esc(a.name)}</option>`).join('');
      frmBox.innerHTML = d.forms.length ? `<ul class="gw-list">${d.forms.map((f) => `<li class="gw-list__item"><div><strong>${esc(f.name)}</strong> <span class="gw-hint">${esc(f.event)}</span></div>
        <div class="gw-card-row__actions"><select class="gw-input gw-input--short" data-assign="${f.id}" data-event="${f.event_id}" aria-label="Cuenta de cobro de ${esc(f.name)}">${opts(f.payment_account_id, f)}</select>
        <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-qr="${esc(f.url)}" data-title="${esc(f.name)}">QR</button></div></li>`).join('')}</ul>`
        : '<div class="gw-state" role="status"><p class="gw-state__title">No hay formularios</p></div>';
    } catch (err) { frmBox.innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">${esc(err.message)}</p></div>`; }
    finally { frmBox.setAttribute('aria-busy', 'false'); }
  }

  function modal(title, bodyHtml, onSubmit, okLabel) {
    const back = document.createElement('div');
    back.className = 'gw-modal-backdrop';
    back.setAttribute('data-open', 'true');      // sin esto el cuadro nunca se veía (el CSS lo deja oculto): «Agregar cuenta» parecía no hacer nada
    back.innerHTML = `<div class="gw-modal gw-modal--dialog" role="dialog" aria-modal="true" aria-label="${esc(title)}"><form autocomplete="off"><div class="gw-modal__head"><h2>${esc(title)}</h2></div>
      <div class="gw-modal__body">${bodyHtml}<p class="gw-text-danger" data-err hidden></p></div>
      <div class="gw-modal__foot"><button type="button" class="gw-btn gw-btn--secondary" data-cancel>Cerrar</button>${onSubmit ? `<button type="submit" class="gw-btn gw-btn--primary">${esc(okLabel || 'Guardar')}</button>` : ''}</div></form></div>`;
    document.body.appendChild(back);
    const close = () => back.remove();
    back.querySelector('[data-cancel]').addEventListener('click', close);
    back.querySelector('form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const err = back.querySelector('[data-err]');
      err.hidden = true;
      try { if (onSubmit) await onSubmit(Object.fromEntries(new FormData(e.target).entries()), back); close(); } catch (ex) { err.textContent = ex.message; err.hidden = false; }
    });
    return back;
  }

  const keyFields = `<div class="gw-field"><label class="gw-label">Llave pública (pub_…)</label><input class="gw-input" name="public_key" required></div>
    <div class="gw-field"><label class="gw-label">Llave privada (prv_…) — opcional; hace falta para reembolsos y enlaces</label><input class="gw-input" type="password" name="private_key"></div>
    <div class="gw-field"><label class="gw-label">Secreto de integridad</label><input class="gw-input" type="password" name="integrity_secret" required></div>
    <div class="gw-field"><label class="gw-label">Secreto de eventos</label><input class="gw-input" type="password" name="events_secret" required></div>`;

  document.addEventListener('click', async (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    try {
      if (b.hasAttribute('data-new')) {
        modal('Agregar cuenta de cobro', `<div class="gw-field"><label class="gw-label">Nombre</label><input class="gw-input" name="name" maxlength="80" required></div>
          <div class="gw-field"><label class="gw-label">Titular (opcional)</label><input class="gw-input" name="holder" maxlength="120"></div>${ownerFields()}${keyFields}`,
          async (v) => { await send('POST', '/api/payment-accounts', v); showToast('Cuenta guardada', 'success'); await load(); }).dispatchEvent(new Event('gw-sync'));
      } else if (b.dataset.owner) {
        const a = accounts.find((x) => String(x.id) === b.dataset.owner);
        modal('A qué pertenece «' + a.name + '»', ownerFields(a),
          async (v) => { await send('PUT', `/api/payment-accounts/${a.id}`, v); showToast('Cuenta actualizada', 'success'); await load(); }).dispatchEvent(new Event('gw-sync'));
      } else if (b.dataset.edit) {
        modal('Cambiar llaves', '<p class="gw-hint">Pega todas las llaves de nuevo; las anteriores se reemplazan.</p>' + keyFields,
          async (v) => { await send('PUT', `/api/payment-accounts/${b.dataset.edit}`, v); showToast('Llaves actualizadas', 'success'); await load(); });
      } else if (b.dataset.toggle) {
        const a = accounts.find((x) => String(x.id) === b.dataset.toggle);
        await send('PUT', `/api/payment-accounts/${a.id}`, { active: !a.active });
        await load();
      } else if (b.dataset.del) {
        if (!(await showConfirm(`¿Borrar la cuenta «${b.dataset.name}» y sus llaves? Los formularios que la usan vuelven a cobrar con la de Golden.`, { variant: 'warning', confirmLabel: 'Sí, borrar' }))) return;
        await send('DELETE', `/api/payment-accounts/${b.dataset.del}`);
        showToast('Cuenta borrada', 'success');
        await load();
      } else if (b.dataset.check) {
        b.disabled = true;
        const r = await send('POST', `/api/payment-accounts/${b.dataset.check}/check`);
        b.disabled = false;
        showToast(`Wompi reconoce la cuenta${r.merchant ? ': ' + r.merchant : ''} (${r.env === 'test' ? 'pruebas' : 'producción'})`, 'success');
      } else if (b.dataset.link) {
        modal('Crear enlace de pago', `<div class="gw-field"><label class="gw-label">Nombre del cobro</label><input class="gw-input" name="name" maxlength="60" required></div>
          <div class="gw-field"><label class="gw-label">Monto en pesos (vacío = la persona lo escribe)</label><input class="gw-input" name="amount_cop" inputmode="numeric"></div>
          <div class="gw-field"><label class="gw-label">Descripción (opcional)</label><input class="gw-input" name="description" maxlength="200"></div>`,
          async (v, back) => {
            const r = await send('POST', `/api/payment-accounts/${b.dataset.link}/payment-link`, v);
            modal('Enlace listo', `<div style="max-width:16rem;margin:auto">${qrSvg(r.url, 6)}</div><p class="gw-hint"><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.url)}</a></p>`);
          }, 'Crear');
      } else if (b.dataset.qr) {
        modal('QR de ' + b.dataset.title, `<div style="max-width:16rem;margin:auto">${qrSvg(b.dataset.qr, 6)}</div><p class="gw-hint">${esc(b.dataset.qr)}</p>`);
      }
    } catch (err) { b.disabled = false; fail(err); }
  });

  document.addEventListener('gw-sync', (e) => { if (e.target && e.target.querySelector) syncOwner(e.target); }, true);
  document.addEventListener('change', async (e) => {
    const own = e.target.closest('select[data-scope]');
    if (own) { syncOwner(own.closest('.gw-modal') || document); return; }
    const s = e.target.closest('select[data-assign]');
    if (!s) return;
    try {
      await send('PUT', `/api/events/${s.dataset.event}/forms/${s.dataset.assign}`, { payment_account_id: s.value ? Number(s.value) : null });
      showToast('Cuenta de cobro asignada', 'success');
      await load();
    } catch (err) { fail(err); await load(); }
  });

  load();
})();
