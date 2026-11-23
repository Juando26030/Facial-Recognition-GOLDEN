/* Configuración (templates/configuracion.html). Dos bloques que se guardan con la barra única (GWParams, static/js/params-save.js):
   - «apariencia»: preferencia LOCAL de este navegador (localStorage; la lee static/js/theme.js en todas las pantallas). Mismas claves de siempre.
   - «sesion» (solo admin): interruptor «Sesión única» → PUT /api/settings/single-session (app/routers/print_stations.py).
   - «guias» (todos): preferencia de la CUENTA «Deshabilitar demos automáticas» → PUT /api/me/tours-auto-off (antes se guardaba al marcar; ahora queda pendiente como lo demás).
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

  /* Guías automáticas: el casillero ya no lleva data-gw-tour-off (ese guarda al marcar, en gw-ui.js); aquí queda pendiente hasta «Guardar cambios». */
  const toursOff = document.getElementById('toursOff');
  if (toursOff) {
    GWParams.register({
      key: 'guias', label: 'Guías automáticas', order: 12,
      save: async () => {
        const res = await fetch('/api/me/tours-auto-off', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ off: toursOff.checked }) });
        if (!res.ok) throw new Error('No se pudo guardar la preferencia de las guías');
        window.GW_TOURS_OFF = toursOff.checked;
      },
    });
  }

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

  /* ---------------------------------------------------------------- Tamaño del logo de Golden (6-nov-2026, solo super admin): vale para todos → PUT /api/settings/golden-logo-height */
  const logoRange = document.getElementById('goldenLogoH');
  if (logoRange) {
    const out = document.getElementById('goldenLogoHv');
    logoRange.addEventListener('input', () => { out.textContent = logoRange.value; });
    fetch('/api/settings/golden-logo-height', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).then((d) => {
      if (!d) return;
      logoRange.value = d.height; out.textContent = d.height;
      GWParams.markClean('logosize');
    }).catch(() => {});
    GWParams.register({
      key: 'logosize', label: 'Tamaño del logo de Golden', order: 15,
      save: async () => {
        const res = await fetch('/api/settings/golden-logo-height', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ height: Number(logoRange.value) }) });
        if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || 'No se pudo guardar el tamaño del logo'); }
        document.querySelectorAll('.golden-logo img').forEach((img) => { if (img.getAttribute('style') && img.getAttribute('style').indexOf('--gw-logo-h') >= 0) img.style.setProperty('--gw-logo-h', logoRange.value + 'px'); });
      },
    });
  }

  /* ---------------------------------------------------------------- Tiempo de sesión por defecto (20-nov-2026, admin y super admin): vale para todos → PUT /api/settings/session-minutes */
  const sessMin = document.getElementById('sessionMinutes');
  if (sessMin) {
    const now = document.getElementById('sessionMinutesNow');
    fetch('/api/settings/session-minutes', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).then((d) => {
      if (!d) return;
      sessMin.value = d.minutes; sessMin.min = d.min; sessMin.max = d.max; now.textContent = d.minutes;
      document.getElementById('sessionMinEnvNote').hidden = !d.forced_by_env;
      sessMin.disabled = !!d.forced_by_env;
      GWParams.markClean('sessionmin');
    }).catch(() => {});
    GWParams.register({
      key: 'sessionmin', label: 'Tiempo de sesión por defecto', order: 16,
      save: async () => {
        const n = Number(sessMin.value);
        if (!Number.isInteger(n) || n < Number(sessMin.min) || n > Number(sessMin.max)) throw new Error('Los minutos deben ser un número entero de ' + sessMin.min + ' a ' + sessMin.max);
        const res = await fetch('/api/settings/session-minutes', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ minutes: n }) });
        if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || 'No se pudo guardar el tiempo de sesión'); }
        now.textContent = n;
      },
    });
  }

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
