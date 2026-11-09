/* Página del EXPOSITOR (Fase 8): escanea asistentes, ve su lista y baja el Excel. Usa el lector QR de siempre (qr.js). */
(function () {
  'use strict';
  const C = window.GWContact;
  const root = document.querySelector('main[data-token]');
  const token = root.dataset.token, base = '/expositor/' + token;
  const $ = (id) => document.getElementById(id);
  const toast = (m, t) => { if (window.showToast) showToast(m, t); };

  function paintList(d) {
    $('leadCount').textContent = d.count;
    $('leadList').innerHTML = d.leads.map((l) => '<li class="ct-item"><span><strong>' + C.esc((l.first_name + ' ' + l.last_name).trim()) + '</strong>' +
      '<span class="ct-muted">' + C.esc([l.company, l.title].filter(Boolean).join(' · ')) + '</span></span>' +
      '<a class="gw-btn gw-btn--secondary gw-btn--sm" href="' + base + '/vcard/' + encodeURIComponent(l.card) + '">Guardar</a></li>').join('') ||
      '<li class="ct-muted">Aún no has escaneado a nadie.</li>';
  }

  async function load() {
    const r = await fetch(base + '/data', { cache: 'no-store' });
    if (!r.ok) { toast('Este enlace no está disponible.', 'error'); return; }
    const d = await r.json();
    paintList(d);
    const url = C.absolute(d.card_path);
    C.drawQr($('qrHost'), url);
    $('cardUrl').textContent = url;
    $('xlsxBtn').href = base + '/leads.xlsx';
    $('copyBtn').onclick = async () => toast((await C.copyText(url)) ? 'Enlace copiado' : 'No se pudo copiar', 'info');
    if (C.nfcSupported()) { $('nfcBtn').hidden = false; $('nfcBtn').onclick = () => C.writeTag(url, $('nfcStatus')); }
  }

  function showResult(res) {
    const box = $('scanResult'); box.hidden = false;
    if (res.status === 'new' || res.status === 'known') {
      const p = res.person;
      box.className = 'gw-state gw-state--success';
      box.innerHTML = '<p class="gw-state__title">' + C.esc((p.first_name + ' ' + p.last_name).trim()) + (res.status === 'known' ? ' (ya estaba en tu lista)' : '') + '</p>' +
        '<p class="gw-state__text">' + C.esc([p.company, p.title, p.phone, p.email].filter(Boolean).join(' · ')) + '</p>' +
        '<a class="gw-btn gw-btn--primary gw-btn--block" href="' + base + '/vcard/' + encodeURIComponent(res.card) + '">Guardar contacto</a>';
    } else {
      box.className = 'gw-state gw-state--warning';
      box.innerHTML = '<p class="gw-state__text">' + C.esc(res.message || 'No se pudo.') + '</p>';
    }
  }

  async function send(text) {
    try {
      const r = await fetch(base + '/scan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
      showResult(await r.json());
      load();
    } catch (e) { toast('Sin conexión. Inténtalo de nuevo.', 'error'); }
  }

  $('scanBtn').addEventListener('click', () => {
    if (!window.QrScanner) { toast('El lector no está disponible.', 'error'); return; }
    QrScanner.open({ title: 'Escanear asistente', cooldownMs: 2500, onCode: (text) => { const x = document.querySelector('.qr-close'); if (x) x.click(); send(text); } });
  });
  $('cedulaBtn').addEventListener('click', () => {
    const v = $('cedulaIn').value.trim();
    if (v) { send(v); $('cedulaIn').value = ''; }
  });
  load();
})();
