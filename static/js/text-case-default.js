/* «Texto al escribir» GENERAL del evento con el formulario de persona PREDETERMINADO (sin formulario a la medida). El servidor entrega `window.TEXT_CASE_DEFAULT = {campo: modo}` solo si el evento
   lo configuró (Parámetros › Formulario de persona › «Texto al escribir»); aquí se convierte MIENTRAS se escribe en «Registrar nuevo» y en el modal de Editar. El servidor repite la conversión al
   guardar (app/personform.py::apply_case), así que lo que llegue por lector, foto o sin red también queda igual. Con un formulario a la medida lo hace person-form.js y este archivo no hace nada. */
(function (root) {
  const rules = root.TEXT_CASE_DEFAULT;
  if (!rules || root.PERSON_FORM) return;
  const CASE = { upper: (s) => s.toUpperCase(), lower: (s) => s.toLowerCase(), title: (s) => s.replace(/[\p{L}\p{N}_]+/gu, (w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()) };
  const NEVER = ['id', 'phone', 'email', 'birth_date'];
  const convert = (c) => {
    const mode = rules[c.name];
    if (!mode || !CASE[mode] || NEVER.includes(c.name)) return;
    if (c.tagName !== 'TEXTAREA' && !(c.tagName === 'INPUT' && ['text', 'search', ''].includes(c.type))) return;
    const v = c.value, nv = CASE[mode](v);
    if (nv === v) return;
    const a = c.selectionStart, b = c.selectionEnd;
    c.value = nv;
    try { if (a != null) c.setSelectionRange(a, b); } catch (e) { /* sin selección */ }
  };
  const inForm = (n) => !!(n && n.closest && n.closest('#dynamicFieldsContainer, #editModalForm'));
  root.document.addEventListener('input', (e) => { if (!e.isComposing && e.target && e.target.name && inForm(e.target)) convert(e.target); });
  root.document.addEventListener('focusout', (e) => { if (e.target && e.target.name && inForm(e.target)) convert(e.target); });
})(window);
