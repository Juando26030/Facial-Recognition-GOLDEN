/* Vista previa de una carga de base (0161, app/roster_preview.py y app/dependents.py analyze): ANTES de cargar se ve el resumen, cómo cambia la base del evento y hasta
   10 personas repartidas por el archivo tal como quedarían en «Editar persona». Nada se guarda hasta pulsar el botón de confirmar.
   RosterPreview.confirmLoad(data, {mode: 'normal'|'append'}) → Promise<boolean> · RosterPreview.confirmDependents(data) → Promise<boolean>.
   No se cierra al hacer clic afuera (es una decisión con datos). Sin manejadores en línea. */
(function () {
  'use strict';
  const esc = (v) => (window.escapeHtml ? window.escapeHtml(String(v == null ? '' : v)) : String(v == null ? '' : v));
  const n = (v) => Number(v || 0).toLocaleString('es-CO');

  function table(caption, rows) {
    return `<div class="gw-table-wrap"><table class="gw-table"><caption>${esc(caption)}</caption><tbody>${rows.filter(Boolean).map(([k, v]) => `<tr><th scope="row">${esc(k)}</th><td><b>${typeof v === 'number' ? n(v) : esc(v)}</b></td></tr>`).join('')}</tbody></table></div>`;
  }
  function columnsHtml(c) {
    if (!c) return '';
    const list = (items, fmt) => items && items.length ? `<ul class="gw-list">${items.map(i => `<li>${fmt(i)}</li>`).join('')}</ul>` : ' ninguna';
    return `<details class="gw-form-group"><summary class="gw-form-group__summary">Columnas del archivo: ${(c.recognized || []).length} se cargan, ${(c.created || []).length} campos nuevos, ${(c.unused || []).length} no se usan</summary><div class="gw-form-group__body gw-stack">
      <div><b>Se cargan:</b>${list(c.recognized, i => `«${esc(i.title)}» → ${esc(i.field)}`)}</div>
      <div><b>Campos nuevos que se crean:</b>${list(c.created, i => `«${esc(i.title)}» → «${esc(i.field)}»`)}</div>
      <div><b>No se usan:</b>${list(c.unused, i => `«${esc(i.title)}»: ${esc(i.reason)}`)}</div></div></details>`;
  }
  const KIND_BADGE = { new: 'gw-badge--ok', enroll: 'gw-badge--info', update: 'gw-badge--warn', keep: 'gw-badge--info', skip: 'gw-badge--err' };
  function personCard(s) {
    const fields = (s.fields || []).map(f => `<div class="gw-preview__field${f.old != null ? ' gw-preview__field--changed' : ''}"><span class="gw-label">${esc(f.label)}</span>
        <input class="gw-input" type="text" value="${esc(f.value)}" readonly aria-label="${esc(f.label)}">${f.old != null ? `<span class="gw-hint">Antes: <span class="gw-preview__old">${esc(f.old || '(vacío)')}</span>${f.cleared ? ' · se borra' : ''}</span>` : ''}</div>`).join('');
    return `<article class="gw-preview__card"><div><span class="gw-badge ${KIND_BADGE[s.kind] || ''}">${esc(s.status)}</span> <span class="gw-hint">Fila ${esc(s.row)}</span></div>${fields || '<p class="gw-hint">Sin datos para mostrar.</p>'}</article>`;
  }

  function dialog(title, bodyHtml, confirmLabel) {
    return new Promise((resolve) => {
      if (typeof window.openGwDialog !== 'function') { resolve(false); return; }
      let d;
      const done = (v) => { d.close(); resolve(v); };
      d = window.openGwDialog({
        title, warning: true, bodyHtml: `<div class="gw-preview">${bodyHtml}</div>`,
        buttons: [{ id: 'gwPrevCancel', cls: 'gw-btn--secondary', label: 'Cancelar (no cargar)' }, { id: 'gwPrevOk', cls: 'gw-btn--primary', label: confirmLabel }],
        onEscape: () => done(false),
      });
      d.dlg.querySelector('#gwPrevCancel').addEventListener('click', () => done(false));
      d.dlg.querySelector('#gwPrevOk').addEventListener('click', () => done(true));
      d.dlg.querySelector('#gwPrevCancel').focus();
    });
  }

  function confirmLoad(p, opts) {
    const mode = (opts && opts.mode) || p.mode || 'normal';
    const i = p.impact || {};
    const isAppend = mode === 'append';
    const summary = table(isAppend ? 'Resumen de «Solo agregar personas nuevas»' : 'Resumen de la carga', [
      ['Filas del archivo', i.rows],
      ['Personas nuevas que se crean', i.new],
      ['Ya existen en el cliente y se inscriben en este evento', i.enroll],
      isAppend ? ['Ya están en el evento: no se tocan', i.untouched] : ['Ya están en el evento: sus datos se reemplazan', i.updated],
      i.duplicates ? ['Filas con cédula repetida (' + (isAppend ? 'se usa la primera' : 'queda la última') + ')', i.duplicates] : null,
      i.without_id ? ['Filas sin cédula (no se cargan)', i.without_id] : null,
      i.suppressed ? ['Pidieron la supresión de sus datos (no se recrean)', i.suppressed] : null,
    ]);
    const impact = `<div class="gw-alert gw-alert--info"><div><b>Cómo cambia la base del evento:</b> hoy tiene <b>${n(i.event_before)}</b> personas; después de cargar tendrá <b>${n(i.event_after)}</b>` +
      ` (${n((i.event_after || 0) - (i.event_before || 0))} más).${!isAppend && i.updated ? ` A <b>${n(i.updated)}</b> que ya estaban se les reemplazan los datos con los del archivo.` : ''}${isAppend ? ' Nadie que ya esté en el evento cambia.' : ''}</div></div>`;
    const notes = (p.notes || []).length ? `<div class="gw-alert gw-alert--warn"><div><ul class="gw-list">${p.notes.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div></div>` : '';
    const cards = (p.samples || []).length ? `<h3 class="gw-card__title">Así quedarían algunas personas</h3><p class="gw-hint">${esc(p.sample_note || '')}</p><div class="gw-preview__cards">${p.samples.map(personCard).join('')}</div>` : '';
    return dialog(isAppend ? 'Revisa antes de agregar' : 'Revisa antes de cargar', impact + summary + notes + columnsHtml(p.columns) + cards,
      isAppend ? `Sí, agregar ${n(i.new + (i.enroll || 0))} persona(s)` : 'Sí, cargar la base');
  }

  function confirmDependents(p) {
    const c = p.columns || {};
    const cols = `<div class="gw-alert gw-alert--info"><div><b>Columnas reconocidas:</b> cédula del titular = «${esc(c.holder)}»; nombre del dependiente = ${c.name ? '«' + esc(c.name) + '»' : '<i>no viene</i> (se mostrarán como «Dependiente 1, 2…»)'}; documento del dependiente = ${c.doc ? '«' + esc(c.doc) + '»' : '<i>no viene</i>'}.` +
      ((c.others || []).length ? ` Las demás columnas (${c.others.map(o => '«' + esc(o) + '»').join(', ')}) se guardan como datos de cada dependiente.` : '') + '</div></div>';
    const impact = `<div class="gw-alert gw-alert--info"><div><b>Cómo cambia la base del evento:</b> hoy hay <b>${n(p.dependents_before)}</b> dependientes en <b>${n(p.holders_with_dependents_before)}</b> titulares; después habrá <b>${n(p.dependents_after)}</b> en <b>${n(p.holders_with_dependents_after)}</b> titulares.` +
      ` El campo «Dependientes» cambia en <b>${n(p.holders_changed)}</b> persona(s). Las personas de la base de registro no cambian.</div></div>`;
    const summary = table(p.mode === 'append' ? 'Resumen («Agregar solo lo nuevo»)' : 'Resumen («Reemplazar»)', [
      ['Filas del archivo', p.rows], ['Filas que se cargan', p.loaded_rows], ['Titulares con dependientes en el archivo', p.holders],
      p.holders_not_registered ? ['Titulares que todavía no están registrados (se cargan igual; se les entrega cuando se registren)', p.holders_not_registered] : null,
      ['Filas nuevas', p.insert_rows], ['Filas que ya estaban y se conservan', p.kept_rows], p.updated_rows ? ['…de ellas, con datos corregidos (edad, notas…)', p.updated_rows] : null, p.delete_rows ? ['Filas que ya no vienen y se borran', p.delete_rows] : null,
      p.kept_delivered ? ['Filas que ya no vienen pero tienen entregas (se conservan)', p.kept_delivered] : null,
      p.own_person_rows ? ['Dependientes que además están en la base con su propio documento (no se cuentan dos veces)', p.own_person_rows] : null,
      p.product_column ? ['Productos distintos en la columna «' + p.product_column + '»', p.products] : null,
    ]);
    const skipped = p.skipped_count ? `<div class="gw-alert gw-alert--err" role="alert"><div><b>${n(p.skipped_count)} fila(s) no se cargan:</b><ul class="gw-list">${(p.skipped || []).slice(0, 30).map(s => `<li>Fila ${esc(s.row)}: ${esc(s.reason)}</li>`).join('')}</ul>${p.skipped_count > 30 ? '<p class="gw-hint">…y más. Corrige el archivo y vuelve a cargarlo.</p>' : ''}</div></div>` : '';
    const cards = (p.samples || []).length ? `<h3 class="gw-card__title">Así quedarían algunos titulares en «Editar persona»</h3><div class="gw-preview__cards">${p.samples.map(s => `<article class="gw-preview__card">
        <div><b>${esc(s.holder_name || s.holder)}</b> <span class="gw-hint">${esc(s.holder)}</span> ${s.registered ? '<span class="gw-badge gw-badge--ok">Registrado</span>' : '<span class="gw-badge gw-badge--warn">No registrado</span>'}</div>
        <div class="gw-preview__field"><span class="gw-label">Dependientes</span><input class="gw-input" type="text" readonly value="${esc(s.after)}"${s.before !== s.after ? '' : ''}>${s.before !== s.after ? `<span class="gw-hint">Antes: <span class="gw-preview__old">${esc(s.before)}</span></span>` : ''}</div>
        <div class="gw-deps">${(s.people || []).map(pp => `<div class="gw-deps__person"><b>${esc(pp.label)}</b>${pp.doc ? ' · ' + esc(pp.doc) : ''}${pp.own_person ? ' <span class="gw-badge gw-badge--info">También está en la base con su documento</span>' : ''}
          <div class="gw-hint">${(pp.rows || []).map(r => Object.keys(r.data || {}).map(k => `${esc(k)}: ${esc(r.data[k])}`).join(' · ')).join('<br>')}</div></div>`).join('')}</div></article>`).join('')}</div>` : '';
    return dialog('Revisa antes de cargar los dependientes', cols + impact + summary + skipped + cards, p.mode === 'append' ? 'Sí, agregar lo nuevo' : 'Sí, cargar (reemplazar)');
  }

  window.RosterPreview = { confirmLoad, confirmDependents };
})();
