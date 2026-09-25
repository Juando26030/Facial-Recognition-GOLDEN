// Aviso informativo de cookies para las páginas PÚBLICAS (formularios, escarapela y certificado digital).
// Solo usamos cookies necesarias (sesión/seguridad) y no hay rastreo de terceros: por eso es un aviso, no un bloqueo por consentimiento.
// Si algún día se agrega un píxel de Meta/TikTok u otro tracking no esencial, este banner debe pasar a pedir consentimiento (ver docs).
(function () {
  var KEY = 'gw_cookie_notice';
  try { if (localStorage.getItem(KEY) === '1') return; } catch (e) { /* sin almacenamiento: se muestra siempre */ }
  var bar = document.createElement('div');
  bar.setAttribute('role', 'region');
  bar.setAttribute('aria-label', 'Aviso de cookies');
  bar.style.cssText = 'position:fixed; left:12px; right:12px; bottom:12px; z-index:9999; background:#1d1d2b; color:#fff; border-radius:12px; padding:12px 16px; font:14px/1.5 Arial,sans-serif; display:flex; gap:12px; align-items:center; flex-wrap:wrap; box-shadow:0 6px 24px rgba(0,0,0,.35);';
  bar.innerHTML = '<span style="flex:1 1 260px;">Usamos solo cookies necesarias para que el sitio funcione (sesión y seguridad); no usamos cookies de publicidad ni de rastreo. Si usas la traducción, Google puede guardar las suyas. <a href="/privacidad" style="color:#ffd54f;">Política de Privacidad</a></span>';
  var btn = document.createElement('button');
  btn.type = 'button'; btn.textContent = 'Entendido';
  btn.style.cssText = 'background:#ffd54f; color:#111; border:none; border-radius:20px; padding:8px 18px; font:700 14px Arial,sans-serif; cursor:pointer;';
  btn.addEventListener('click', function () { try { localStorage.setItem(KEY, '1'); } catch (e) { /* opcional */ } bar.remove(); });
  bar.appendChild(btn);
  document.body.appendChild(bar);
})();
