/* Tarjeta «Llaves de producto» de Configuración › Servidor local (solo administradores): crear, ver y deshabilitar las llaves que pide el instalador del servidor local.
   Sin atributos de evento en línea: delegación sobre el cuerpo de la tabla. La llave es de un solo uso; deshabilitar es definitivo. */
(function () {
  const rows = document.getElementById('skRows');
  if (!rows) return;
  const labelIn = document.getElementById('skLabel');
  const createBtn = document.getElementById('skCreate');
  const summary = document.getElementById('skSummary');
  const BADGE = { active: 'ok', unused: 'info', claimed: 'info', expired: 'warn', disabled: 'err' };
  const FRESH = { igual: 'Al día', desactualizada: 'Desactualizado', distinta_version: 'Versión distinta', adelantada: 'Más nuevo que producción', desconocida: 'Sin dato' };
  let started = false;

  const fmt = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
    return isNaN(d) ? '—' : d.toLocaleString('es-CO', { dateStyle: 'short', timeStyle: 'short' });
  };
  const cell = (tr, node, label) => { const td = document.createElement('td'); if (label) td.dataset.label = label; if (typeof node === 'string') td.textContent = node; else if (node) td.appendChild(node); tr.appendChild(td); return td; };          // data-label: en pantallas chicas cada fila pasa a ser una tarjeta con «Estado: …», «Servidor: …» (.gw-table-cards)

  async function api(url, method, body) {
    const res = await fetch(url, { method: method || 'GET', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
    let d = null;
    try { d = await res.json(); } catch (e) { /* sin cuerpo */ }
    if (!res.ok) throw new Error((d && d.detail) || 'No se pudo completar la acción');
    return d;
  }

  function render(d) {
    rows.textContent = '';
    document.getElementById('skDays').textContent = d.valid_days;
    const c = d.counts;
    const late = d.keys.filter((k) => k.node && !k.node.revoked && k.node.freshness && ['desactualizada', 'distinta_version'].includes(k.node.freshness.status)).length;
    summary.textContent = '';
    const chip = (text, kind) => { const b = document.createElement('span'); b.className = 'gw-badge gw-badge--' + kind; b.textContent = text; summary.appendChild(b); };          // un chip por dato: se lee de un vistazo y se acomoda solo en el celular
    chip('Producción: ' + (((d.cloud && d.cloud.commit) || '—').slice(0, 7)), 'info');
    chip(`${late} por actualizar`, late ? 'warn' : 'ok');
    chip(`${c.active} activos`, 'ok');
    chip(`${c.unused + c.claimed} sin usar`, 'info');
    chip(`${c.disabled} deshabilitadas`, 'info');
    chip(`${c.expired} vencidas`, c.expired ? 'warn' : 'info');
    if (!d.keys.length) {
      const tr = document.createElement('tr');
      const td = cell(tr, 'Todavía no hay llaves. Crea la primera para instalar un servidor.');
      td.colSpan = 6;
      rows.appendChild(tr);
      return;
    }
    d.keys.forEach((k) => {
      const tr = document.createElement('tr');
      const code = document.createElement('code'); code.textContent = k.code;
      cell(tr, code, 'Llave').classList.add('gw-table-cards__title');
      cell(tr, k.label || '—', 'Nombre');
      const b = document.createElement('span'); b.className = 'gw-badge gw-badge--' + (BADGE[k.status] || 'info'); b.textContent = k.status_label;
      cell(tr, b, 'Estado');
      const n = k.node;
      const srv = document.createElement('div');
      if (n) {
        const f = n.freshness || {};
        const fb = document.createElement('span');
        fb.className = 'gw-badge gw-badge--' + (f.status === 'igual' ? 'ok' : (f.status === 'desconocida' ? 'info' : 'warn'));
        fb.textContent = FRESH[f.status] || 'Sin dato';
        fb.title = f.message || '';
        srv.appendChild(fb);
        const info = document.createElement('span'); info.className = 'gw-hint';
        info.textContent = ` ${n.name}${f.commit ? ' · ' + f.commit : ''} · visto ${fmt(n.last_seen_at)}`;
        srv.appendChild(info);
      } else srv.textContent = (k.status === 'unused' || k.status === 'claimed') ? 'Vence ' + fmt(k.expires_at) : '—';
      cell(tr, srv, 'Servidor');
      cell(tr, `${fmt(k.created_at)}${k.created_by_name ? ' · ' + k.created_by_name : ''}`, 'Creada');
      const act = cell(tr, '');
      act.classList.add('gw-table-cards__actions');
      if (k.status !== 'disabled') {
        const btn = document.createElement('button');
        btn.type = 'button'; btn.className = 'gw-btn gw-btn--danger gw-btn--sm'; btn.dataset.disable = k.id; btn.dataset.code = k.code;
        btn.textContent = 'Deshabilitar';
        act.appendChild(btn);
      }
      rows.appendChild(tr);
    });
  }

  async function load() {
    try { render(await api('/api/server-keys')); started = true; }
    catch (e) { started = false; rows.textContent = ''; const tr = document.createElement('tr'); cell(tr, 'No se pudieron cargar las llaves.').colSpan = 6; rows.appendChild(tr); if (window.showToast) showToast(e.message, 'error'); }
  }

  createBtn.addEventListener('click', async () => {
    createBtn.disabled = true;
    try {
      const k = await api('/api/server-keys', 'POST', { label: labelIn.value });
      labelIn.value = '';
      if (window.showToast) showToast(`Llave creada: ${k.code}. Cópiala y entrégala a quien instalará el servidor.`, 'success');
      await load();
    } catch (e) { if (window.showToast) showToast(e.message, 'error'); }
    finally { createBtn.disabled = false; }
  });

  rows.addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-disable]');
    if (!btn) return;
    const ok = await showConfirm(`¿Deshabilitar la llave ${btn.dataset.code}? El servidor que la usa dejará de funcionar apenas vuelva a tener internet y la llave no se podrá reutilizar. Para instalar de nuevo habrá que crear otra.`, { confirmLabel: 'Deshabilitar' });
    if (!ok) return;
    btn.disabled = true;
    try { await api(`/api/server-keys/${encodeURIComponent(btn.dataset.disable)}/disable`, 'POST', {}); if (window.showToast) showToast('Llave deshabilitada', 'success'); await load(); }
    catch (err) { btn.disabled = false; if (window.showToast) showToast(err.message, 'error'); }
  });

  const tab = document.getElementById('tab_servidor');
  if (tab) { tab.addEventListener('click', () => { if (!started) load(); }); tab.addEventListener('focus', () => { if (!started) load(); }); }
  load();
})();
