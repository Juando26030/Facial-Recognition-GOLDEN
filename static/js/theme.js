/* Apariencia por computador (Sprint 2.3, 2026-09-16) — pedido explícito, aclarado por Juan David:
   el color/tipografía elegidos en Configuración > Apariencia son una preferencia LOCAL de ESTE
   navegador/computador, no se sincroniza ni se guarda en la base de datos. Se aplica acá, antes
   de que se note el flash del dorado por defecto, leyendo las mismas claves que
   configuracion.html escribe. Envuelto en try/catch: localStorage puede fallar en ventana
   privada o con site data bloqueada. */
(function () {
  try {
    const primary = localStorage.getItem('golden_theme_primary');
    if (primary) {
      document.documentElement.style.setProperty('--golden-primary', primary);
      // El mismo color también pinta el fondo del menú lateral (pedido explícito, 2026-09-16,
      // ronda 2) — el texto del menú se queda siempre blanco (ver .golden-sidebar a en style.css).
      document.documentElement.style.setProperty('--golden-sidebar-bg', primary);
    }

    const fontsRaw = localStorage.getItem('golden_theme_fonts');
    if (fontsRaw) {
      const fonts = JSON.parse(fontsRaw);
      if (fonts.heading_primary) document.documentElement.style.setProperty('--font-heading-primary', fonts.heading_primary);
      if (fonts.heading_secondary) document.documentElement.style.setProperty('--font-heading-secondary', fonts.heading_secondary);
      if (fonts.body) document.documentElement.style.setProperty('--font-body', fonts.body);
    }
  } catch (e) { /* preferencia local opcional — si falla, se queda con el tema por defecto */ }
})();
