/* Tarjeta de la persona encontrada en Control de inventario y Control de zonas (25-nov-2026, Juan David).
   Muestra SIEMPRE cédula, nombres y apellidos, más los campos marcados «Mostrar en el registro» (Parámetros › Campos; window.REG_CARD_FIELDS, los mismos de la tarjeta de Registro),
   el estado en Registro (Registrado / No registrado: en rojo, como alerta) y, a su lado, el botón de la acción (Entregar / Acreditar). Pura: devuelve HTML; la página lo pone donde quiera. */
(function (root) {
  'use strict';
  const ALWAYS = ['id', 'first_name', 'last_name'];
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

  /* Valor legible de un campo de la tarjeta (misma regla que la tarjeta de Registro, static/js/directory.js). */
  function valueOf(u, c) {
    if (c.key === 'categories') return (u.categories || []).join(', ');
    if (c.key === 'certificate') return u.certificate ? 'Sí' : 'No';
    if (c.key === 'dependents') return u.dependents != null ? String(u.dependents) : '';
    if (c.type === 'signature') return '';
    const extras = u.extra_fields || {};
    const raw = Object.prototype.hasOwnProperty.call(u, c.key) && String(c.key).indexOf('opcional_') !== 0 ? u[c.key] : extras[c.key];
    const t = String(raw == null ? '' : raw).trim();
    if (c.type === 'boolean' || c.type === 'consent') return t.toLowerCase() === 'true' ? 'Sí' : (t.toLowerCase() === 'false' ? 'No' : '');
    return t;
  }

  /* Campos extra de la tarjeta: [{label, value}] (sin cédula, nombres ni apellidos, que van arriba). Vacíos también, con «—», para que se vea qué falta. */
  function extraFields(u, cardFields) {
    const list = Array.isArray(cardFields) ? cardFields : (Array.isArray(root.REG_CARD_FIELDS) ? root.REG_CARD_FIELDS : []);
    return list.filter((c) => ALWAYS.indexOf(c.key) < 0 && c.type !== 'signature').map((c) => ({ key: c.key, label: c.label, value: valueOf(u, c) }));
  }

  const isRegistered = (u) => !!u && u.status !== 'No registrado';

  /* opts: {action: HTML del botón (opcional), note: texto pequeño (opcional), cardFields} → {cls, html}: la clase del <article> y su contenido. */
  function render(u, opts) {
    opts = opts || {};
    const reg = isRegistered(u);
    const initial = esc((String(u.first_name || '?').trim()[0] || '?').toUpperCase());
    const fields = extraFields(u, opts.cardFields);
    const dl = fields.length
      ? `<dl class="gw-pcard__fields">${fields.map((f) => `<div class="gw-pcard__f"><dt>${esc(f.label)}</dt><dd>${f.value ? esc(f.value) : '<span class="gw-hint">—</span>'}</dd></div>`).join('')}</dl>`
      : '';
    const state = reg
      ? '<span class="gw-badge gw-badge--ok gw-pcard__state">Registrado</span>'
      : '<span class="gw-badge gw-badge--err gw-pcard__state" role="alert">No registrado</span>';
    const warn = reg ? '' : '<p class="gw-pcard__alert">Esta persona NO está registrada en el evento (Registro).</p>';
    return {
      cls: 'gw-person gw-person--big gw-pcard ' + (reg ? 'gw-person--ok' : 'gw-person--err gw-pcard--unreg'),
      html: `<div class="gw-person__photo" aria-hidden="true">${initial}</div>`
        + `<div class="gw-person__body"><h3 class="gw-person__name">${esc(u.first_name)} ${esc(u.last_name)}</h3><p class="gw-person__meta">Cédula: ${esc(u.id)}${u.code ? ' · Código: ' + esc(u.code) : ''}</p>${warn}${dl}${opts.note ? `<p class="gw-hint">${opts.note}</p>` : ''}</div>`
        + `<div class="gw-person__status gw-pcard__side">${state}${opts.action || ''}</div>`,
    };
  }

  const api = { render, extraFields, valueOf, isRegistered };
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.GWPersonCard = api;
}(typeof self !== 'undefined' ? self : this));
