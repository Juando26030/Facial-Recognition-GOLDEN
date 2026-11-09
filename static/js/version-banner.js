/* Franja de versión (Fase 6): solo en servidores locales (PRODUCTION_URL definida). Si el servidor no tiene la versión de producción, muestra un aviso fijo arriba. En la nube el servidor responde
   {configured:false} y no se pinta nada. Una consulta al abrir la página (el servidor guarda la comparación 5 min). Texto escapado. */
(function () {
  'use strict';
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  fetch('/api/ops/version-check').then((r) => (r.ok ? r.json() : null)).then((d) => {
    if (!d || !d.configured || d.status === 'igual' || d.status === 'desconocida') return;
    const bar = document.createElement('div');
    bar.className = 'gw-versionbar gw-versionbar--' + (d.status === 'desactualizada' ? 'err' : 'warn');
    bar.setAttribute('role', 'alert');
    bar.innerHTML = `<strong>Versión:</strong> ${esc(d.message)}`;
    document.body.insertBefore(bar, document.body.firstChild);
  }).catch(() => {});
})();
