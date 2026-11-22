/* Ayuda ⓘ dentro del título de un grupo plegable (<summary>): sin esto, pulsar la ⓘ (o «Entendido») también abriría o cerraría el grupo.
   Solo cancela el plegado; la ayuda la sigue abriendo gw-ui.js (delegación en document). Lo usa «Editar evento» (templates/_event_edit_modal.html). */
(function () {
  if (window.__gwSummaryHelp) return;
  window.__gwSummaryHelp = true;
  document.addEventListener('click', function (e) {
    var t = e.target;
    if (t && t.closest && t.closest('summary .gw-help')) e.preventDefault();
  });
  document.addEventListener('keydown', function (e) {      // Espacio o Enter sobre la ⓘ: el <summary> no debe plegarse
    var t = e.target;
    if ((e.key === ' ' || e.key === 'Enter') && t && t.closest && t.closest('summary .gw-help') && !t.matches('button')) e.preventDefault();
  });
})();
