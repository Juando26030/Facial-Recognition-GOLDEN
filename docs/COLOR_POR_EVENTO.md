# Color de marca por evento (migración 0098)

Igual que el logo (`logo_mode`/`logo_path`), cada evento puede tener su color: `events.brand_color` = `#rrggbb` o NULL (= el dorado general de Golden).

- **Dónde se elige:** Parámetros del evento, bloque «Logo del evento» (fieldset «Color de marca»: Color de Golden / Color propio + selector). Se guarda con el «Guardar» global (sección `logo`) vía `PUT /api/events/{id}/brand-color` (`{"color": "#rrggbb" | null}`), mismos roles que el logo; deja registro en `audit_actions` (`event_brand_color`).
- **Validación (servidor, `app/brandcolor.py`):** acepta `#rgb`/`#rrggbb` (normaliza a minúscula); el texto de los botones se elige solo (blanco o azul marino `#141c4d`) y se RECHAZA el color que no llegue a 4,5:1 con ninguno (400, en español). Un valor guardado que ya no sea válido se ignora (cae al de Golden).
- **Dónde se aplica:** páginas públicas del evento (`/aceptar/{code}`, `/f/{evento}/{slug}` y `/c/{token}`): el servidor inyecta un `<style>` con `--gw-gold-grad`, `--gw-gold-1/2`, `--gw-on-gold` (tokens del sistema de diseño) y `--gold`/`--on-gold` (hojas de las páginas públicas sueltas). Las hojas no llevan colores nuevos; solo `var(--gold, <el de siempre>)`.
- **No incluido (decisión):** las pantallas internas (kiosco) siguen con la marca de Golden; el diseño propio de cada formulario (`theme.accent` en `form-render.js`) sigue mandando dentro del formulario; la librería `saved_colors` es de pañoletas y no se mezcla (se podría ofrecer como atajo después).
- **Migración:** `0098_event_brand_color` (aditiva, reversible). `down_revision` temporal `0095_super_events_archive`; el integrador la reencadena.
- **Pruebas:** `tests/test_brand_color.py`.
