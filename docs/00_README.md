# `docs/` — índice de entrada (22-nov-2026)

Documentación técnica de Orum. Este archivo es **la puerta**: dice qué leer según lo que necesites y propone el orden en que `docs/` debería
quedar organizado. El índice exhaustivo por documento (con la explicación de los números repetidos) sigue en [`INDEX.md`](INDEX.md) hasta que se funda aquí.
Si un documento no coincide con el código, manda el código y `CLAUDE.md`.

## 1. Si tienes cinco minutos: qué leer y en qué orden
| Necesito… | Lee |
|---|---|
| Las reglas que no se discuten | [`REGLAS_INAMOVIBLES_Y_DECISIONES.md`](REGLAS_INAMOVIBLES_Y_DECISIONES.md) → [`REGLAS_Y_FORMA_DE_TRABAJO.md`](REGLAS_Y_FORMA_DE_TRABAJO.md) |
| Saber qué corre hoy y qué cambió | [`../CHANGELOG.md`](../CHANGELOG.md) → [`ESTADO_2026-11-11.md`](ESTADO_2026-11-11.md) (punto de retorno) → [`25_INVENTARIO_POR_BASE.md`](25_INVENTARIO_POR_BASE.md) §10-12 (último bloque) |
| Desplegar | [`19_GUIA_PRODUCCION.md`](19_GUIA_PRODUCCION.md) y [`../deploy/gcp/README.md`](../deploy/gcp/README.md) (antes de cualquier comando) |
| Entender la arquitectura | [`13_ARQUITECTURA_ESCALABILIDAD.md`](13_ARQUITECTURA_ESCALABILIDAD.md), [`15_MIGRACION.md`](15_MIGRACION.md), [`14_FASE0_RESULTADOS.md`](14_FASE0_RESULTADOS.md) |
| Tocar una pantalla | [`ux/ESTANDARES_VISUALES.md`](ux/ESTANDARES_VISUALES.md), [`ux/LECCIONES_VISUALES_NOV11.md`](ux/LECCIONES_VISUALES_NOV11.md), muestrario `ux/guia_visual.html` |
| Tocar impresión | [`IMPRESION_PARAMETROS_INAMOVIBLES.md`](IMPRESION_PARAMETROS_INAMOVIBLES.md) (no se cambia sin orden escrita) |
| Tocar biometría, consentimiento o textos legales | [`legal/DECISIONES_Y_PENDIENTES.md`](legal/DECISIONES_Y_PENDIENTES.md) y los textos de la auditora en `legal/` |
| Saber qué falta construir | [`16_BACKLOG_PRODUCTO.md`](16_BACKLOG_PRODUCTO.md) (ojo: el estado de varias piezas está viejo; ver `revision_2026-11-22/02_codigo_calidad_repo.md` §3) |
| El porqué de un arreglo viejo | [`historial.md`](historial.md) (hasta el 5-nov-2026) y los `CIERRE_*.md` / `FASE_*.md` |

## 2. Qué hay en cada carpeta (hoy)
| Carpeta | Contenido | Estado |
|---|---|---|
| `docs/` (raíz, 96 archivos) | Mezcla de reglas, estados, guías, diseños por pieza y cierres de fase. | Viva, pero sin orden: ver §3 |
| `crm/` | Reglas del módulo CRM, códigos, importador de SuiteCRM, guías de staging C1A-C4, SQL de verificación. | Vivo (módulo apagado en producción) |
| `legal/` | Textos literales de la auditora, política de privacidad v1.1 (+ huella), decisiones y pendientes, guías del corte H1 y runbooks. | Vivo; los textos no se editan |
| `ux/` | Estándares visuales, lecciones, revisiones visuales, pendientes, muestrario HTML, capturas de tipografías. | Vivo |
| `seguridad/` | Ronda de seguridad de las Fases 5-9 (resumen y cinco informes). | Histórico (9-nov) |
| `etapa/` | Estados y pendientes de las etapas 0A/1A. | Histórico (oct-nov) |
| `revision_2026-11-22/` | Revisión integral por roles (instrucciones comunes y un reporte por rol). | En curso |

## 3. Cómo debería quedar `docs/` (propuesta; nada se ha movido todavía)
El criterio: una persona nueva encuentra lo vigente en dos clics y lo histórico no estorba. Se mueven archivos, **no se reescriben**, y se deja un enlace en
`INDEX.md` por cada ruta vieja que citen `CLAUDE.md`, runbooks o el proyecto de Claude.

