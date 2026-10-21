# Pendientes de terceros y de tipografía (después del piloto del 29 de octubre)

Decisiones del dueño, 17 oct 2026.

## Scripts de terceros que se siguen pidiendo a `cdnjs.cloudflare.com` (solo pantallas del PERSONAL)
| Script | Pantallas |
|---|---|
| JSZip 3.10.1 | certificados (diseñador), carga de lista (roster) |
| Chart.js 4.5.1 | estadísticas, editor de formulario |
| SheetJS (xlsx) 0.18.5 | carga de lista (roster) |

Cerrado antes del piloto (alojado en `static/vendor/` con su licencia): `qrcode-generator` 1.4.4, JsBarcode 3.12.3, html2canvas 1.4.1 y jsPDF 2.5.1. Las páginas de los asistentes (`/b/<token>`, certificado público, formulario público, `/aceptar`, ruleta) ya no piden ningún script ni fuente a terceros, salvo el botón «Translate» (abajo). `tests/test_fuentes_propias.py` falla si aparece un script o una fuente externa nueva fuera de esta lista.

## Para la política v1.2
- **Botón «Translate» del formulario público** (`templates/form_public.html`): al pulsarlo carga `translate.google.com/translate_a/element.js` y le entrega la IP de la persona a Google. El texto del banner ya lo dice («Google puede guardar las suyas»). Decidir en la política v1.2 si se deja, se avisa de otra forma o se quita.

## Para después del piloto
- **Tema por defecto de formularios nuevos** (`app/formlib.py`, `DEFAULT_THEME["font"] = "Montserrat"`): el dueño pidió que Agrandir sea la fuente por defecto de toda la app; los formularios NUEVOS siguen naciendo en Montserrat. Cambiarlo toca lógica de la aplicación, por eso se deja. Los formularios ya guardados no cambian.
- **Licencia web de Agrandir:** la gestiona el dueño con el proveedor; ver `docs/legal/LICENCIA_AGRANDIR.md`.
