-- SOLO LECTURA. Cuenta qué tipografías usan los diseños guardados. Devuelve nombres de fuentes y cantidades; no devuelve datos de personas.
-- Córrelo en el SQL Editor de Neon, proyecto/base de STAGING (no producción). Debes ver una tabla: origen | fuente | cantidad.
WITH usos AS (
  SELECT 'escarapela/certificado (evento)' AS origen, (regexp_matches(elements_json, '"(?:font_family|font)"\s*:\s*"([^"]+)"', 'g'))[1] AS fuente FROM badge_templates
  UNION ALL
  SELECT 'escarapela/certificado (biblioteca)', (regexp_matches(elements_json, '"(?:font_family|font)"\s*:\s*"([^"]+)"', 'g'))[1] FROM saved_badge_templates
  UNION ALL
  SELECT 'formulario público', (regexp_matches(design_json, '"font"\s*:\s*"([^"]+)"', 'g'))[1] FROM web_forms
  UNION ALL
  SELECT 'formulario (biblioteca)', (regexp_matches(design_json, '"font"\s*:\s*"([^"]+)"', 'g'))[1] FROM saved_form_templates
  UNION ALL
  SELECT 'ruleta', (regexp_matches(style_json, '"(?:font_family|title_font)"\s*:\s*"([^"]+)"', 'g'))[1] FROM roulette_configs WHERE style_json IS NOT NULL
)
SELECT origen, fuente, count(*) AS cantidad FROM usos GROUP BY origen, fuente ORDER BY origen, cantidad DESC;
