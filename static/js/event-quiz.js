/* «Configurar el evento por cuestionario» (26-nov-2026): primera pestaña de Parámetros del evento. Preguntas y reglas en app/setup_quiz.py.
   - Al responder, se cambian los MISMOS controles de las demás pestañas (como si la persona los tocara): esas secciones quedan «Sin guardar» y todo se guarda con «Guardar cambios».
   - Las preguntas sin responder muestran la respuesta que ya corresponde al evento cuando se puede reconocer («Así está hoy»).
   - Lo que falta hacer a mano (crear ítems, zonas, categorías, diseñar…) se marca en amarillo con «!» en la pestaña y en la sección, hasta que se haga.
   La lógica pura (visible, detect, plan) se prueba con Node: tests/js/event_quiz_check.js. Sin innerHTML con datos: todo con textContent. */
(function (root) {
  'use strict';

  /* ------------------------------------------------------------------ lógica pura */
  function visible(q, answers, byId, seen) {
    seen = seen || {};
    if (!q || seen[q.id]) return false;
    seen[q.id] = true;
    const when = q.when || {};
    return Object.keys(when).every((dep) => when[dep].indexOf(answers[dep]) >= 0 && visible(byId[dep], answers, byId, Object.assign({}, seen)));
  }
  // La opción que ya corresponde al estado actual: todas sus operaciones coinciden. Si coinciden varias (o ninguna), no se adivina.
  function detect(q, read) {
    const hits = (q.options || []).filter((o) => o.set && o.set.length && o.set.every((op) => read(op) === true));
    return hits.length === 1 ? hits[0].v : null;
  }
  // Lo que hay que cambiar para dejar la respuesta: las operaciones que todavía no coinciden (las de «estado» no cambian nada).
  function plan(q, value, read) {
    const o = (q.options || []).find((x) => x.v === value);
    if (!o) return [];
    return o.set.filter((op) => op.k !== 'state' && read(op) !== true);
  }
  function lanesText(current, n) {
    const parts = String(current || '').split(',').map((s) => s.trim()).filter(Boolean);
    const letters = 'ABCDEFGH';
    const out = parts.slice(0, n);
    for (let i = out.length; i < n; i++) out.push(letters[i]);
    return out.join(', ');
  }
  const core = { visible, detect, plan, lanesText };
  if (typeof module !== 'undefined' && module.exports) { module.exports = core; return; }

  /* ------------------------------------------------------------------ pantalla */
  const doc = root.document;
  const host = doc.getElementById('quizRoot');
  if (!host) return;
  const EID = root.EVENT_ID;
  const API = '/api/events/' + EID + '/setup-quiz';
  const ICONS = root.GW_ICONS || '';
  let data = null;               // respuesta del servidor
  let answers = {};              // respuestas en pantalla (guardadas + tocadas + reconocidas)
  let detected = {};             // las que el sistema reconoció del estado actual (no las escribió nadie)
  const results = {};            // por pregunta: qué pasó con cada operación la última vez

  const byId = () => { const m = {}; (data ? data.questions : []).forEach((q) => { m[q.id] = q; }); return m; };
  const el = (tag, cls, text) => { const e = doc.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const icon = (name) => { const s = doc.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('class', 'gw-icon gw-icon--sm'); s.setAttribute('aria-hidden', 'true'); const u = doc.createElementNS('http://www.w3.org/2000/svg', 'use'); u.setAttribute('href', ICONS + '#i-' + name); s.appendChild(u); return s; };

  function radioOf(op) { return Array.from(doc.getElementsByName(op.name)).find((r) => r.value === op.v) || null; }
  function read(op) {
    if (op.k === 'state') return data && data.flags ? data.flags[op.key] === op.v : null;
    if (op.k === 'radio') { const r = radioOf(op); return r ? r.checked : null; }
    const c = doc.getElementById(op.id);
    if (!c) return null;
    if (op.k === 'check') return c.checked === op.v;
    if (op.k === 'select') return Array.from(c.options || []).some((o) => o.value === op.v) ? c.value === op.v : null;
    if (op.k === 'value') return String(c.value || '').trim() === op.v;
    if (op.k === 'lanes') return String(c.value || '').split(',').map((s) => s.trim()).filter(Boolean).length === op.v;
    return null;
  }
  function fire(c) { c.dispatchEvent(new root.Event('input', { bubbles: true })); c.dispatchEvent(new root.Event('change', { bubbles: true })); }
  function write(op) {
    const c = op.k === 'radio' ? radioOf(op) : doc.getElementById(op.id);
    if (!c) return 'missing';
    if (c.disabled || c.closest('[inert]')) return 'disabled';
    if (op.k === 'check') c.checked = op.v;
    else if (op.k === 'radio') c.checked = true;
    else if (op.k === 'select' || op.k === 'value') c.value = op.v;
    else if (op.k === 'lanes') c.value = lanesText(c.value, op.v);
    fire(c);
    return 'ok';
  }

  function apply(q, value) {
    const ops = plan(q, value, read);
    const res = [];
    ops.forEach((op) => res.push({ label: op.label, st: write(op) }));
    const o = q.options.find((x) => x.v === value);
    (o ? o.set : []).forEach((op) => { if (op.k !== 'state' && !ops.includes(op)) res.push({ label: op.label, st: 'same' }); });
    results[q.id] = res;
    return res;
  }

  /* ---------------------------------------------------------------- dibujar el cuestionario */
  function render() {
    const m = byId();
    host.replaceChildren();
    data.sections.forEach((s) => {
      const qs = data.questions.filter((q) => q.section === s.id);
      if (!qs.length) return;
      const card = el('div', 'gw-card gw-stack gw-quiz__section');
      card.dataset.qzSection = s.id;
      card.appendChild(el('h3', 'gw-quiz__title', s.title));
      qs.forEach((q) => {
        const fs = el('fieldset', 'gw-fieldset gw-quiz__q');
        fs.dataset.qz = q.id;
        fs.hidden = !visible(q, answers, m);
        const lg = el('legend', 'gw-label', q.text);
        if (detected[q.id] && answers[q.id] === detected[q.id]) { lg.appendChild(doc.createTextNode(' ')); lg.appendChild(el('span', 'gw-badge gw-badge--info', 'Así está hoy')); }
        fs.appendChild(lg);
        if (q.help) fs.appendChild(el('p', 'gw-hint', q.help));
        q.options.forEach((o) => {
          const lab = el('label', 'gw-choice');
          const inp = el('input');
          inp.type = 'radio'; inp.name = 'qz_' + q.id; inp.value = o.v; inp.checked = answers[q.id] === o.v;
          lab.appendChild(inp);
          const tx = el('span', 'gw-choice__text', o.label);
          if (o.hint) tx.appendChild(el('span', null, o.hint));
          lab.appendChild(tx);
          fs.appendChild(lab);
        });
        fs.appendChild(outFor(q));
        card.appendChild(fs);
      });
      host.appendChild(card);
    });
    progress();
  }
  // Respuesta guardada que ya no coincide con cómo está la sección (alguien la cambió a mano o no se guardó): se avisa y se ofrece aplicarla otra vez.
  const mismatch = (q) => !!answers[q.id] && !results[q.id] && !detected[q.id] && plan(q, answers[q.id], read).some((op) => read(op) === false);
  function outFor(q) {
    const p = el('p', 'gw-hint gw-quiz__out');
    p.dataset.qzOut = q.id;
    const res = results[q.id];
    if (mismatch(q)) {
      p.classList.add('gw-quiz__bad');
      p.appendChild(doc.createTextNode('La configuración de hoy no coincide con esta respuesta. '));
      const b = el('button', 'gw-btn gw-btn--secondary gw-btn--sm', 'Aplicar esta respuesta');
      b.type = 'button'; b.dataset.qzReapply = q.id;
      p.appendChild(b);
      return p;
    }
    if (!res || !res.length) { p.hidden = true; return p; }
    const txt = { ok: 'cambiado, falta guardar', same: 'ya estaba así', disabled: 'no lo puedes cambiar tú (pídeselo a un administrador)', missing: 'no está en esta pantalla' };
    p.appendChild(doc.createTextNode('Esto configura: '));
    res.forEach((r, i) => {
      if (i) p.appendChild(doc.createTextNode(' · '));
      const b = el('span', r.st === 'ok' ? 'gw-quiz__chg' : (r.st === 'disabled' || r.st === 'missing' ? 'gw-quiz__bad' : null), r.label + ' (' + txt[r.st] + ')');
      p.appendChild(b);
    });
    return p;
  }
  function syncReapply() {
    const b = doc.getElementById('quizReapply');
    if (!b || !data) return;
    const m = byId();
    b.hidden = !data.questions.some((q) => visible(q, answers, m) && mismatch(q));
  }
  function progress() {
    syncReapply();
    const m = byId();
    const vis = data.questions.filter((q) => visible(q, answers, m));
    const done = vis.filter((q) => answers[q.id]).length;
    const pend = (data.actions || []).filter((a) => !a.done).length;
    const bar = doc.getElementById('quizProgress');
    if (bar) bar.textContent = done + ' de ' + vis.length + ' preguntas respondidas' + (data.saved ? '' : ' · sin guardar todavía');
    const sum = doc.querySelector('#tab_cuestionario .gw-tab__sum');
    if (sum) sum.textContent = (data.saved ? done + ' de ' + vis.length + ' respondidas' : 'Sin responder') + (pend ? ' · ' + pend + ' por hacer' : '');
  }

  /* ---------------------------------------------------------------- acciones pendientes */
  function paintActions() {
    doc.querySelectorAll('[data-qz-note]').forEach((n) => n.remove());
    doc.querySelectorAll('.gw-needs-action').forEach((n) => n.classList.remove('gw-needs-action'));
    const perTab = {};
    const pending = (data.actions || []).filter((a) => !a.done);
    const byTarget = {};
    pending.forEach((a) => { (byTarget[a.target] = byTarget[a.target] || []).push(a); });
    Object.keys(byTarget).forEach((tid) => {
      const t = doc.getElementById(tid);
      if (!t) return;
      t.classList.add('gw-needs-action');
      const note = el('div', 'gw-alert gw-alert--warn gw-needs-action__note');
      note.dataset.qzNote = '1';
      note.setAttribute('role', 'note');
      note.appendChild(icon('alert'));
      const body = el('div', 'gw-alert__body');
      body.appendChild(el('b', null, byTarget[tid].length > 1 ? 'Necesita ' + byTarget[tid].length + ' acciones por el cuestionario:' : 'Necesita acción por el cuestionario:'));
      const ul = el('ul', 'gw-needs-action__list');
      byTarget[tid].forEach((a) => {
        const li = el('li');
        li.appendChild(el('b', null, a.title + '. '));
        li.appendChild(doc.createTextNode(a.text + ' '));
        if (a.link) { const ln = el('a', null, 'Abrir'); ln.href = a.link; li.appendChild(ln); }
        ul.appendChild(li);
      });
      body.appendChild(ul);
      note.appendChild(body);
      const head = t.querySelector(':scope > .gw-item-head');          // después del título: el plegado de las secciones necesita el título primero
      if (head) head.after(note); else t.insertBefore(note, t.firstChild);
      const panel = t.closest('[role="tabpanel"]');
      const tabId = panel && panel.getAttribute('aria-labelledby');
      if (tabId) perTab[tabId] = (perTab[tabId] || 0) + byTarget[tid].length;
    });
    doc.querySelectorAll('[data-group-action]').forEach((f) => {
      const tab = f.closest('[role="tab"]');
      const n = tab ? perTab[tab.id] || 0 : 0;
      f.hidden = !n;
      const lbl = f.querySelector('[data-action-count]');
      if (lbl) lbl.textContent = n > 1 ? 'Requiere ' + n + ' acciones' : 'Requiere acción';
    });
    const qtab = doc.querySelector('#tab_cuestionario [data-group-action]');
    if (qtab) { qtab.hidden = !pending.length; const l = qtab.querySelector('[data-action-count]'); if (l) l.textContent = pending.length > 1 ? pending.length + ' acciones pendientes' : '1 acción pendiente'; }
    listActions();
    progress();
  }
  function listActions() {
    const box = doc.getElementById('quizActions');
    if (!box) return;
    box.replaceChildren();
    const acts = data.actions || [];
    if (!data.saved) { box.appendChild(el('p', 'gw-hint', 'Cuando guardes las respuestas, aquí verás lo que falta hacer a mano.')); return; }
    const pend = acts.filter((a) => !a.done), done = acts.filter((a) => a.done);
    if (!pend.length) {
      const ok = el('div', 'gw-alert gw-alert--ok'); ok.setAttribute('role', 'status'); ok.appendChild(icon('check'));
      ok.appendChild(el('div', 'gw-alert__body', acts.length ? 'No falta nada: todo lo que pidió el cuestionario ya está hecho.' : 'Con estas respuestas no hace falta ningún paso adicional.'));
      box.appendChild(ok);
    } else {
      const ul = el('ul', 'gw-quiz__todo');
      pend.forEach((a) => {
        const li = el('li', 'gw-quiz__todo-item');
        li.appendChild(icon('alert'));
        const tx = el('div', 'gw-quiz__todo-text');
        tx.appendChild(el('b', null, a.title));
        tx.appendChild(el('span', 'gw-hint', a.text));
        li.appendChild(tx);
        const go = el('button', 'gw-btn gw-btn--secondary gw-btn--sm', 'Ir a la sección');
        go.type = 'button'; go.dataset.qzGo = a.target;
        li.appendChild(go);
        ul.appendChild(li);
      });
      box.appendChild(ul);
    }
    if (done.length) {
      const d = el('details', 'gw-advanced');
      d.appendChild(el('summary', null, 'Ya hecho (' + done.length + ')'));
      const ul = el('ul', 'gw-quiz__done');
      done.forEach((a) => { const li = el('li'); li.appendChild(icon('check')); li.appendChild(doc.createTextNode(' ' + a.title)); ul.appendChild(li); });
      d.appendChild(ul);
      box.appendChild(d);
    }
  }
  function goTo(tid) {
    const t = doc.getElementById(tid);
    if (!t) return;
    const panel = t.closest('[role="tabpanel"]');
    const tab = panel && doc.getElementById(panel.getAttribute('aria-labelledby'));
    if (tab) tab.click();
    root.setTimeout(() => { t.setAttribute('tabindex', '-1'); t.scrollIntoView({ behavior: 'smooth', block: 'start' }); t.focus({ preventScroll: true }); }, 60);
  }

  /* ---------------------------------------------------------------- datos */
  function recognize() {
    detected = {};
    data.questions.forEach((q) => {
      if (answers[q.id]) return;
      const v = detect(q, read);
      if (v) { detected[q.id] = v; answers[q.id] = v; }
    });
  }
  async function load(first) {
    const r = await fetch(API, { headers: { Accept: 'application/json' } });
    if (!r.ok) throw new Error('No se pudo cargar el cuestionario');
    const d = await r.json();
    const panel = doc.getElementById('grp_cuestionario');
    // Se vuelve a dibujar solo al cargar o si la persona no lo está mirando (otra pestaña) y no hay respuestas sin guardar: así no salta mientras responde.
    if (first || (!dirty && panel && panel.hidden)) {
      data = d;
      answers = Object.assign({}, d.answers);
      recognize();
      render();
    } else {
      data.actions = d.actions; data.flags = d.flags; data.saved = d.saved;
    }
    paintActions();
  }
  let dirty = false;
  const refresh = () => { load(false).catch(() => { /* sin red: se queda lo último */ }); };
  let tmr = null;
  const later = (ms) => { root.clearTimeout(tmr); tmr = root.setTimeout(refresh, ms || 1200); };

  host.addEventListener('change', (e) => {
    const t = e.target;
    if (!t || t.type !== 'radio' || !t.name || t.name.indexOf('qz_') !== 0) return;
    const q = byId()[t.name.slice(3)];
    if (!q) return;
    answers[q.id] = t.value;
    delete detected[q.id];
    dirty = true;
    const res = apply(q, t.value);
    // Las preguntas que dependen de esta aparecen o se ocultan; la línea de «Esto configura» se actualiza.
    const m = byId();
    host.querySelectorAll('[data-qz]').forEach((fs) => { fs.hidden = !visible(m[fs.dataset.qz], answers, m); });
    const old = host.querySelector('[data-qz-out="' + q.id + '"]');
    if (old) old.replaceWith(outFor(q));
    const lg = host.querySelector('[data-qz="' + q.id + '"] legend .gw-badge');
    if (lg) lg.remove();
    progress();
    const n = res.filter((x) => x.st === 'ok').length;
    const st = doc.getElementById('quizStatus');
    if (st) st.textContent = n ? (n > 1 ? 'Se cambiaron ' + n + ' ajustes' : 'Se cambió 1 ajuste') + ' en otras pestañas. Revisa y pulsa «Guardar cambios».' : '';
  });
  (doc.getElementById('grp_cuestionario') || host).addEventListener('click', (e) => {
    const b = e.target.closest && e.target.closest('[data-qz-go]');
    if (b) { e.preventDefault(); goTo(b.dataset.qzGo); return; }
    const r = e.target.closest && e.target.closest('[data-qz-reapply], #quizReapply');
    if (!r) return;
    e.preventDefault();
    const m = byId();
    const ids = r.id === 'quizReapply' ? data.questions.filter((q) => visible(q, answers, m) && mismatch(q)).map((q) => q.id) : [r.dataset.qzReapply];
    let n = 0;
    ids.forEach((id) => { if (m[id]) n += apply(m[id], answers[id]).filter((x) => x.st === 'ok').length; });
    ids.forEach((id) => { const old = host.querySelector('[data-qz-out="' + id + '"]'); if (old && m[id]) old.replaceWith(outFor(m[id])); });
    syncReapply();
    const st = doc.getElementById('quizStatus');
    if (st) st.textContent = n ? (n > 1 ? 'Se cambiaron ' + n + ' ajustes' : 'Se cambió 1 ajuste') + ' en otras pestañas. Revisa y pulsa «Guardar cambios».' : '';
  });
  doc.addEventListener('click', (e) => {
    const b = e.target.closest && e.target.closest('button');
    if (b && !b.closest('#grp_cuestionario') && !b.closest('[role="tab"]') && b.id !== 'paramsSaveBtn') later(1500);          // agregar una zona, un ítem, subir el logo…: se vuelve a mirar lo que falta
  });
  doc.addEventListener('gw:tabshow', () => later(200));
  doc.addEventListener('gw:paramsstate', (e) => { if (e.detail && e.detail.state === 'saved') { dirty = false; later(300); } });
  root.addEventListener('focus', () => later(300));

  const clearBtn = doc.getElementById('quizClear');
  if (clearBtn) clearBtn.addEventListener('click', async () => {
    const ok = await root.showConfirm('¿Borrar las respuestas del cuestionario? La configuración del evento no cambia; solo se quitan las respuestas y las marcas de «Requiere acción».', { confirmLabel: 'Sí, borrar' });
    if (!ok) return;
    const r = await fetch(API, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ clear: true }) });
    if (!r.ok) { root.showToast('No se pudieron borrar las respuestas', 'error'); return; }
    Object.keys(results).forEach((k) => delete results[k]);
    data = await r.json(); answers = Object.assign({}, data.answers); dirty = false;
    recognize(); render(); paintActions();
    root.GWParams.markClean('quiz');
    root.showToast('Respuestas borradas', 'success');
  });

  root.GWParams.register({ key: 'quiz', label: 'Cuestionario del evento', order: 1, save: async () => {
    const m = byId();
    const body = {};
    Object.keys(answers).forEach((k) => { if (m[k] && visible(m[k], answers, m)) body[k] = answers[k]; });          // también las reconocidas («Así está hoy»): describen el evento tal como queda
    const r = await fetch(API, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answers: body }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || 'No se guardaron las respuestas');
    data.actions = d.actions; data.flags = d.flags; data.saved = true; data.updated_at = d.updated_at;
    paintActions();
  } });

  // «Una escarapela distinta por categoría» (Escarapelas y certificados): el mismo interruptor del diseñador de escarapelas.
  const bpc = doc.getElementById('badgePerCategory');
  if (bpc) root.GWParams.register({ key: 'badgecat', label: 'Una escarapela por categoría', order: 81, save: async () => {
    const r = await fetch('/api/events/' + EID + '/badge-mode', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ per_category: bpc.checked }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || 'No se pudo guardar');
  } });

  // Los valores de Turnos y otras secciones llegan un momento después: se reconoce el estado cuando ya están.
  root.setTimeout(() => load(true).catch(() => {
    host.replaceChildren(el('p', 'gw-alert gw-alert--err', 'No se pudo cargar el cuestionario. Recarga la página.'));
  }), 700);
})(typeof window !== 'undefined' ? window : globalThis);
