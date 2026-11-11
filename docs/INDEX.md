# Índice de `docs/` (0B, 2-nov-2026)

Qué es cada documento y cuál manda. Si un documento de producto (`00`–`06`) no coincide con el código, manda el código y `CLAUDE.md`.
Hay números repetidos (`00`, `13`, `18`, `20`, `21`, `22`) porque son documentos distintos de épocas distintas; **no se renumeran** para no romper enlaces,
runbooks ni los espejos del proyecto de Claude. Abajo dice cuál es cuál.

## Para retomar el trabajo
| Documento | Para qué |
|---|---|
| [`HANDOFF.md`](HANDOFF.md) | Relevo de la migración a Cloud Run + Neon |
| [`historial.md`](historial.md) | Detalle por sprint: porqués, bugs reales y arreglos |
| [`HANDOFF_IMPRESION_COMPARTIDA_29OCT.md`](HANDOFF_IMPRESION_COMPARTIDA_29OCT.md) | Relevo de impresión/sesión del 29-oct |
| [`ux/ESTANDARES_VISUALES.md`](ux/ESTANDARES_VISUALES.md) | **Regla única de diseño: todo lo visual se hace así** |
| [`IMPRESION_PARAMETROS_INAMOVIBLES.md`](IMPRESION_PARAMETROS_INAMOVIBLES.md) | **Parámetros de impresión fijados en hardware. No cambiar sin orden expresa.** |

## Producto (los mantiene otra sesión)
`00_README.md` (índice de esta serie), `00_REQUERIMIENTOS_ROADMAP.md`, `01_VISION_Y_ALCANCE.md`, `02_CLASIFICACION_FURPS.md`, `03_PRODUCT_BACKLOG.md`, `04_ARQUITECTURA.md`, `05_MODELO_DATOS.md`, `06_BRIEF_SPRINT_1.md`.

## Arquitectura, migración y operación
| Documento | Contenido |
|---|---|
| [`13_ARQUITECTURA_ESCALABILIDAD.md`](13_ARQUITECTURA_ESCALABILIDAD.md) | Plan de arquitectura para picos de carga (el «13» de arquitectura) |
| [`13_RUNBOOK_PRODUCCION.md`](13_RUNBOOK_PRODUCCION.md) | Runbook del paso a producción del 28-oct (el «13» de operación; histórico) |
| [`14_FASE0_RESULTADOS.md`](14_FASE0_RESULTADOS.md) | Resultados de carga y reconocimiento facial |
| [`15_MIGRACION.md`](15_MIGRACION.md) | Progreso y decisiones de la migración |
| [`16_BACKLOG_PRODUCTO.md`](16_BACKLOG_PRODUCTO.md) | Lo que falta construir (decidido con Juan David) |
| [`17_SERVIDOR_LOCAL.md`](17_SERVIDOR_LOCAL.md) | Servidor local sin internet (diseño) |
| [`18_EVENTO_CAMPOS_ESTADOS.md`](18_EVENTO_CAMPOS_ESTADOS.md) | Ficha configurable, estados con reglas e inventario (el «18» de eventos; diseño) |
| [`18_EXPORTAR_EVENTOS.md`](18_EXPORTAR_EVENTOS.md) | Exportar/importar eventos entre entornos (el «18» de exportación) |
| [`19_GUIA_PRODUCCION.md`](19_GUIA_PRODUCCION.md) | **Guía vigente para poner producción en Cloud Run** |
| [`EVENTOS_EN_CURSO_LANZAMIENTO.md`](EVENTOS_EN_CURSO_LANZAMIENTO.md) | Lanzamiento y reversa de «eventos en curso» (migración 0077) |
| [`observabilidad.md`](observabilidad.md) · [`recuperacion_desastre.md`](recuperacion_desastre.md) · [`runbook_evento.md`](runbook_evento.md) | Salud/logs, recuperación ante desastre, qué revisar en una noche grande |
| [`investigaciones_reunion_2026-09-21.md`](investigaciones_reunion_2026-09-21.md) | Investigaciones puntuales (histórico) |

