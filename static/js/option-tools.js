/* Editor cómodo de opciones de lista desplegable (P7), compartido por Parámetros del evento y el diseñador de formularios.
   Se pone sobre el <textarea> que ya guardaba «una opción por línea» (sigue siendo la fuente de verdad: quien guarda lo lee igual).
     OptionTools.attach(textarea, { eventId, key })   agrega: vista de etiquetas (orden y borrado), ordenar A–Z, quitar repetidas y
                                                       «Usar los valores que ya están en la base de datos» / «Actualizar desde la base»
   Las funciones puras (list, dedupe, sortAZ, move, plan, result) se prueban en Node: tests/js/option_tools_check.js.
   PRIVACIDAD: el servidor (app/optionvalues.py) solo entrega valores de campos NO identificantes; aquí además se avisa que las opciones son públicas. */
(function () {
  const norm = (x) => String(x == null ? '' : x).normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
  const BLOCKED = ['id', 'first_name', 'last_name', 'email', 'phone', 'birth_date', 'digital_contact', 'certificate'];
  const list = (text) => String(text || '').split('\n').map((s) => s.trim()).filter(Boolean);
  const dedupe = (arr) => { const seen = new Set(); return arr.filter((o) => { const k = norm(o); if (seen.has(k)) return false; seen.add(k); return true; }); };
  const sortAZ = (arr) => [...arr].sort((a, b) => norm(a).localeCompare(norm(b), 'es') || a.localeCompare(b, 'es'));
  const move = (arr, i, d) => { const out = [...arr], j = i + d; if (j < 0 || j >= out.length) return out; [out[i], out[j]] = [out[j], out[i]]; return out; };

  // Filas del diálogo «traer de la base»: una por grupo de variantes. Primera vez: todo marcado. Al actualizar: lo que ya estaba queda marcado (con su mismo texto) y lo nuevo, sin marcar.
  function plan(groups, existing, fromDb) {
    const have = new Map(existing.map((o) => [norm(o), o]));
    return groups.map((g) => {
      const mine = have.get(norm(g.suggested));
      return { group: g, checked: !fromDb || !!mine, isNew: !!fromDb && !mine, chosen: mine && g.values.some((v) => v.value === mine) ? mine : g.suggested };
    });
  }
  // Resultado: lo elegido de la base (A–Z) y, al final, lo escrito a mano que la base no tiene.
  function result(rows, existing) {
    const known = new Set(rows.map((r) => norm(r.group.suggested)));
    const chosen = sortAZ(rows.filter((r) => r.checked).map((r) => r.chosen));
    return dedupe(chosen.concat(existing.filter((o) => !known.has(norm(o)))));
  }

  const api = { norm, list, dedupe, sortAZ, move, plan, result, BLOCKED };
  if (typeof module !== 'undefined') module.exports = api;
  if (typeof window === 'undefined') return;
  window.OptionTools = api;

  const el = (tag, props, ...kids) => { const e = document.createElement(tag); Object.assign(e, props || {}); kids.forEach((k) => e.append(k)); return e; };
  const btn = (text, onclick, title) => { const b = el('button', { type: 'button', textContent: text, title: title || '' }); b.style.cssText = 'font-size:0.74rem; padding:3px 8px; border:1px solid #ccc; background:#fafafa; border-radius:8px; cursor:pointer;'; b.className = 'gwe-mini-btn'; b.addEventListener('click', onclick); return b; };

  async function fetchValues(eventId, key, scope) {
    const r = await fetch(`/api/events/${eventId}/field-values?key=${encodeURIComponent(key)}&scope=${scope}`, { credentials: 'same-origin' });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || 'No se pudieron traer los valores');
    return d;
  }

  // Diálogo: devuelve la lista final o null. Los textos entran con textContent (nada de HTML).
  function importDialog(eventId, key, existing, fromDb) {
    return new Promise((resolve) => {
      const overlay = el('div'); overlay.style.cssText = 'position:fixed; inset:0; background:rgba(10,14,46,.45); z-index:9998; display:flex; align-items:center; justify-content:center; padding:12px;';
      const box = el('div'); box.style.cssText = 'background:#fff; border-radius:16px; padding:1.2rem; width:min(520px,100%); max-height:88vh; display:flex; flex-direction:column; gap:8px; font-family:var(--font-body,sans-serif); font-size:.9rem;';
      const head = el('div'); const body = el('div'); body.style.cssText = 'overflow:auto; border:1px solid #eee; border-radius:10px; padding:6px; min-height:80px;';
      const warn = el('div'); warn.style.cssText = 'background:#fff8e1; border:1px solid #f0ad4e; border-radius:10px; padding:8px; color:#7a5b00; font-size:.82rem;';
      const scopeBox = el('input', { type: 'checkbox' });
      const scopeLbl = el('label', {}, scopeBox, ' Incluir también otros eventos del mismo cliente'); scopeLbl.style.cssText = 'display:flex; gap:6px; font-size:.82rem;';
      const ok = btn('Usar estas opciones', () => {}), cancel = btn('Cancelar', () => close(null));
      ok.style.cssText += 'background:#0a0e2e; color:#fff; border-color:#0a0e2e; padding:6px 14px;';
      const foot = el('div', {}, cancel, ok); foot.style.cssText = 'display:flex; justify-content:flex-end; gap:8px;';
      box.append(head, scopeLbl, body, warn, foot); overlay.append(box); document.body.append(overlay);
      const close = (v) => { overlay.remove(); resolve(v); };
      let rows = [];
      const countChecked = () => rows.filter((r) => r.checked).length;
      const paintCount = () => { const n = result(rows, existing).length; warn.textContent = `Quedarán ${n} opciones. Estas opciones serán públicas: cualquier persona que abra el formulario las verá. Revisa que ninguna sea un dato personal.`; ok.disabled = !countChecked() && !existing.length; };
      async function load() {
        body.textContent = 'Buscando…';
        let d;
        try { d = await fetchValues(eventId, key, scopeBox.checked ? 'client' : 'event'); } catch (e) { body.textContent = e.message; ok.disabled = true; return; }
        rows = plan(d.groups, existing, fromDb);
        head.textContent = `${d.total} valores distintos en "${d.label}"` + (d.truncated ? `. Hay más de ${d.limit}: se muestran los ${d.limit} más frecuentes (revisa que este campo sirva como lista).` : '.') + (d.skipped ? ` ${d.skipped} valores muy largos se omitieron.` : '');
        body.textContent = '';
        if (!rows.length) body.textContent = 'No hay valores todavía.';
        rows.forEach((r) => {
          const cb = el('input', { type: 'checkbox', checked: r.checked });
          cb.addEventListener('change', () => { r.checked = cb.checked; paintCount(); });
          const line = el('label', {}, cb); line.style.cssText = 'display:flex; gap:6px; align-items:center; padding:3px 4px;';
          if (r.group.values.length > 1) {   // variantes («Bogota» / «Bogotá»): se elige cuál usar
            const sel = el('select'); r.group.values.forEach((v) => sel.append(el('option', { value: v.value, textContent: `${v.value} (${v.count})`, selected: v.value === r.chosen })));
            sel.addEventListener('change', () => { r.chosen = sel.value; paintCount(); });
            line.append(sel, el('span', { textContent: ' variantes juntas: elige cuál usar' }));
          } else line.append(el('span', { textContent: `${r.group.suggested} (${r.group.count})` }));
          if (r.isNew) line.append(el('b', { textContent: ' nuevo' }));
          body.append(line);
        });
        paintCount();
      }
      scopeBox.addEventListener('change', load);
      ok.addEventListener('click', () => close(result(rows, existing)));
      load();
    });
  }

  function attach(ta, opts) {
    if (!ta || ta.dataset.otDone) return;
    ta.dataset.otDone = '1';
    if (opts.fromDb) ta.dataset.fromDb = '1';
    const wrap = el('div'); wrap.style.cssText = 'display:grid; gap:4px; margin-top:4px;';
    const tags = el('div'); tags.style.cssText = 'display:none; flex-wrap:wrap; gap:4px; border:1px solid #ddd; border-radius:8px; padding:4px; background:#fff;';
    const bar = el('div'); bar.style.cssText = 'display:flex; gap:4px; flex-wrap:wrap;';
    ta.after(wrap);
    const get = () => list(ta.value);
    const set = (arr) => { ta.value = arr.join('\n'); ta.dispatchEvent(new Event('input', { bubbles: true })); ta.dispatchEvent(new Event('change', { bubbles: true })); paintTags(); };
    function paintTags() {
      tags.textContent = '';
      get().forEach((o, i) => {
        const chip = el('span', {}, el('span', { textContent: o + ' ' }));
        chip.style.cssText = 'display:inline-flex; align-items:center; gap:2px; background:#eef0f8; border-radius:12px; padding:2px 4px 2px 8px; font-size:.78rem;';
        const mini = (t, fn, title) => { const b = btn(t, fn, title); b.style.cssText = 'border:none; background:transparent; cursor:pointer; font-size:.78rem; padding:0 3px;'; b.className = 'gwe-chip-btn'; return b; };
        chip.append(mini('↑', () => set(move(get(), i, -1)), 'Subir'), mini('↓', () => set(move(get(), i, 1)), 'Bajar'), mini('✕', () => set(get().filter((_, k) => k !== i)), 'Quitar'));
        tags.append(chip);
      });
      const add = el('input', { type: 'text', placeholder: 'Agregar y Enter' }); add.style.cssText = 'border:none; outline:none; font-size:.8rem; min-width:110px;';
      add.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); const v = add.value.trim(); if (v) set(dedupe(get().concat(v))); } });
      tags.append(add);
    }
    const toggle = btn('Ver como etiquetas', () => {
      const show = tags.style.display === 'none';
      tags.style.display = show ? 'flex' : 'none'; ta.style.display = show ? 'none' : ''; toggle.textContent = show ? 'Ver como lista' : 'Ver como etiquetas'; if (show) paintTags();
    });
    bar.append(toggle, btn('Ordenar A–Z', () => set(sortAZ(get()))), btn('Quitar repetidas', () => set(dedupe(get())), 'Ignora espacios, mayúsculas y tildes'));
    const key = () => (typeof opts.key === 'function' ? opts.key() : opts.key);
    if (opts.eventId && key() && BLOCKED.includes(key())) {
      const note = el('div', { textContent: 'Este campo parece contener datos personales; por seguridad no se puede traer de la base' }); note.style.cssText = 'font-size:.74rem; color:#7a5b00;';
      bar.append(note);
    } else if (opts.eventId && key()) {
      const dbBtn = btn(ta.dataset.fromDb ? 'Actualizar desde la base' : 'Usar los valores que ya están en la base de datos', async () => {
        const res = await importDialog(opts.eventId, key(), get(), !!ta.dataset.fromDb);
        if (res) { ta.dataset.fromDb = '1'; if (opts.onImported) opts.onImported(); set(res); dbBtn.textContent = 'Actualizar desde la base'; }
      }, 'Trae los valores distintos de las personas; es una foto, no se actualiza sola');
      bar.append(dbBtn);
    }
    wrap.append(bar, tags);
    ta._otWrap = wrap;
    if (ta.style.display === 'none') wrap.style.display = 'none';
  }
  api.attach = attach;
})();
