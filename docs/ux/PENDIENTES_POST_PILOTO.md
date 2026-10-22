# Pendientes para después del piloto del 29 de octubre de 2026

Decisiones del dueño (17 y 21 de octubre de 2026). Nada de esto se hace antes del piloto sin una orden escrita de Juan David.

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
- **`producto/permisos-ops`** (orden del 21 oct): dejar en `deploy/gcp/bootstrap.sh`, para producción y staging, los dos permisos que en producción se aplicaron a mano el 21 de octubre:
  - `golden-ops` con `roles/cloudtasks.enqueuer` sobre la cola general `golden-jobs` (sin él, los reintentos que programa el Job horario fallan con 403: Hallazgo 4);
  - `golden-ops` con `roles/iam.serviceAccountUser` sobre `golden-app` (sin él, el precalentamiento no puede cambiar las instancias mínimas: 403 del 21 oct).
  Revisar también si staging los necesita (mismas consultas de solo lectura del Hallazgo 1 y 4).
- **`favicon.ico` devuelve 404** en las páginas: agregar el ícono (o la ruta) para que no ensucie los registros.
- **Política v1.2:** borrador en `docs/legal/BORRADOR_POLITICA_v1.2.md`; espera a la auditora (incluye la decisión del botón «Translate», arriba).
- **`producto/codigo-en-ruta`** (Parte B, rutas ADITIVAS `/e/<código>/…` solo para páginas de gestión, sin tocar la puerta): solo entra antes del piloto si el dueño lo decide el viernes 23 por la tarde con la Parte A (`producto/codigo-protegido`) ya en staging; si no, va aquí. Informe con riesgos, pruebas y estimación (18 a 26 h) en la conversación del 21 de octubre.
