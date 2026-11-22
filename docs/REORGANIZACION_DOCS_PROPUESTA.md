# Reorganización de `docs/`: propuesta lista para ejecutar (22-nov-2026)

**Estado: PROPUESTA. Nada se ha movido.** La estructura es la de [`00_README.md`](00_README.md) §3; aquí está convertida en un script que se puede revisar antes de aplicar.

## Qué hace el script
`scripts/reorganizar_docs.sh` tiene dos modos:

| Orden | Qué hace |
|---|---|
| `bash scripts/reorganizar_docs.sh` | **Modo seco (por defecto).** Imprime los `git mv` que haría, cuántos enlaces corregiría y qué archivos habría que revisar a mano. No toca nada. |
| `bash scripts/reorganizar_docs.sh --aplicar` | Ejecuta los `git mv`, corrige los enlaces relativos de todos los `.md` (incluidos `CLAUDE.md`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`) y las menciones con ruta completa (`docs/15_MIGRACION.md` → `docs/arquitectura/15_MIGRACION.md`). **No hace commit.** |

Mueve archivos; no reescribe ninguno (solo cambia rutas dentro de los enlaces).

## Resultado del modo seco hoy (22-nov-2026)
- **99 movimientos** (`git mv`): 4 a `reglas/`, 2 a `estado/`, 7 a `arquitectura/`, 10 a `operacion/`, 25 a `modulos/` (incluida la carpeta `crm/`), 7 a `producto/`, 43 a `historico/` (incluidas `etapa/` y `seguridad/`) y `revision_2026-11-22/` a `revisiones/`.
- **Unos 400 enlaces y menciones en 74 archivos `.md`** se corrigen solos (406 en la última corrida; el número sube con cada documento nuevo).
- **Unos 144 archivos que no son `.md`** citan alguna ruta movida (comentarios en `app/`, migraciones, pruebas, scripts, dos flujos de GitHub). El script los **lista y no los toca**.
- Ensayo: se aplicó en una copia desechable del repositorio; los 128 enlaces Markdown relativos del repositorio siguieron resolviendo (0 rotos antes, 0 después).

## Adónde va cada cosa
| Carpeta | Qué recibe |
|---|---|
| `reglas/` | `REGLAS_INAMOVIBLES_Y_DECISIONES`, `REGLAS_Y_FORMA_DE_TRABAJO`, `IMPRESION_PARAMETROS_INAMOVIBLES`, `COORDINADOR_TEMPORAL` |
| `estado/` | `ESTADO_2026-11-11` (como `2026-11-11_punto_de_retorno.md`), `HANDOFF` |
| `arquitectura/` | `13_ARQUITECTURA_ESCALABILIDAD`, `14_FASE0_RESULTADOS`, `15_MIGRACION`, `04_ARQUITECTURA`, `05_MODELO_DATOS`, `observabilidad`, `SEGURIDAD_SESIONES` |
| `operacion/` | `19_GUIA_PRODUCCION`, `13_RUNBOOK_PRODUCCION`, `runbook_evento`, `recuperacion_desastre`, `24_COPIA_SEMANAL_ONEDRIVE`, `PRUEBA_CARGA_PRODUCCION`, `EVENTOS_EN_CURSO_LANZAMIENTO`, `PASO_A_PRODUCCION_2026-11-16`, `PASO_CRM_PRODUCCION_2026-11-16`, `26_SITIO_WEB_MONTAJE` |
| `modulos/registro/` | `18_EVENTO_CAMPOS_ESTADOS`, `COLOR_POR_EVENTO`, `ESCARAPELA_DIGITAL_DATOS`, `PRUEBA_LECTOR_CEDULA`, `PRUEBA_FISICA_AUTOIMPRESION`, `1B_reimpresion_permisos` |
| `modulos/formularios/` | `20_FORM_YA_INSCRITO`, `20_URL_LIMPIA_INSCRIPCIONES`, `21_ESTADISTICAS_FORMULARIO_Y_CLIENTE`, `23_COBROS_WOMPI_MULTICUENTA` |
| `modulos/inventario/`, `almacen/`, `crm/` | `25_INVENTARIO_POR_BASE`, `FASE_5_INVENTARIO` · `ALMACEN` · la carpeta `crm/` completa |
| `modulos/servidor_local/` | `17_SERVIDOR_LOCAL`, `23_EVENTO_COMPARTIDO_NUBE`, `FASE_6_SERVIDOR_LOCAL`, `EXPLICACION_SERVIDOR_LOCAL_SIMPLE`, `20_FIRMA_INSTALADOR`, `18_EXPORTAR_EVENTOS` |
| `modulos/plataforma/` | `FASE_9_PLATAFORMA`, `20_CUENTAS_POR_SERVICIO`, `22_SESION_INACTIVIDAD`, `22_CONTACTOS_EXPOSITORES`, `21_QR_DINAMICO_WALLET` |
| `producto/` | `16_BACKLOG_PRODUCTO`, `00_REQUERIMIENTOS_ROADMAP`, `01_VISION_Y_ALCANCE`, `02_CLASIFICACION_FURPS`, `03_PRODUCT_BACKLOG`, `06_BRIEF_SPRINT_1`, `FASE_2_ALCANCE` |
| `historico/` | `historial`, `CIERRE_*`, `FASE_3_*`, `FASE_4_*`, `FASE_5_*` (menos inventario), `FASE_8_*`, `FASE_10_*`, `0B_*`, `0C_*`, `0D_*`, `4B_*`, `5_*`, `etapa/`, `seguridad/`, `29_PLAN_MAESTRO_ETAPA`, `REVISION_F5-9_PLAN_VS_CODIGO`, `PLAN_PRUEBAS_COMPLETAS_F5-9`, `HANDOFF_IMPRESION_COMPARTIDA_29OCT`, `investigaciones_reunion_2026-09-21`, `PROMPT_SESION_NUEVA_2026-11-11`, `comp_de_check.py.txt` |
| `revisiones/` | `revision_2026-11-22/` |
| Se quedan | `00_README.md`, `INDEX.md`, `ux/`, `legal/`, y este archivo |

Dos decisiones que la propuesta original no decía y se tomaron aquí: `26_SITIO_WEB_MONTAJE` va a `operacion/` y `PRUEBA_FISICA_AUTOIMPRESION` a `modulos/registro/`. `modulos/legalizaciones/` no se crea porque hoy no hay documento propio. Las dos revisiones visuales que viven en `ux/` se quedan en `ux/`.

## Lo que el script NO hace (queda a mano)
1. **Los ~144 archivos que no son `.md`.** La mayoría son comentarios («ver docs/17_SERVIDOR_LOCAL.md») y no rompen nada, pero varias **pruebas leen documentos por su ruta** (por ejemplo las de impresión y las de textos legales): esas fallarán hasta corregir la ruta. Hay que correr la suite completa después de aplicar.
2. **Las formas cortas** (`docs/15`, `docs/13 §4`): no son rutas, no se tocan.
3. **Fundir `INDEX.md` en `00_README.md`** y dejar ahí un enlace por cada ruta vieja.
4. **`TESTING.md`, `QA_HANDOFF.md` y `QA_HANDOFF_SPRINT_2_3.md`** de la raíz (a `docs/historico/`) y **`Golden Logo 25.PNG`**: el script solo trabaja dentro de `docs/`.
5. **El proyecto de Claude** (`claude/NN_…`) guarda copias con otros nombres: no depende de estas rutas, pero conviene avisar en la siguiente sesión.

## Riesgos y cuándo hacerlo
- Rompe los enlaces de **toda rama abierta** que edite `docs/`: hacerlo después de poner `main` al día (reporte 02 §4.1) y con las ramas de trabajo ya integradas.
- `docs/IMPRESION_PARAMETROS_INAMOVIBLES.md` y `docs/legal/` son intocables en contenido; aquí el primero solo cambia de carpeta y `legal/` no se mueve. Si se prefiere no mover el de impresión, se borra su renglón del mapa del script.
- Se deshace completo con `git reset --hard` (antes del commit) o `git revert` (después).

## Pasos para aplicarlo (cuando Juan David lo autorice)
1. Rama nueva desde la rama vigente, sin otros cambios: `git switch -c docs/reorganizar`.
2. `bash scripts/reorganizar_docs.sh` y leer la salida.
3. `bash scripts/reorganizar_docs.sh --aplicar`.
4. Corregir la lista «A MANO» (empezar por `tests/` y `.github/workflows/`), fundir `INDEX.md`.
5. `ruff check .` y `python -m pytest -q` completos; un solo commit; revisión.

Tiempo estimado: 3 horas, casi todas en el paso 4.
