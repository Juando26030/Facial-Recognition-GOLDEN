/* Pantalla /instalar (SaaS, pieza 1; docs/27_SAAS_EMPRESAS.md): primer arranque sin scripts. Crea el primer Super Admin y lleva a «Ingresar». El servidor valida todo; aquí solo se evita un viaje
   cuando falta un dato. Mensajes con showToast. */
(function () {
  'use strict';
  const form = document.getElementById('installForm');
  if (!form) return;
  const button = document.getElementById('installSubmit');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = {};
    Array.from(form.elements).forEach((f) => { if (f.name) body[f.name] = f.type === 'password' ? f.value : f.value.trim(); });
    const missing = Array.from(form.elements).find((f) => f.name && f.required && !f.value);
    if (missing) { showToast('Completa todos los datos para continuar.', 'error'); missing.focus(); return; }
    if (body.password !== body.password_confirm) { showToast('Las dos contraseñas no coinciden. Escríbelas de nuevo.', 'error'); form.elements.password_confirm.focus(); return; }
    button.disabled = true;
    try {
      const res = await fetch('/instalar', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const data = await res.json().catch(() => ({}));
      if (res.status === 404) { showToast('La plataforma ya tiene su cuenta de dueño. Te llevamos a «Ingresar».', 'info'); setTimeout(() => { window.location.href = '/login'; }, 1500); return; }
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo crear la cuenta. Intenta de nuevo.');
      showToast(data.message || 'Cuenta creada.', 'success');
      setTimeout(() => { window.location.href = data.redirect || '/login'; }, 1200);
    } catch (err) {
      showToast(err.message, 'error');
      button.disabled = false;
    }
  });
})();
