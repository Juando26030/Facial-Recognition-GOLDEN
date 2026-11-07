/* Pantalla «Diseñar plantilla para eventos» (templates/plantilla_evento.html): carga la plantilla, monta el diseñador (static/js/event-template-designer.js) y la guarda con la barra única (GWParams).
   GET /api/event-template · PUT /api/event-template (admin+, versionado: si otro administrador guardó antes responde 409 y NO se pisa nada). */
(function () {
  'use strict';
  const root = document.getElementById('tplRoot');
  if (!root || !window.EventTemplateDesigner) return;
  const tabs = document.getElementById('paramsRoot');
  const loading = document.getElementById('tplLoading'), err = document.getElementById('tplError');
  const designer = EventTemplateDesigner.mount(root, { onChange: () => GWParams.markDirty('plantilla') });

  async function load() {
    err.hidden = true; loading.hidden = false; tabs.hidden = true;
    try {
      const res = await fetch('/api/event-template', { cache: 'no-store' });
      if (!res.ok) throw new Error('http ' + res.status);
      designer.load(await res.json());
    } catch (e) {
      loading.hidden = true; err.hidden = false;
      document.getElementById('tplMeta').textContent = 'No se pudo cargar';
      return false;
    }
    loading.hidden = true; tabs.hidden = false;
    GWParams.markClean('plantilla');
    return true;
  }

  GWParams.register({
    key: 'plantilla', label: 'Plantilla de eventos', order: 10,
    save: async () => {
      if (!designer.hasModel()) throw new Error('La plantilla no está cargada');
      const problems = designer.validate();
      if (problems.length) throw new Error(problems[0] + (problems.length > 1 ? ' (y ' + (problems.length - 1) + ' más)' : ''));
      let res;
      try {
        res = await fetch('/api/event-template', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(designer.payload()) });
      } catch (e) { throw new Error('Sin conexión: no se guardó. Revisa tu red e inténtalo de nuevo.'); }
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo guardar la plantilla');
      designer.load(data);
    },
  });
  document.getElementById('tplRetry').addEventListener('click', load);
  load();
})();