## Etapa «después del piloto» (Fases 5 a 9, rama `f5/integracion`, sin desplegar al 9-nov-2026)
| Documento | Contenido |
|---|---|
| [`29_PLAN_MAESTRO_ETAPA_2026-10-29.md`](29_PLAN_MAESTRO_ETAPA_2026-10-29.md) | Plan maestro de la etapa (fases, «listo cuando») |
| [`REVISION_F5-9_PLAN_VS_CODIGO.md`](REVISION_F5-9_PLAN_VS_CODIGO.md) | **Lo planeado contra lo construido (revisión 9-nov)** |
| [`seguridad/F5-9_RESUMEN.md`](seguridad/F5-9_RESUMEN.md) | **Ronda de seguridad de las Fases 5–9** (y los cinco informes `seguridad/F5-9_*.md`) |
| [`ux/REVISION_VISUAL_F5-9.md`](ux/REVISION_VISUAL_F5-9.md) | Revisión visual de las pantallas nuevas |
| Fase 5 · eventos | `FASE_5_DECISIONES.md`, `FASE_5_FACTURADO.md`, `FASE_5_ENTREGA_ENCUESTA.md`, `FASE_5_HISTORIAL.md`, `FASE_5_INVENTARIO.md`, `FASE_5_JORNADA.md`, `FASE_5_NOTIFICACIONES.md` |
| Fase 6 · sin red | `FASE_6_SERVIDOR_LOCAL.md` (estado y decisiones), `17_SERVIDOR_LOCAL.md` (diseño) |
| Fase 7 · cliente | `20_URL_LIMPIA_INSCRIPCIONES.md` (el «20» de inscripciones) |
| Fase 8 · vanguardia | `FASE_8_PANTALLA_TV.md`, `FASE_8_TURNOS.md`, `FASE_8_AUTORREGISTRO_KIOSCO.md`, `21_QR_DINAMICO_WALLET.md` (el «21» de QR), `22_CONTACTOS_EXPOSITORES.md` (el «22» de expositores), `23_COBROS_WOMPI_MULTICUENTA.md` |
| Fase 9 · plataforma | `FASE_9_PLATAFORMA.md`, `24_COPIA_SEMANAL_ONEDRIVE.md` |
| Fase 10 · ajustes 10-nov | `FASE_10_AJUSTES_NOV10.md`, `EXPLICACION_SERVIDOR_LOCAL_SIMPLE.md` |
| Otros «20–22» (Fases 3–4) | `20_CUENTAS_POR_SERVICIO.md`, `20_FORM_YA_INSCRITO.md`, `21_ESTADISTICAS_FORMULARIO_Y_CLIENTE.md`, `22_SESION_INACTIVIDAD.md` |

## Legal, UX y otros
- [`legal/`](legal/): textos de la auditora, política de privacidad, decisiones y pendientes (empezar por `DECISIONES_Y_PENDIENTES.md`). Los textos legales son literales y no se editan.
- [`ux/`](ux/): análisis de flujo y UX, plan de la fase 1 visual, pendientes post-piloto.
- `comp_de_check.py.txt`: script de comprobación de impresión guardado como texto (histórico).
- **Cierre de las Fases 0 y 1 (5-nov-2026):** `CIERRE_FASES_0_1.md`.
- **Cierre de la Fase 4 — Equipo del evento (8-nov-2026):** `CIERRE_FASE_4.md` (+ `FASE_4_*.md`, `FASE_4_SEGURIDAD.md`). Ramas ya integradas y candidatas a borrar (con permiso): `4B_ramas_integradas_en_f4.txt` y `5_ramas_integradas_en_f5.txt` (9-nov).
- Fase 0A/0B: `0B_inventario.md`, `0B_ramas_borradas.md` (+ lista) — limpieza del repositorio.
- **Fase 10 — Ajustes del 10-nov-2026:** `FASE_10_AJUSTES_NOV10.md` (una sección por bloque; el bloque D trae asteriscos configurables, prellenado del compromiso y Acta de novedades).
