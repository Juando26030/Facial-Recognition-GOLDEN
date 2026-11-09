/* Página pública de entrega al cliente (/entrega/<token>): envía la encuesta y, al recibirla, muestra «Descargar base de datos». Sin datos personales. */
(function () {
  'use strict';
  const form = document.getElementById('surveyForm');
  if (!form) return;
  const errBox = document.getElementById('surveyError'), errText = document.getElementById('surveyErrorText'), send = document.getElementById('surveySend');

  function showError(msg) { errText.textContent = msg; errBox.hidden = false; errBox.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
  function collect() {
    const answers = {};
    form.querySelectorAll('fieldset[data-qid]').forEach((fs) => {
      const qid = fs.dataset.qid, picked = fs.querySelector('input[type=radio]:checked'), c = fs.querySelector('textarea');
      answers[qid] = { choice: picked ? picked.value : null, comment: c ? c.value : '' };
    });
    return { answers };
  }
  function firstMissing() {
    return Array.from(form.querySelectorAll('fieldset[data-qid]')).find((fs) => fs.dataset.required === 'true' && !fs.querySelector('input[type=radio]:checked'));
  }
  function showDone(canDownload) {
    form.hidden = true;
    document.getElementById('doneCard').hidden = false;
    document.getElementById('downloadBox').hidden = !canDownload;
    document.getElementById('noDbBox').hidden = !!canDownload;
    document.getElementById('doneCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    errBox.hidden = true;
    const missing = firstMissing();
    if (missing) {
      showError('Falta responder la pregunta ' + missing.querySelector('.entrega__num').textContent.replace('.', '') + '.');
      const first = missing.querySelector('input'); if (first) first.focus();
      return;
    }
    send.disabled = true;
    try {
      const res = await fetch(form.dataset.submitUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(collect()) });
      const body = await res.json().catch(() => ({}));
      if (res.ok || res.status === 409) {                    // 409: ya la habían enviado; se sigue al paso de la descarga
        if (window.showToast) window.showToast(res.ok ? 'Encuesta enviada. ¡Gracias!' : (body.detail || 'Ya recibimos la encuesta.'));
        showDone(!!(body.can_download || body.has_db));
      } else {
        showError(body.detail || 'No se pudo enviar la encuesta. Intente de nuevo.');
      }
    } catch (e) {
      showError('No se pudo enviar la encuesta. Revise su conexión e intente de nuevo.');
    } finally {
      send.disabled = false;
    }
  });
})();
