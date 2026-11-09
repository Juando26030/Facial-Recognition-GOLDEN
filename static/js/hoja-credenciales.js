/* Hoja de ingreso del personal temporal: el botón abre el cuadro de impresión normal del navegador (nunca impresión silenciosa). */
(function () {
    'use strict';
    var btn = document.getElementById('hojaImprimir');
    if (btn) btn.addEventListener('click', function () { window.print(); });
})();
