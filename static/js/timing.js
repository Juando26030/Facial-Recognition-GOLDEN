/* Cronómetro del registro (Fase 1A, PR1): mide cuánto tarda el digitador en registrar a una persona, desde la PRIMERA TECLA en el buscador (o la apertura del formulario de alta) hasta el momento en
   que el quiosco manda el registro. El valor viaja con la petición (`took_ms`, `ui_flow`); lo cuenta el servidor (app/regtime.py lo acota a 0..600000 ms) y lo agrega en el reporte del evento.
   Sin red, el valor se guarda junto al registro en la cola/bandeja del dispositivo y se envía al sincronizar. NO mide la respuesta del servidor (no se puede mandar dentro de la misma petición).
   Nunca guarda cédulas ni nombres: solo un instante y una etiqueta. Se carga antes de directory.js/app.js; si falta, todo sigue funcionando sin medir. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else { root.GoldenTiming = api; root.RegTimer = api.create(); }
})(typeof self !== 'undefined' ? self : this, function () {
  const MAX_MS = 600000;                       // igual que el tope del servidor: más que esto es una pestaña olvidada

  function create(deps) {
    const d = Object.assign({ now: () => Date.now(), flow: () => ((typeof window !== 'undefined' && window.UI_FLOW) || 'v0') }, deps || {});
    const t = { startedAt: null };
    /* Empieza a contar si no estaba contando (la primera tecla manda; las siguientes no reinician). */
    t.start = () => { if (t.startedAt === null) t.startedAt = d.now(); };
    /* Descarta la medición en curso (el digitador borró lo escrito, o cerró el formulario sin registrar). */
    t.cancel = () => { t.startedAt = null; };
    /* Lo que se manda con el registro: { took_ms, ui_flow } o null si no se estaba midiendo (registro sin teclear, p. ej. desde la lista de recientes) o si pasó demasiado tiempo. NO reinicia: se llama
       `done()` cuando el servidor (o la cola sin red) aceptó el registro, así un reintento o el aviso de DUPLICADO siguen contando desde la misma primera tecla. */
    t.payload = () => {
      if (t.startedAt === null) return null;
      const ms = Math.round(d.now() - t.startedAt);
      if (!(ms >= 0) || ms > MAX_MS) { t.startedAt = null; return null; }
      return { took_ms: ms, ui_flow: String(d.flow()) };
    };
    /* El registro quedó hecho: se cierra la medición para que la siguiente persona empiece de cero. */
    t.done = () => { t.startedAt = null; };
    /* Pone los campos en un FormData (si hay medición; `set`: un reintento con el mismo FormData no los duplica). */
    t.appendTo = (formData) => { const p = t.payload(); if (p) { formData.set('took_ms', String(p.took_ms)); formData.set('ui_flow', p.ui_flow); } return p; };
    return t;
  }
  return { create, MAX_MS };
});