```
docs/
  00_README.md                      ← este índice (único punto de entrada; INDEX.md se funde aquí)
  reglas/                           ← lo que no se discute
    REGLAS_INAMOVIBLES_Y_DECISIONES.md · REGLAS_Y_FORMA_DE_TRABAJO.md · IMPRESION_PARAMETROS_INAMOVIBLES.md · COORDINADOR_TEMPORAL.md
  estado/                           ← UN solo estado vivo + puntos de retorno fechados
    ESTADO.md (vivo) · 2026-11-11_punto_de_retorno.md · HANDOFF.md (solo lo vigente; las capas «ESTADO ANTERIOR» van al CHANGELOG)
  arquitectura/                     ← cómo está hecho
    13_ARQUITECTURA_ESCALABILIDAD.md · 14_FASE0_RESULTADOS.md · 15_MIGRACION.md · 04_ARQUITECTURA.md · 05_MODELO_DATOS.md · observabilidad.md · SEGURIDAD_SESIONES.md
  operacion/                        ← cómo se despliega y se opera
    19_GUIA_PRODUCCION.md · 13_RUNBOOK_PRODUCCION.md · runbook_evento.md · recuperacion_desastre.md · 24_COPIA_SEMANAL_ONEDRIVE.md · PRUEBA_CARGA_PRODUCCION.md
    EVENTOS_EN_CURSO_LANZAMIENTO.md · PASO_A_PRODUCCION_2026-11-16.md · PASO_CRM_PRODUCCION_2026-11-16.md
  modulos/                          ← un documento vivo por pieza del producto (diseño + decisiones + estado)
    registro/ (18_EVENTO_CAMPOS_ESTADOS, COLOR_POR_EVENTO, ESCARAPELA_DIGITAL_DATOS, PRUEBA_LECTOR_CEDULA, 1B_reimpresion_permisos)
    formularios/ (20_FORM_YA_INSCRITO, 20_URL_LIMPIA_INSCRIPCIONES, 21_ESTADISTICAS_FORMULARIO_Y_CLIENTE, 23_COBROS_WOMPI_MULTICUENTA)
    inventario/ (25_INVENTARIO_POR_BASE, FASE_5_INVENTARIO) · almacen/ (ALMACEN) · crm/ (lo de hoy) · legalizaciones/
    servidor_local/ (17_SERVIDOR_LOCAL, 23_EVENTO_COMPARTIDO_NUBE, FASE_6_SERVIDOR_LOCAL, EXPLICACION_SERVIDOR_LOCAL_SIMPLE, 20_FIRMA_INSTALADOR, 18_EXPORTAR_EVENTOS)
    plataforma/ (FASE_9_PLATAFORMA, 20_CUENTAS_POR_SERVICIO, 22_SESION_INACTIVIDAD, 22_CONTACTOS_EXPOSITORES, 21_QR_DINAMICO_WALLET)
  producto/                         ← visión, backlog y decisiones de alcance
    16_BACKLOG_PRODUCTO.md (vivo, con el estado al día) · 00_REQUERIMIENTOS_ROADMAP · 01_VISION_Y_ALCANCE · 02_CLASIFICACION_FURPS · 03_PRODUCT_BACKLOG · 06_BRIEF_SPRINT_1 · FASE_2_ALCANCE
  ux/   legal/                      ← como están
  historico/                        ← cerrado; se conserva, no se mantiene
    historial.md · CIERRE_*.md · FASE_3_* · FASE_4_* · FASE_5_* · FASE_8_* · FASE_10_* · 0B_* · 0C_* · 0D_* · 4B_* · 5_* · etapa/ · seguridad/
    29_PLAN_MAESTRO_ETAPA · REVISION_F5-9_PLAN_VS_CODIGO · PLAN_PRUEBAS_COMPLETAS_F5-9 · HANDOFF_IMPRESION_COMPARTIDA_29OCT · investigaciones_reunion_2026-09-21
    PROMPT_SESION_NUEVA_2026-11-11 · comp_de_check.py.txt
  revisiones/                       ← auditorías fechadas (revision_2026-11-22/, ux/26_REVISION_VISUAL_2026-10-16, ux/REVISION_VISUAL_F5-9)
```
Reglas para que no se vuelva a desordenar: (1) un documento nuevo nace en la carpeta de su módulo, con fecha y estado en la primera línea; (2) los números
`NN_` dejan de usarse para documentos nuevos (ya hay seis repetidos: `00`, `13`, `18`, `20`, `21`, `22`, `23`); (3) lo que cierra va a `historico/` en el mismo
commit que lo cierra; (4) lo que el dueño debe leer se duplica en el proyecto de Claude (`claude/NN_…`), no al revés.

## 4. Documentos de producto (`00`–`06`)
Los mantiene la sesión de producto: `00_REQUERIMIENTOS_ROADMAP.md`, `01_VISION_Y_ALCANCE.md`, `02_CLASIFICACION_FURPS.md`, `03_PRODUCT_BACKLOG.md`
(trae la Definition of Ready/Done original), `04_ARQUITECTURA.md`, `05_MODELO_DATOS.md`, `06_BRIEF_SPRINT_1.md`. Están al 8-nov-2026 o antes; el estado real
de lo construido está en `CHANGELOG.md` y en `16_BACKLOG_PRODUCTO.md`.
