/* Dibujo de un Formulario Web a partir de su diseño (Sprint 5) — compartido por la página pública (/f/...) y la vista
   previa del editor, así "lo que ves" es lo que la gente verá. La validación DEFINITIVA es la del servidor
   (app/formlib.py); aquí solo se muestra/oculta en vivo (mismas reglas de condiciones) y se avisa rápido de lo básico.

     const form = FormRender.render(contenedor, design, { assetUrl, prefill, readonly, onFirstInput, onChange });
     form.collect()      -> { values: {campo: valor}, files: {campo: File} }   (solo campos visibles)
     form.validate()     -> true/false, y pinta los errores debajo de cada campo
     form.setErrors({campo: mensaje})   (los que devuelve el servidor)
     form.setQuote({amount, applied})   actualiza el «Total a pagar» del campo Pago y el texto del botón (lo llama la página pública
                                        con lo que responde /quote; el precio lo calcula SIEMPRE el servidor)                    */
(function () {
  const esc = (t) => String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
  const norm = (x) => String(x == null ? '' : x).trim().toLowerCase();
  const asList = (v) => (Array.isArray(v) ? v.map(String) : (v === '' || v == null ? [] : [String(v)]));
  const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;
  const cop = (n) => '$' + Number(n || 0).toLocaleString('es-CO', { maximumFractionDigits: 0 }) + ' COP';

  function conditionMet(cond, values) {
    if (!cond) return true;
    const cur = values[cond.field];
    const have = asList(cur);
    const op = cond.op || 'equals';
    if (op === 'filled') return have.length > 0 && cur !== false;
    if (op === 'equals') return have.some((h) => norm(h) === norm(cond.value));
    if (op === 'not_equals') return !have.some((h) => norm(h) === norm(cond.value));
    if (op === 'contains') return have.some((h) => norm(h).includes(norm(cond.value)));
    if (op === 'in') { const w = asList(cond.value).map(norm); return have.some((h) => w.includes(norm(h))); }
    return false;
  }

  function render(container, design, opts) {
    opts = opts || {};
    const theme = design.theme || {};
    const assetUrl = opts.assetUrl || ((p) => p);
    const readonly = new Set(opts.readonly || []);
    const prefill = opts.prefill || {};
    let cur = 'COP', rates = null, lastQuote = null;   // moneda en que se MUESTRA el precio; el cobro es siempre en COP
    try { const c = localStorage.getItem('gw_cur'); if (['COP', 'USD', 'EUR'].includes(c)) cur = c; } catch (e) { /* sin almacenamiento: COP */ }
    container.innerHTML = '';
    container.style.fontFamily = `'${theme.font || 'Montserrat'}', sans-serif`;
    container.style.color = theme.text_color || '#0A0E2E';

    const card = document.createElement('div');
    card.style.cssText = `background:${theme.card_color || '#fff'}; border-radius:20px; padding:28px 30px; box-shadow:0 12px 40px rgba(0,0,0,.12); max-width:760px; margin:0 auto; box-sizing:border-box;`;
    container.appendChild(card);
    if (theme.logo) card.insertAdjacentHTML('beforeend', `<div style="text-align:center; margin-bottom:10px;"><img src="${esc(assetUrl(theme.logo))}" alt="" style="max-height:80px; max-width:60%;"></div>`);
    if (theme.title) card.insertAdjacentHTML('beforeend', `<h2 style="margin:0 0 4px; text-align:center; font-size:1.7rem;">${esc(theme.title)}</h2>`);
    if (theme.subtitle) card.insertAdjacentHTML('beforeend', `<p style="margin:0 0 18px; text-align:center; opacity:.75;">${esc(theme.subtitle)}</p>`);

    const style = document.createElement('style');
    const accent = theme.accent || '#D4AF37';
    style.textContent = `
      .fr-row { display:flex; gap:14px; margin-bottom:14px; flex-wrap:wrap; }
      .fr-item { flex:1 1 200px; min-width:0; }
      .fr-item label.fr-l { display:block; font-size:.82rem; font-weight:700; margin-bottom:4px; }
      .fr-item .fr-help { font-size:.74rem; opacity:.65; margin-top:3px; }
      .fr-item input[type=text], .fr-item input[type=email], .fr-item input[type=tel], .fr-item input[type=number], .fr-item input[type=date], .fr-item select, .fr-item textarea {
        width:100%; box-sizing:border-box; padding:10px 12px; border:1px solid #c9ccd6; border-radius:10px; font:inherit; background:#fff; color:#111; }
      .fr-item input:focus, .fr-item select:focus, .fr-item textarea:focus { outline:2px solid ${accent}; border-color:${accent}; }
      .fr-item .fr-ro { background:#eef0f4 !important; color:#555 !important; }
      .fr-opts label { display:flex; gap:8px; align-items:center; font-weight:400; margin:4px 0; cursor:pointer; }
      .fr-err { color:#c0392b; font-size:.76rem; margin-top:3px; } .fr-item.has-err input, .fr-item.has-err select, .fr-item.has-err textarea { border-color:#c0392b; }
      .fr-btn { width:100%; padding:13px; border:none; border-radius:26px; background:${accent}; color:#111; font:inherit; font-weight:800; font-size:1rem; cursor:pointer; margin-top:6px; }
      .fr-btn:disabled { opacity:.6; cursor:default; }
      .fr-pay { border:2px dashed ${accent}; border-radius:14px; padding:14px 16px; background:rgba(0,0,0,.03); }
      .fr-pay .fr-total { font-size:1.5rem; font-weight:800; } .fr-pay ul { margin:6px 0 0; padding-left:18px; font-size:.8rem; opacity:.8; }
      .fr-svc { margin-top:6px; padding:7px 10px; border-radius:10px; background:#fff3cd; color:#664d03; font-size:.78rem; }
      .fr-comp-group { border:1px solid rgba(0,0,0,.14); border-radius:12px; padding:10px 12px; margin-top:8px; background:rgba(0,0,0,.025); }
      .fr-comp-title { font-size:.8rem; font-weight:800; margin-bottom:6px; } .fr-comp-group input { margin-bottom:6px; }
      .fr-chip { border:1px solid ${accent}; background:#fff; color:#111; border-radius:14px; padding:2px 11px; font:inherit; font-size:.75rem; font-weight:700; cursor:pointer; margin-right:4px; }
      .fr-chip.on { background:${accent}; } .fr-charge { font-size:.8rem; opacity:.85; }
      .fr-safe { margin-top:10px; padding-top:8px; border-top:1px solid rgba(0,0,0,.1); font-size:.72rem; line-height:1.4; opacity:.85; } .fr-safe [data-fxnote] { display:block; opacity:.7; margin-top:3px; }`;
    card.appendChild(style);

    const form = document.createElement('form');
    form.noValidate = true;
    card.appendChild(form);
    const els = {};   // fid -> {wrap, input(s)}

    (design.rows || []).forEach((row) => {
      const r = document.createElement('div');
      r.className = 'fr-row';
      const justify = { left: 'flex-start', center: 'center', right: 'flex-end' }[row.align] || 'flex-start';
      r.style.justifyContent = justify;
      (row.items || []).forEach((fid) => {
        const f = design.fields[fid];
        if (!f) return;
        const wrap = document.createElement('div');
        wrap.className = 'fr-item'; wrap.dataset.fid = fid;
        if (row.items.length === 1 && row.align !== 'left') wrap.style.cssText = 'flex:0 1 60%;';
        wrap.innerHTML = fieldHtml(f, prefill[fid], readonly.has(fid), assetUrl);
        r.appendChild(wrap);
        els[fid] = { wrap, f };
      });
      form.appendChild(r);
    });
    const btn = document.createElement('button');
    btn.type = 'submit'; btn.className = 'fr-btn'; btn.textContent = theme.button_text || 'Enviar';
    if (opts.previewOnly) btn.type = 'button';
    form.appendChild(btn);

    let started = false;
    form.addEventListener('input', (e) => { syncComp(e.target); if (!started) { started = true; if (opts.onFirstInput) opts.onFirstInput(); } applyConditions(); if (opts.onChange) opts.onChange(); });
    form.addEventListener('change', (e) => {
      if (e.target && e.target.dataset && e.target.dataset.compCount) renderGroups(design.fields[e.target.dataset.compCount]);
      applyConditions(); if (opts.onChange) opts.onChange();
    });

    function fieldHtml(f, pre, ro, assetUrl) {
      const badgeNote = opts.badgeEmailField && opts.badgeEmailField === f.id ? ' <span class="fr-badge-note" style="font-weight:400; opacity:.75;">(a este correo se le enviará su escarapela virtual)</span>' : '';
      const label = f.label ? `<label class="fr-l">${esc(f.label)}${f.required ? ' <span style="color:#c0392b">*</span>' : ''}${badgeNote}</label>` : '';
      const help = f.help ? `<div class="fr-help">${esc(f.help)}</div>` : '';
      const val = pre == null ? '' : pre;
      const roAttr = ro ? 'readonly class="fr-ro" tabindex="-1"' : '';
      const name = `name="${esc(f.id)}"`;
      let control = '';
      switch (f.type) {
        case 'heading': return `<h3 style="margin:8px 0 2px;">${esc(f.content)}</h3>`;
        case 'paragraph': return `<p style="margin:0; white-space:pre-wrap; opacity:.85;">${esc(f.content)}</p>`;
        case 'payment': { const varies = f.pay && (f.pay.mode === 'rules' || (f.pay.discounts || []).length);
          return `<div class="fr-pay"><div style="font-size:.82rem;font-weight:700;">💳 ${esc(f.label || 'Pago')}${f.pay && f.pay.description ? ' — ' + esc(f.pay.description) : ''}</div><div class="fr-cur" data-curbar style="margin:8px 0 2px;"><span style="font-size:.72rem;opacity:.7;">Ver el precio en: </span>${['COP', 'USD', 'EUR'].map((c) => `<button type="button" class="fr-chip" data-cur="${c}" ${c === 'COP' ? '' : 'hidden'}>${c}</button>`).join('')}</div><div class="fr-total" data-total translate="no">Calculando…</div><div class="fr-charge" data-charge translate="no"></div>${opts.previewOnly && varies ? '<div class="fr-help">El valor final cambia según las respuestas y descuentos configurados.</div>' : ''}<div class="fr-svc" data-svc hidden></div><ul data-applied></ul><div class="fr-safe">🔒 <b>Pago seguro procesado por Wompi.</b> Golden no ve ni guarda los datos de tu tarjeta. El dinero ingresa a Golden en <b>pesos colombianos (COP)</b>. Si eliges USD o EUR es solo un valor de referencia con la tasa del día: tu tarjeta se cobra en COP y tu banco hace la conversión con su propia tasa (puede cobrarte una comisión).<span data-fxnote></span></div></div>`; }
        case 'companions': {
          const lo = f.min || 0;
          const opts = Array.from({ length: f.max - lo + 1 }, (_, i) => lo + i).map((n) => `<option value="${n}">${n === 0 ? 'Ninguno (voy solo/a)' : n === 1 ? '1 acompañante' : n + ' acompañantes'}</option>`).join('');
          return `<label class="fr-l">${esc(f.label)}</label><select data-comp-count="${esc(f.id)}">${opts}</select><div data-comp-list="${esc(f.id)}"></div>${help}<div class="fr-err"></div>`;
        }
        case 'image': return f.src ? `<img src="${esc(assetUrl(f.src))}" alt="" style="max-width:100%; border-radius:12px; display:block; margin:0 auto;">` : '';
        case 'text_long': control = `<textarea ${name} rows="4" placeholder="${esc(f.placeholder)}" ${roAttr}>${esc(val)}</textarea>`; break;
        case 'select': control = `<select ${name} ${ro ? 'disabled class="fr-ro"' : ''}><option value="">Selecciona…</option>${(f.options || []).map((o) => `<option ${String(val) === o ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>${ro ? `<input type="hidden" ${name} value="${esc(val)}">` : ''}`; break;
        case 'radio': control = `<div class="fr-opts">${(f.options || []).map((o) => `<label><input type="radio" ${name} value="${esc(o)}" ${String(val) === o ? 'checked' : ''} ${ro ? 'disabled' : ''}> ${esc(o)}</label>`).join('')}</div>`; break;
        case 'multiselect': { const sel = asList(val); control = `<div class="fr-opts">${(f.options || []).map((o) => `<label><input type="checkbox" ${name} value="${esc(o)}" ${sel.includes(o) ? 'checked' : ''} ${ro ? 'disabled' : ''}> ${esc(o)}</label>`).join('')}</div>`; break; }
        case 'checkbox': return `<div class="fr-opts"><label><input type="checkbox" ${name} value="true" ${val === true || String(val) === 'true' ? 'checked' : ''} ${ro ? 'disabled' : ''}> ${esc(f.label)}${f.required ? ' <span style="color:#c0392b">*</span>' : ''}</label></div>${help}<div class="fr-err"></div>`;
        case 'file': control = `<input type="file" ${name} accept="${(f.accept || []).map((a) => '.' + a).join(',')}" style="width:100%;"><div class="fr-help">Formatos: ${esc((f.accept || []).join(', '))} · máximo ${f.max_mb || 10} MB</div>`; break;
        default: { const type = { email: 'email', phone: 'tel', number: 'number', date: 'date' }[f.type] || 'text'; control = `<input type="${type}" ${name} value="${esc(val)}" placeholder="${esc(f.placeholder)}" autocomplete="off" ${type === 'number' ? 'step="any"' : ''} ${roAttr}>`; }
      }
      return `${label}${control}${help}<div class="fr-err"></div>`;
    }

    // ---- Acompañantes: un mini-formulario por acompañante; lo escrito se conserva si cambia la cantidad
    const compData = {};
    const compCount = (f) => { const sel = form.querySelector(`[data-comp-count="${f.id}"]`); return sel ? Number(sel.value) || 0 : 0; };
    const compList = (f) => { const n = compCount(f); const d = compData[f.id] || []; return Array.from({ length: n }, (_, i) => ({ ...(d[i] || {}) })); };
    function renderGroups(f) {
      const host = form.querySelector(`[data-comp-list="${f.id}"]`);
      const n = compCount(f);
      const d = (compData[f.id] = compData[f.id] || []);
      host.innerHTML = Array.from({ length: n }, (_, i) => `<div class="fr-comp-group"><div class="fr-comp-title">Acompañante ${i + 1}</div>${(f.person_fields || []).map((pf) => {
        const type = { email: 'email', phone: 'tel', number: 'number' }[pf.type] || 'text';
        return `<label class="fr-l" style="font-weight:600;">${esc(pf.label)}${pf.required ? ' <span style="color:#c0392b">*</span>' : ''}</label><input type="${type}" data-comp="${esc(f.id)}" data-i="${i}" data-sid="${esc(pf.id)}" value="${esc((d[i] || {})[pf.id] || '')}" autocomplete="off" ${type === 'number' ? 'step="any"' : ''}>`;
      }).join('')}</div>`).join('');
    }
    function syncComp(target) {
      if (!target || !target.dataset || target.dataset.comp === undefined) return;
      const d = (compData[target.dataset.comp] = compData[target.dataset.comp] || []);
      const i = Number(target.dataset.i);
      d[i] = { ...(d[i] || {}), [target.dataset.sid]: target.value };
    }
    function checkComp(f, list) {
      for (let i = 0; i < list.length; i++) {
        for (const pf of f.person_fields || []) {
          const v = String(list[i][pf.id] || '').trim();
          const who = `Acompañante ${i + 1}: «${pf.label}»`;
          if (!v) { if (pf.required) return `${who} es obligatorio`; continue; }
          if (pf.type === 'email' && !EMAIL.test(v)) return `${who}: escribe un correo con formato válido`;
          if (pf.type === 'number' && isNaN(Number(v.replace(',', '.')))) return `${who}: debe ser un número`;
        }
      }
      return '';
    }

    function rawValues() {
      const out = {};
      Object.values(els).forEach(({ f, wrap }) => {
        if (f.type === 'companions') { out[f.id] = compList(f); return; }
        if (!['text_short', 'text_long', 'email', 'phone', 'number', 'date', 'select', 'radio', 'multiselect', 'checkbox', 'file'].includes(f.type)) return;
        const inputs = Array.from(wrap.querySelectorAll(`[name="${f.id}"]`));
        if (f.type === 'multiselect') out[f.id] = inputs.filter((i) => i.checked).map((i) => i.value);
        else if (f.type === 'checkbox') out[f.id] = inputs.some((i) => i.checked) ? 'true' : 'false';
        else if (f.type === 'radio') { const c = inputs.find((i) => i.checked); out[f.id] = c ? c.value : ''; }
        else if (f.type === 'file') out[f.id] = inputs[0] && inputs[0].files && inputs[0].files.length ? '__file__' : '';
        else out[f.id] = inputs.length ? inputs[inputs.length - 1].value : '';   // select solo lectura: el input oculto va después
      });
      return out;
    }

    function visibleSet() {
      const values = rawValues();
      const memo = {};
      const vis = (fid) => {
        if (fid in memo) return memo[fid];
        const cond = design.fields[fid].show_if;
        memo[fid] = !cond || (design.fields[cond.field] && vis(cond.field) && conditionMet(cond, values));
        return memo[fid];
      };
      return new Set(Object.keys(els).filter(vis));
    }

    function applyConditions() {
      const vis = visibleSet();
      Object.entries(els).forEach(([fid, { wrap }]) => { wrap.style.display = vis.has(fid) ? '' : 'none'; });
      return vis;
    }
    Object.values(els).forEach(({ f }) => { if (f.type === 'companions') renderGroups(f); });
    applyConditions();

    function setErrors(errors) {
      Object.entries(els).forEach(([fid, { wrap }]) => {
        const msg = errors && errors[fid];
        wrap.classList.toggle('has-err', !!msg);
        const box = wrap.querySelector('.fr-err');
        if (box) box.textContent = msg || '';
      });
      const first = errors && Object.keys(errors)[0];
      if (first && els[first]) els[first].wrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    function collect() {
      const vis = visibleSet();
      const values = {}, files = {};
      const raw = rawValues();
      Object.keys(els).forEach((fid) => {
        if (!vis.has(fid) || !(fid in raw)) return;
        if (els[fid].f.type === 'file') {
          const input = els[fid].wrap.querySelector('input[type=file]');
          if (input && input.files.length) files[fid] = input.files[0];
        } else values[fid] = raw[fid];
      });
      return { values, files };
    }

    function validate() {
      const vis = visibleSet();
      const raw = rawValues();
      const errors = {};
      Object.entries(els).forEach(([fid, { f }]) => {
        if (!vis.has(fid) || !(fid in raw)) return;
        if (f.type === 'companions') { const msg = checkComp(f, raw[fid]); if (msg) errors[fid] = msg; return; }
        const v = raw[fid];
        const empty = f.type === 'multiselect' ? v.length === 0 : (f.type === 'checkbox' ? v !== 'true' : v === '');
        if (f.required && empty) errors[fid] = f.type === 'checkbox' ? 'Debes marcar esta casilla' : (f.type === 'file' ? 'Adjunta el archivo' : 'Este campo es obligatorio');
        else if (!empty && f.type === 'email' && !EMAIL.test(v)) errors[fid] = 'Escribe un correo con formato válido';
        else if (!empty && f.type === 'number' && isNaN(Number(String(v).replace(',', '.')))) errors[fid] = 'Debe ser un número';
        else if (f.type === 'file' && !empty) {
          const file = els[fid].wrap.querySelector('input[type=file]').files[0];
          const ext = (file.name.split('.').pop() || '').toLowerCase();
          if ((f.accept || []).length && !f.accept.includes(ext)) errors[fid] = `Formato no permitido (.${ext})`;
          else if (file.size > (f.max_mb || 10) * 1048576) errors[fid] = `El archivo pesa más de ${f.max_mb || 10} MB`;
        }
      });
      setErrors(errors);
      return Object.keys(errors).length === 0;
    }

    const money = (v, c) => new Intl.NumberFormat(navigator.language || 'es-CO', { style: 'currency', currency: c, maximumFractionDigits: 2 }).format(v);
    function paintPay() {
      const q = lastQuote, pays = form.querySelectorAll('.fr-pay');
      const usable = rates && rates.rates && rates.rates.USD && rates.rates.EUR;
      if (!usable && cur !== 'COP') cur = 'COP';
      pays.forEach((box) => {
        box.querySelectorAll('[data-cur]').forEach((b) => { b.hidden = b.dataset.cur !== 'COP' && !usable; b.classList.toggle('on', b.dataset.cur === cur); });
        const total = box.querySelector('[data-total]'), charge = box.querySelector('[data-charge]');
        if (!q || q.has_payment === false) { total.textContent = q ? '' : 'Calculando…'; charge.textContent = ''; }
        else if (!(q.amount > 0)) { total.textContent = 'Sin costo'; charge.textContent = ''; }
        else if (cur === 'COP') { total.textContent = cop(q.amount); charge.textContent = ''; }
        else {
          total.textContent = '≈ ' + money(q.amount * rates.rates[cur], cur);
          charge.textContent = `Se te cobrará ${cop(q.amount)} (pesos colombianos). Referencia: 1 ${cur} ≈ ${Math.round(1 / rates.rates[cur]).toLocaleString('es-CO')} COP.`;
        }
        box.querySelector('[data-applied]').innerHTML = ((q && q.applied) || []).map((a) => `<li>${esc(a.label)}: ${esc(a.effect)}</li>`).join('');
        box.querySelector('[data-fxnote]').textContent = usable ? `Tasas de referencia: exchangerate-api.com${rates.as_of ? ' · ' + rates.as_of : ''}.` : '';
      });
    }
    form.addEventListener('click', (e) => {
      const b = e.target.closest && e.target.closest('[data-cur]');
      if (!b) return;
      cur = b.dataset.cur;
      try { localStorage.setItem('gw_cur', cur); } catch (err) { /* opcional */ }
      paintPay();
    });

    function setQuote(q) {
      lastQuote = q;
      paintPay();
      form.querySelectorAll('[data-svc]').forEach((el) => {   // Wompi reporta una incidencia en su página de estado
        el.hidden = !(q && q.service);
        el.textContent = q && q.service ? `⚠️ Wompi está reportando problemas en su servicio (${q.service.description || 'incidencia'}). Tu pago podría fallar; si pasa, intenta de nuevo más tarde. No se te cobra si el pago no se aprueba.` : '';
      });
      const pays = form.querySelectorAll('.fr-pay');
      const paying = pays.length && pays[0].closest('.fr-item').style.display !== 'none' && q && q.amount > 0;
      btn.textContent = paying ? `Continuar al pago · ${cop(q.amount)}` : (theme.button_text || 'Enviar');   // el botón siempre dice el cobro real: COP
    }
    function setRates(r) { rates = r; paintPay(); }
    if (opts.previewOnly) { const pf = Object.values(design.fields).find((x) => x.type === 'payment'); if (pf) lastQuote = { has_payment: true, amount: (pf.pay && pf.pay.amount) || 0, applied: [] }; }
    paintPay();

    return { collect, validate, setErrors, setQuote, setRates, form, button: btn, applyConditions, hasPayment: Object.values(els).some(({ f }) => f.type === 'payment') };
  }

  if (typeof window !== 'undefined') window.FormRender = { render, conditionMet };
  if (typeof module !== 'undefined') module.exports = { conditionMet };
})();
