/* Configuración (templates/configuracion.html). Dos bloques que se guardan con la barra única (GWParams, static/js/params-save.js):
   - «apariencia»: preferencia LOCAL de este navegador (localStorage; la lee static/js/theme.js en todas las pantallas). Mismas claves de siempre.
   - «sesion» (solo admin): interruptor «Sesión única» → PUT /api/settings/single-session (app/routers/print_stations.py).
   «Restablecer» actúa al instante (no es edición pendiente). */
(function () {
  'use strict';
  const DEFAULT_COLOR = '#D4AF37';
  const colorInput = document.getElementById('themeColor');
  const fontsSelect = window.gwFontsSelect;
  if (!colorInput || !fontsSelect) return;
  Object.defineProperty(fontsSelect, 'value', { get: () => fontsSelect.get(), set: (v) => fontsSelect.set(v) });
  colorInput.value = DEFAULT_COLOR;
  if (window.goldenEnsureFontLink) window.goldenEnsureFontLink();          // las fuentes alojadas se cargan de una vez para que cada opción se vea en la suya

  try {
    const savedColor = localStorage.getItem('golden_theme_primary');
    if (savedColor) colorInput.value = savedColor;
    const savedFont = localStorage.getItem('golden_theme_font_family');
    if (savedFont) fontsSelect.value = savedFont;
  } catch (e) { /* sin almacenamiento: queda el valor por defecto */ }

  function applyAppearance() {
    try {
      localStorage.setItem('golden_theme_primary', colorInput.value);
      document.documentElement.style.setProperty('--golden-primary', colorInput.value);
      // El mismo color también pinta el fondo del menú lateral (pedido explícito, ronda 2).
      document.documentElement.style.setProperty('--golden-sidebar-bg', colorInput.value);
      // Contraste automático (2026-09-17, pedido explícito): el texto de botones/menú se recalcula según qué tan clara/oscura sea la elegida.
      const contrast = window.goldenContrastColor ? window.goldenContrastColor(colorInput.value) : '#000000';
      document.documentElement.style.setProperty('--golden-primary-contrast', contrast);
      document.documentElement.style.setProperty('--golden-sidebar-contrast', contrast);

      const family = fontsSelect.value;
      if (family) {
        localStorage.setItem('golden_theme_font_family', family);
        if (window.goldenEnsureFontLink) window.goldenEnsureFontLink();
        const value = `'${family}', sans-serif`;
        document.documentElement.style.setProperty('--font-heading-primary', value);
        document.documentElement.style.setProperty('--font-heading-secondary', value);
        document.documentElement.style.setProperty('--font-body', value);
      } else {
        localStorage.removeItem('golden_theme_font_family');
        document.documentElement.style.removeProperty('--font-heading-primary');
        document.documentElement.style.removeProperty('--font-heading-secondary');
        document.documentElement.style.removeProperty('--font-body');
      }
    } catch (e) {
      throw new Error('No se pudo guardar la preferencia (¿ventana privada?)');
    }
  }

  GWParams.register({ key: 'apariencia', label: 'Apariencia', order: 10, save: async () => applyAppearance() });

  document.getElementById('resetThemeBtn').addEventListener('click', () => {
    try {
      localStorage.removeItem('golden_theme_primary');
      localStorage.removeItem('golden_theme_font_family');
    } catch (e) { /* sin almacenamiento */ }
    ['--golden-primary', '--golden-sidebar-bg', '--golden-primary-contrast', '--golden-sidebar-contrast', '--font-heading-primary', '--font-heading-secondary', '--font-body']
      .forEach((p) => document.documentElement.style.removeProperty(p));
    colorInput.value = DEFAULT_COLOR;
    fontsSelect.value = '';
    GWParams.markClean('apariencia');
    showToast('Apariencia restablecida', 'success');
  });

  /* ---------------------------------------------------------------- Sesión única (26-oct-2026, solo admin): app/routers/print_stations.py → app/sessions.py */
  const chk = document.getElementById('singleSessionChk');
  if (!chk) return;
  fetch('/api/settings/single-session', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).then((d) => {
    if (!d) return;
    chk.checked = !!d.enabled;
    document.getElementById('singleSessionNote').hidden = !d.forced_by_env;
    GWParams.markClean('sesion');
  }).catch(() => {});
  GWParams.register({
    key: 'sesion', label: 'Sesión única', order: 20,
    save: async () => {
      const res = await fetch('/api/settings/single-session', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: chk.checked }) });
      if (!res.ok) throw new Error('No se pudo cambiar la sesión única');
    },
  });
})();
