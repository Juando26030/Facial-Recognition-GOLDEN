/* Ingreso en espera (S1, templates/ingreso_espera.html): pregunta POST /api/ingreso/estado cada pocos segundos mientras el coordinador decide. Se detiene sola al
   aprobarse (va a la página que corresponda), al no aprobarse, al vencer la solicitud (5 minutos) o si ya no hay solicitud. Es el único sondeo que toca la base y solo
   corre mientras alguien espera. */
(function () {
    'use strict';
    const box = document.getElementById('ingresoEspera');
    if (!box) return;
    const every = Math.max(2, Number(box.dataset.pollSeconds) || 3) * 1000;
    const deadline = Date.now() + (Math.max(30, Number(box.dataset.ttlSeconds) || 300) + 10) * 1000;
    const aviso = document.getElementById('ingresoAviso');
    const titulo = document.getElementById('ingresoTitulo');
    const detalle = document.getElementById('ingresoDetalle');
    const rueda = document.getElementById('ingresoRueda');
    const cancelar = document.getElementById('ingresoCancelar');
    const volver = document.getElementById('ingresoVolver');
    let timer = null, done = false;

    function finish(title, body, ok) {
        done = true;
        if (timer) clearTimeout(timer);
        aviso.classList.remove('gw-alert--warn');
        aviso.classList.add(ok ? 'gw-alert--ok' : 'gw-alert--err');
        titulo.textContent = title;
        detalle.textContent = body || '';
        if (rueda) rueda.remove();
        document.getElementById('ingresoCancelarBox').hidden = true;
        volver.hidden = !!ok;
    }

    async function ask() {
        if (done) return;
        if (Date.now() > deadline) { finish('La solicitud de ingreso venció. Vuelve a ingresar.', 'Si todavía necesitas entrar, escribe de nuevo tu usuario y contraseña.'); return; }
        try {
            const res = await fetch('/api/ingreso/estado', { method: 'POST', headers: { 'X-Gw-Fetch': '1' }, cache: 'no-store' });
            const d = await res.json().catch(() => ({}));
            if (d.status === 'approved') { finish('Ingreso autorizado', 'Entrando…', true); window.location.replace(d.redirect || '/'); return; }
            if (d.status === 'denied') { finish(d.message || 'El coordinador no autorizó el ingreso.', 'Si crees que es un error, habla con el coordinador del evento.'); return; }
            if (d.status === 'expired' || d.status === 'none') { finish(d.message || 'La solicitud de ingreso venció. Vuelve a ingresar.', 'Si todavía necesitas entrar, escribe de nuevo tu usuario y contraseña.'); return; }
        } catch (e) { /* sin red un momento: se vuelve a preguntar en el siguiente turno */ }
        timer = setTimeout(ask, every);
    }

    cancelar.addEventListener('click', async () => {
        cancelar.disabled = true;
        try { await fetch('/api/ingreso/cancelar', { method: 'POST', headers: { 'X-Gw-Fetch': '1' } }); } catch (e) { /* igual se vuelve al login */ }
        done = true;
        window.location.replace('/login');
    });

    timer = setTimeout(ask, 800);
})();
