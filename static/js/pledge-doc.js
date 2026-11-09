/* Compromiso firmado (templates/pledge_document.html): el botón abre el cuadro de impresión del navegador (ahí se puede «Guardar como PDF»). Sin onclick en línea. */
document.addEventListener('click', function (ev) {
    if (ev.target.closest && ev.target.closest('[data-print]')) window.print();
});
