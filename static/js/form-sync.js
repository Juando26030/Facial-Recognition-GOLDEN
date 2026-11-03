/* Ayudas del diseñador de formularios para los campos enlazados a Parámetros del evento (P6). Sin DOM, así se prueba en Node.
     FormSync.norm(texto)                  mismo criterio que las reglas del servidor (formlib.norm_value): espacios, mayúsculas y tildes
     FormSync.optionsOf(campo, camposEv)   opciones del campo (propias o las del campo del evento enlazado por `key`), o null si no tiene
     FormSync.findOption(opciones, valor)  la opción que coincide con el valor ignorando espacios/mayúsculas/tildes
     FormSync.plan(design, camposEv)       cambios que haría «Sincronizar con Parámetros» (no cambia nada)
     FormSync.apply(design, plan)          aplica esos cambios                                                              */
(function () {
  const norm = (x) => String(x == null ? '' : x).normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
  const CHOICE = ['select', 'radio', 'multiselect'];
  const same = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

  function optionsOf(field, eventFields) {
    if (!field) return null;
    if (Array.isArray(field.options) && field.options.length) return field.options;
    const ev = field.key && (eventFields || []).find((e) => e.key === field.key);
    return ev && ev.options && ev.options.length ? ev.options : null;
  }
  const findOption = (opts, value) => (opts || []).find((o) => norm(o) === norm(value));

  function plan(design, eventFields) {
    const out = [];
    Object.values(design.fields).forEach((f) => {
      const ev = f.key && (eventFields || []).find((e) => e.key === f.key);
      if (!ev) return;
      const p = { id: f.id, label: f.label || ev.label, changes: [] };
      let type = f.type;
      if ((type === 'text_short' || type === 'text_long') && ev.type === 'select' && (ev.options || []).length) { type = 'select'; p.type = 'select'; p.changes.push('pasa de texto a lista desplegable'); }
      if (CHOICE.includes(type) && (ev.options || []).length && !same(f.options || [], ev.options)) { p.options = [...ev.options]; p.changes.push(`opciones: ${(f.options || []).length} → ${ev.options.length}`); }
      if (p.changes.length) out.push(p);
    });
    return out;
  }

  function apply(design, changes) {
    changes.forEach((p) => {
      const f = design.fields[p.id];
      if (!f) return;
      if (p.type) { f.type = p.type; f.placeholder = ''; }
      if (p.options) f.options = [...p.options];
    });
  }

  const api = { norm, optionsOf, findOption, plan, apply };
  if (typeof window !== 'undefined') window.FormSync = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
