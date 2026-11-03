# 0B · Inventario de solo lectura (2-nov-2026)
Base: `main` = 874ab1b. Nada de esto cambió código ni ramas; es la lista para que Juan David apruebe qué se borra.
## 1. Resumen
| Tema | Resultado |
|---|---|
| `ruff` sobre TODO el repo | 1 aviso: variable sin usar `keep_id` en `alembic/versions/0017_staff_phone_unique.py:35` (migración antigua; no se toca, se ignora en la configuración). |
| Plantillas, JS y CSS sin referencias | Ninguno. |
| Secretos en TODO el historial (todas las ramas) | **Ninguno real.** Solo valores de ejemplo (`usuario:password`, `postgres:postgres`, `cambia-esto…`). Los únicos archivos tipo `.env` versionados son `.env.example` y `.env.staging.example`. Búsqueda propia con patrones (llaves privadas, AWS, GitHub, Google, Wompi, URLs con clave); `gitleaks` no estaba disponible: se recomienda correrlo en el CI (Fase 0C). |
| Código muerto (funciones/clases sin ninguna otra referencia) | 15 candidatas de 961 (sección 3). **Todas por verificar a mano:** el método es aproximado y `_stamp_finalized` / `_stamp_face_captured` salieron como candidatas pero son escuchas de eventos de SQLAlchemy (retención biométrica): NO son código muerto. |
| Binarios en el repo | `Golden Logo 25.PNG` (1 MB, en la raíz; solo lo cita `docs/15_MIGRACION.md`), `static/img/logo-golden.png`, capturas en `docs/ux/capturas_fuentes/` (5 PNG), `static/templates/plantilla_carga_base_asistentes.xlsx` (plantilla en uso). Peso total del repo: 12 MB de archivos, 23 MB de `.git`. |
| Documentos duplicados por número | `00_README`/`00_REQUERIMIENTOS_ROADMAP`, `13_ARQUITECTURA_ESCALABILIDAD`/`13_RUNBOOK_PRODUCCION`, `18_EVENTO_CAMPOS_ESTADOS`/`18_EXPORTAR_EVENTOS`. Son documentos distintos con el mismo número: se renumeran, no se borran. `docs/comp_de_check.py.txt` es un script suelto guardado como texto. |
| Dependencias | `requirements.txt` fija todo (incluidas transitivas); ninguna sale claramente sobrante. Revisar con `pip-audit` en 0C. |

## 2. Ramas (87 remotas; solo hay 1 etiqueta: `pre-formularios-bc4a19d`)
**A. Ya fusionadas en `main` (0 commits propios): 74.** Seguras de borrar después de dejar una etiqueta de archivo por rama.

`cand28`, `candidato/formularios-p1`, `candidato/produccion-28oct`, `candidato/produccion-29oct`, `corte/main`, `docs/correo-rbac`, `docs/correo-rbac-v2`, `docs/h1-guias`, `fix/cupos-sin-tope-30`, `fix/impresion-compartida-29oct`, `fix/impresion-horizontal`, `fix/legal-1-0`, `integracion/piloto-legal`, `integracion/staging-ajustes`, `integracion/staging-final-24oct`, `integracion/staging-impresion`, `migra/fase1-2`, `perf/fase0-carga`, `producto/aceptar-mejoras`, `producto/ajustes-puerta`, `producto/ajustes-sabado17`, `producto/arreglo-corte`, `producto/arreglos-impresion`, `producto/b1-entrar-rostro`, `producto/b2d-prueba-vida`, `producto/bootstrap-iam-reintentos`, `producto/carga-avance-inmediato`, `producto/carga-base-titulos`, `producto/carga-por-pasos`, `producto/codigo-protegido`, `producto/config-impresion-puesto`, `producto/directorio-touch-dos-filas`, `producto/editor-manijas-y-prioridad`, `producto/enlace-personal`, `producto/envio-enlaces`, `producto/escarapela-editor-pro`, `producto/escarapela-mayusculas`, `producto/escarapela-texto-ajuste`, `producto/estados-evento`, `producto/exportar-evento`, `producto/exportar-formulario`, `producto/fase0-ux`, `producto/fecha-en-carga`, `producto/formularios-ajustes`, `producto/fuentes-propias`, `producto/grupo-a`, `producto/grupo-b`, `producto/guia-h1-bloque2`, `producto/hotfix-kiosk`, `producto/impresion-controlador-siempre`, `producto/impresion-domingo`, `producto/impresion-plantilla-fresca`, `producto/impresion-por-controlador`, `producto/impresion-prefs-espejo`, `producto/impresion-rotados-completos`, `producto/impresora-conectar`, `producto/legal-piloto`, `producto/neon-role-base-vacia`, `producto/nombre-reporte`, `producto/piloto`, `producto/plantilla-carga`, `producto/politica-produccion`, `producto/produccion-manual`, `producto/puerta-sin-red`, `producto/puesto-reclamo`, `producto/puestos-sesiones`, `producto/rendimiento-reporte-carga`, `producto/row-accredit-determinista`, `producto/segunda-salida`, `producto/segunda-salida-v2`, `producto/sin-biometria`, `producto/test-minors-estable`, `producto/trabajos-huerfanos`, `sprint5/ruleta-formularios`

