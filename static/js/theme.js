/* Apariencia por computador (Sprint 2.3/2.4, 2026-09-16) — pedido explícito, aclarado por Juan
   David: el color/tipografía elegidos en Configuración > Apariencia son una preferencia LOCAL de
   ESTE navegador/computador, no se sincroniza ni se guarda en la base de datos. Se aplica acá,
   antes de que se note el flash del tema por defecto, leyendo las mismas claves que
   configuracion.html escribe. Envuelto en try/catch: localStorage puede fallar en ventana
   privada o con site data bloqueada. Disponible para TODOS los roles (Sprint 2.4, ronda 2) —
   cargado en todos los templates, igual que toast.js. */
(function () {
  // Contraste automático de texto (Sprint 2.4 Fase 13, 2026-09-17, pedido explícito): "en todo
  // lugar que haya texto... si detecta que el fondo es claro, letra negra; si es oscuro, letra
  // blanca". Fórmula de luminancia percibida (coeficientes ITU-R BT.601, ya usados de forma
  // habitual para esto) — no es una conversión de color exacta, pero alcanza de sobra para
  // decidir blanco/negro. Expuesta globalmente porque calendario.html la reusa para los chips de
  // "color de pañoleta" (otro lugar con fondo elegido libremente por el usuario).
  window.goldenContrastColor = function (hex) {
    if (!hex) return '#000000';
    let c = String(hex).replace('#', '').trim();
    if (c.length === 3) c = c.split('').map((ch) => ch + ch).join('');
    if (c.length !== 6 || /[^0-9a-fA-F]/.test(c)) return '#000000';
    const r = parseInt(c.substr(0, 2), 16), g = parseInt(c.substr(2, 2), 16), b = parseInt(c.substr(4, 2), 16);
    const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return luminance > 0.6 ? '#000000' : '#ffffff';
  };

  // Mismas 40 familias tipográficas que ya ofrece el editor de escarapelas (badge_editor.html:
  // FONT_FAMILIES) — un solo <link> de Google Fonts, idéntico al de ahí, inyectado una vez por
  // página (no todas las páginas lo tenían, y sin cargarlo la fuente elegida no se ve aunque la
  // variable CSS ya diga cuál es). Si la página ya lo trae (ej. badge_editor.html), no se duplica.
  var FONTS_URL = "https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&family=Open+Sans:wght@400;700&family=Lato:wght@400;700&family=Montserrat:wght@400;700&family=Oswald:wght@400;700&family=Raleway:wght@400;700&family=Poppins:wght@400;700&family=Merriweather:wght@400;700&family=Playfair+Display:wght@400;700&family=Nunito:wght@400;700&family=Ubuntu:wght@400;700&family=PT+Sans:wght@400;700&family=Noto+Sans:wght@400;700&family=Source+Sans+Pro:wght@400;700&family=Rubik:wght@400;700&family=Inter:wght@400;700&family=Work+Sans:wght@400;700&family=Quicksand:wght@400;700&family=Fira+Sans:wght@400;700&family=Barlow:wght@400;700&family=Karla:wght@400;700&family=Mulish:wght@400;700&family=Josefin+Sans:wght@400;700&family=Bebas+Neue&family=Dancing+Script&family=Pacifico&family=Lobster&family=Caveat&family=Anton&family=Archivo+Black&family=Cormorant+Garamond:wght@400;700&family=Crimson+Text:wght@400;700&family=Libre+Baskerville:wght@400;700&family=EB+Garamond:wght@400;700&family=Abril+Fatface&family=Comfortaa:wght@400;700&family=DM+Sans:wght@400;700&family=Space+Grotesk:wght@400;700&family=Manrope:wght@400;700&family=Zilla+Slab:wght@400;700&display=swap";

  window.GOLDEN_FONT_FAMILIES = [
    'Roboto', 'Open Sans', 'Lato', 'Montserrat', 'Oswald', 'Raleway', 'Poppins', 'Merriweather',
    'Playfair Display', 'Nunito', 'Ubuntu', 'PT Sans', 'Noto Sans', 'Source Sans Pro', 'Rubik',
    'Inter', 'Work Sans', 'Quicksand', 'Fira Sans', 'Barlow', 'Karla', 'Mulish', 'Josefin Sans',
    'Bebas Neue', 'Dancing Script', 'Pacifico', 'Lobster', 'Caveat', 'Anton', 'Archivo Black',
    'Cormorant Garamond', 'Crimson Text', 'Libre Baskerville', 'EB Garamond', 'Abril Fatface',
    'Comfortaa', 'DM Sans', 'Space Grotesk', 'Manrope', 'Zilla Slab',
  ];

  // Expuesta globalmente (2026-09-16) — configuracion.html la reusa al aplicar un cambio EN LA
  // MISMA carga de página (este IIFE solo corre una vez, al inicio, con lo que ya había en
  // localStorage — sin esto, elegir una fuente nueva no se veía hasta recargar).
  window.goldenEnsureFontLink = function () {
    if (!document.querySelector('link[href="' + FONTS_URL + '"]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = FONTS_URL;
      document.head.appendChild(link);
    }
  };

  try {
    const fontFamily = localStorage.getItem('golden_theme_font_family');
    if (fontFamily) {
      window.goldenEnsureFontLink();
      const value = `'${fontFamily}', sans-serif`;
      document.documentElement.style.setProperty('--font-heading-primary', value);
      document.documentElement.style.setProperty('--font-heading-secondary', value);
      document.documentElement.style.setProperty('--font-body', value);
    }

    const primary = localStorage.getItem('golden_theme_primary');
    if (primary) {
      document.documentElement.style.setProperty('--golden-primary', primary);
      // El mismo color también pinta el fondo del menú lateral (2026-09-16, ronda 2).
      document.documentElement.style.setProperty('--golden-sidebar-bg', primary);
      // Contraste automático (2026-09-17, pedido explícito) — antes el texto de botones/menú
      // quedaba fijo, ahora se recalcula según qué tan clara/oscura sea la elegida.
      const contrast = window.goldenContrastColor(primary);
      document.documentElement.style.setProperty('--golden-primary-contrast', contrast);
      document.documentElement.style.setProperty('--golden-sidebar-contrast', contrast);
    }
  } catch (e) { /* preferencia local opcional — si falla, se queda con el tema por defecto */ }
})();
