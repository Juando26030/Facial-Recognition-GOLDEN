/* Tarjeta «Servidor local» de Configuración (Fase 10 E): pregunta a /api/local-installer si hay instalador y arma el botón de descarga. Se pide la primera vez que se abre la pestaña.
   Sin atributos de evento en línea: el botón es un enlace normal a /api/local-installer/download (el servidor redirige o transmite el archivo). */
(function () {
  const body = document.getElementById('localInstallerBody');
  const tab = document.getElementById('tab_servidor');
  if (!body || !tab) return;
  let started = false;

  function row(text, cls) {
    const p = document.createElement('p');
    p.className = cls || '';
    p.textContent = text;
    return p;
  }

  async function load() {
    if (started) return;
    started = true;
    try {
      const res = await fetch('/api/local-installer', { headers: { Accept: 'application/json' } });
      if (!res.ok) throw new Error('http ' + res.status);
      const d = await res.json();
      body.textContent = '';
      if (!d.available) {
        const badge = document.createElement('span');
        badge.className = 'gw-badge gw-badge--info';
        badge.textContent = 'Aún no disponible';
        body.appendChild(badge);
        body.appendChild(row('El instalador todavía no se ha publicado. Cuando el equipo de Golden lo suba, aparecerá aquí el botón de descarga.', 'gw-hint'));
        return;
      }
      const ok = document.createElement('span');
      ok.className = 'gw-badge gw-badge--ok';
      ok.textContent = 'Disponible';
      body.appendChild(ok);
      body.appendChild(row(d.version ? `Versión: ${d.version}` : '', 'gw-hint'));
      const a = document.createElement('a');
      a.className = 'gw-btn gw-btn--primary';
      a.href = '/api/local-installer/download';
      a.textContent = 'Descargar instalador para Windows';
      body.appendChild(a);
      body.appendChild(row('Es un archivo grande: la descarga puede tardar varios minutos.', 'gw-hint'));
    } catch (e) {
      started = false;
      body.textContent = '';
      body.appendChild(row('No se pudo revisar el instalador. Cierra esta pestaña y ábrela de nuevo para intentarlo otra vez.', 'gw-hint'));
      if (window.showToast) showToast('No se pudo revisar el instalador del servidor local', 'error');
    }
  }

  tab.addEventListener('click', load);
  tab.addEventListener('focus', load);
  if (location.hash === '#servidor' || tab.getAttribute('aria-selected') === 'true') load();
})();
