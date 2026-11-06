/* Veredicto del Registro (Fase 1.7, Ola 1A): una banda grande debajo del buscador que dice, con ícono y palabras, qué pasó con la última búsqueda o acreditación
   (acreditado / ya registrado / no está en la lista / hay que confirmar). Es solo presentación: no decide nada ni cambia el flujo; los avisos (toasts) de siempre siguen.
   Uso: window.GWVerdict.show('ok' | 'warn' | 'err' | 'info', 'Título', 'Detalle opcional'). Sin la banda en la página (otras pantallas, pruebas) no hace nada. */
(function (root) {
  'use strict';
  const ICON = { ok: 'check-lg', warn: 'alert', err: 'error', info: 'info' };
  const HIDE_MS = { ok: 8000, info: 12000, warn: 15000, err: 15000 };
  let timer = null;

  function parts() {
    const doc = root.document;
    if (!doc || !doc.getElementById) return null;
    const box = doc.getElementById('gwVerdict');
    if (!box) return null;
    return { box, icon: doc.getElementById('gwVerdictIcon'), title: doc.getElementById('gwVerdictTitle'), text: doc.getElementById('gwVerdictText') };
  }

  function hide() {
    const p = parts(); if (!p) return;
    if (timer) { clearTimeout(timer); timer = null; }
    p.box.hidden = true;
  }

  function show(kind, title, text) {
    const p = parts(); if (!p) return;
    const k = ICON[kind] ? kind : 'info';
    if (timer) clearTimeout(timer);
    p.box.className = 'gw-verdict' + (k === 'info' ? '' : ' gw-verdict--' + k);
    p.box.setAttribute('role', k === 'err' ? 'alert' : 'status');
    if (p.icon) { const base = String(p.icon.getAttribute('href') || '').split('#')[0]; p.icon.setAttribute('href', base + '#i-' + ICON[k]); }
    if (p.title) p.title.textContent = title || '';
    if (p.text) { p.text.textContent = text || ''; p.text.hidden = !text; }
    p.box.hidden = false;
    timer = setTimeout(hide, HIDE_MS[k]);
  }

  root.GWVerdict = { show, hide };
  /* al volver a escribir en el buscador la banda anterior ya no aplica */
  if (root.document && root.document.addEventListener) root.document.addEventListener('input', (e) => { if (e && e.target && e.target.id === 'searchCedula') hide(); });
})(typeof window !== 'undefined' ? window : globalThis);
