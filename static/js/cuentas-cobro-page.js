/* Pantalla /cuentas-de-cobro (Fase 8): cuentas de Wompi de terceros, asignación a formularios y QR. Las llaves secretas solo viajan al guardar; nunca se muestran de vuelta.
   Delegación de eventos, texto escapado, mensajes con showToast/showConfirm. El QR se dibuja en el navegador (qrcode-generator). */
(function () {
  'use strict';
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const accBox = document.getElementById('accounts');
  const frmBox = document.getElementById('forms');
  let accounts = [];
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

  function accountRow(a) {
    const env = a.env === 'test' ? 'Pruebas' : 'Producción';
    const warn = !a.keys_readable ? '<br><span class="gw-text-danger">Las llaves no se pueden leer (cambió la llave de cifrado del servidor). Vuelve a pegarlas.</span>' : '';
    return `<li class="gw-list__item" data-id="${a.id}"><div><strong>${esc(a.name)}</strong> <span class="gw-badge">${env}</span> ${a.active ? '' : '<span class="gw-badge">Desactivada</span>'}
      <br><span class="gw-hint">${a.holder ? 'Titular: ' + esc(a.holder) + ' · ' : ''}Llave pública ${esc(a.public_key_masked)} · ${a.forms} formulario(s) · ${a.has_private ? 'con llave privada (reembolsos y enlaces)' : 'sin llave privada'}</span>
      <br><span class="gw-hint">URL de eventos para pegar en Wompi: <code>${esc(a.webhook_url)}</code></span>${warn}</div>
      <div class="gw-card-row__actions">
        <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-check="${a.id}">Probar</button>
        ${a.has_private ? `<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-link="${a.id}">Crear enlace de pago</button>` : ''}
        <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-edit="${a.id}">Cambiar llaves</button>
        <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-toggle="${a.id}">${a.active ? 'Desactivar' : 'Activar'}</button>
        <button type="button" class="gw-btn gw-btn--ghost gw-btn--sm" data-del="${a.id}" data-name="${esc(a.name)}">Borrar</button></div></li>`;
  }

  async function load() {
    try {
      const d = await api('/api/payment-accounts');
      accounts = d.accounts;
      const warn = d.encryption_ready ? '' : '<div class="gw-alert gw-alert--warn" role="status">Falta <code>PAYMENT_KEYS_ENCRYPTION_KEY</code> en el servidor: no se pueden guardar cuentas nuevas.</div>';
      accBox.innerHTML = warn + (accounts.length ? `<ul class="gw-list">${accounts.map(accountRow).join('')}</ul>` : '<div class="gw-state" role="status"><p class="gw-state__title">Todavía no hay cuentas de terceros</p></div>');
    } catch (err) { accBox.innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">${esc(err.message)}</p></div>`; }
    finally { accBox.setAttribute('aria-busy', 'false'); }
    await loadForms();
  }

  async function loadForms() {
    try {
      const d = await api('/api/payment-accounts-forms');
      const opts = (sel) => '<option value="">Cuenta de Golden</option>' + accounts.filter((a) => a.active || a.id === sel).map((a) => `<option value="${a.id}"${a.id === sel ? ' selected' : ''}>${esc(a.name)}</option>`).join('');
      frmBox.innerHTML = d.forms.length ? `<ul class="gw-list">${d.forms.map((f) => `<li class="gw-list__item"><div><strong>${esc(f.name)}</strong> <span class="gw-hint">${esc(f.event)}</span></div>
        <div class="gw-card-row__actions"><select class="gw-input gw-input--short" data-assign="${f.id}" data-event="${f.event_id}" aria-label="Cuenta de cobro de ${esc(f.name)}">${opts(f.payment_account_id)}</select>
        <button type="button" class="gw-btn gw-btn--secondary gw-btn--sm" data-qr="${esc(f.url)}" data-title="${esc(f.name)}">QR</button></div></li>`).join('')}</ul>`
        : '<div class="gw-state" role="status"><p class="gw-state__title">No hay formularios</p></div>';
    } catch (err) { frmBox.innerHTML = `<div class="gw-state gw-state--error" role="alert"><p class="gw-state__title">${esc(err.message)}</p></div>`; }
    finally { frmBox.setAttribute('aria-busy', 'false'); }
  }

  function modal(title, bodyHtml, onSubmit, okLabel) {
    const back = document.createElement('div');
    back.className = 'gw-modal-backdrop';
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
          <div class="gw-field"><label class="gw-label">Titular (opcional)</label><input class="gw-input" name="holder" maxlength="120"></div>${keyFields}`,
          async (v) => { await send('POST', '/api/payment-accounts', v); showToast('Cuenta guardada', 'success'); await load(); });
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

  document.addEventListener('change', async (e) => {
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