**B. Con commits que `main` no tiene: 13.** No se borran sin revisar. Propuesta:

| Rama | Commits únicos | Último | Propuesta |
|---|---|---|---|
| `sprint2/reverify-fixes-and-badges` | 68 | 2026-09-16 | Abandonada (sept.); archivar con etiqueta. |
| `producto/impresion-ajustes` | 9 | 2026-10-24 | Impresión: revisar contra lo fijado antes de archivar. |
| `candidato/produccion-23oct` | 8 | 2026-10-23 | Histórico de producción; conservar (plantilla única en 0B). |
| `ux/fase1-visual` | 8 | 2026-10-18 | **Vigente:** se reutiliza en la Fase 2 (diseño). |
| `producto/impresion-compartida` | 6 | 2026-10-22 | Impresión: revisar contra lo fijado antes de archivar. |
| `docs/etapa-0a` | 4 | 2026-10-30 | Informes de 0A; integrar a `main` como documentos y luego archivar. |
| `candidato/produccion-25oct` | 3 | 2026-10-26 | Histórico de producción; conservar. |
| `fix/offline-recarga` | 3 | 2026-10-05 | Punto 27 «hecho sin integrar»; decidir integrar o archivar. |
| `producto/fecha-nacimiento-sin-rostro` | 2 | 2026-10-22 | Revisar (2 commits). |
| `archivo/corte-main-b5f861b` | 1 | 2026-10-05 | Ya es de archivo; conservar. |
| `fix/legal-1-1-borrador` | 1 | 2026-10-05 | **Vigente:** borrador del apartado 5-bis de la política (punto 39). No borrar. |
| `producto/constancia-puerta` | 1 | 2026-10-21 | Revisar (1 commit). |
| `producto/eventos-flujo` | 1 | 2026-11-02 | Trabajo de eventos reciente; revisar. |

Vigentes además de las anteriores: `main`, `migra/fase1-2` (4 detrás de main), `producto/formularios-ajustes`, `candidato/formularios-p1` (pista de formularios, ya en producción).

## 3. Candidatas a código muerto (verificar una por una antes de borrar)

`app/auth.py:require_super_admin`, `app/consent_receipt.py:run_receipt`, `app/enroll.py:run_enroll`, `app/faces.py:read_match_token`, `app/faces_version.py:_collect`, `app/formsvc.py:has_confirmed_sid` y `_form_feed_job`, `app/models.py:PrivacyRequestCounter`, `app/reconcile.py:_reconcile_job`, `app/roster_columns.py:merge_reports`, `app/routers/form_refunds.py:_row`, `app/routers/parametros.py:field_labels_for_event`, `app/storage.py:delete_many`.

Ojo: `run_enroll`, `run_receipt` y los `_*_job` son probablemente manejadores de la cola de trabajos (se registran por nombre); `PrivacyRequestCounter` es un modelo (tabla). Por regla de 0B (no tocar consentimiento ni biometría salvo movimientos mecánicos) esos se dejan. Los realmente candidatos son los helpers sueltos (`require_super_admin`, `has_confirmed_sid`, `merge_reports`, `field_labels_for_event`, `delete_many`, `read_match_token`).

## 4. Preguntas para Juan David (las de «Preguntas al iniciar» de 0B)

1. ¿Apruebas borrar las ramas del grupo A (con etiqueta de archivo previa)?
2. ¿Qué haces con las del grupo B? (propuesta en la tabla)
3. ¿La VM antigua (`golden-biometrics-prod`) ya se puede dar por cerrada? Mientras no, `deploy/` de la VM y `deploy.yml` se marcan como heredados y no se borran.
