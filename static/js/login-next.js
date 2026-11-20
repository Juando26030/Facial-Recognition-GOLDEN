/* Al volver a entrar tras una sesión cerrada por tiempo: si la página donde estaba la persona tenía una pestaña interna (#algo), el navegador la conserva en la dirección del inicio de sesión y aquí se
   añade a la dirección de regreso (app/nextpage.py la valida en el servidor). Sin `next` o sin # no hace nada. */
(function () {
  var f = document.querySelector('input[name="next"]');
  var h = window.location.hash;
  if (!f || !f.value || !h || h.length > 200 || f.value.indexOf('#') >= 0) return;
  f.value += h;
})();
