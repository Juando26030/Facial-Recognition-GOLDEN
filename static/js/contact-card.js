/* Páginas de la PERSONA (Fase 8): /contacto/<token> (decide si comparte y ve su QR) y /tarjeta/<token> (lo que abre el teléfono al escanear: «Guardar contacto»). */
(function () {
  'use strict';
  const C = window.GWContact;
  const root = document.querySelector('main[data-token]');
  if (!root) return;
  const token = root.dataset.token, mode = root.dataset.mode;
  const $ = (id) => document.getElementById(id);
  const get = async (url) => { const r = await fetch(url, { cache: 'no-store' }); if (!r.ok) throw new Error(String(r.status)); return r.json(); };

  async function manage() {
    let d;
    try { d = await get('/contacto/' + token + '/data'); } catch (e) { $('shareText').textContent = 'Este enlace no está disponible.'; return; }
    $('shareText').textContent = d.text;
    if (d.minor) { $('minorMsg').hidden = false; return; }
    let sharing = d.sharing;
    const paint = () => {
      $('acceptBtn').hidden = sharing; $('revokeBtn').hidden = !sharing;
      $('adultRow').hidden = sharing || !d.needs_adult;
      $('stateMsg').textContent = sharing ? 'Estás compartiendo tus datos con los expositores que escanees. Puedes dejar de hacerlo cuando quieras.' : 'Por ahora NO compartes tus datos con expositores.';
      $('qrCard').hidden = !sharing;
      if (sharing) C.drawQr($('qrHost'), C.absolute(d.card_path));
    };
    $('adultText').textContent = d.adult_text;
    const send = async (accept, btn) => {
      btn.disabled = true;
      try {
        const r = await fetch('/contacto/' + token + '/share', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ accept, adult: $('adultBox').checked }) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'No se pudo guardar tu respuesta');
        sharing = accept; paint();
        if (window.showToast) showToast(accept ? 'Listo: compartes tus datos con expositores.' : 'Listo: dejaste de compartir tus datos.', 'success');
      } catch (e) { if (window.showToast) showToast(e.message, 'error'); } finally { btn.disabled = false; }
    };
    $('acceptBtn').addEventListener('click', () => {
      if (d.needs_adult && !$('adultBox').checked) { if (window.showToast) showToast('Confirma que eres mayor de 18 años.', 'warning'); return; }
      send(true, $('acceptBtn'));
    });
    $('revokeBtn').addEventListener('click', () => send(false, $('revokeBtn')));
    paint();
  }

  async function card() {
    let d;
    try { d = await get('/tarjeta/' + token + '/data'); } catch (e) { $('goneBox').hidden = false; return; }
    $('cardBox').hidden = false;
    $('cardName').textContent = d.name || 'Contacto';
    $('cardCompany').textContent = d.company || ''; $('cardTitle').textContent = d.title || '';
    $('cardPhone').textContent = d.phone ? 'Tel: ' + d.phone : ''; $('cardEmail').textContent = d.email ? 'Correo: ' + d.email : '';
    $('saveBtn').href = '/tarjeta/' + token + '/vcard';
  }

  (mode === 'manage' ? manage : card)();
})();
