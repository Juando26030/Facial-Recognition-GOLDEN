# 14 · Gobierno del repositorio (plataforma/DevOps) — 22-nov-2026

Rol: ingeniero de plataforma/DevOps. Aplica lo que los reportes 01 (§4, órdenes 2, 4 y 7) y 02 (§4, §6, §8, §9) dejaron propuesto sobre el repositorio, **sin tocar la aplicación**.
Rama `saas/revision-integral`. Nada se ejecutó en la nube, nada se borró, ningún flujo de GitHub se disparó.

## 1. Resumen en 5 líneas
1. **Los escáneres de seguridad ya miran lo que de verdad se despliega:** `seguridad.yml` corre también en `feat/**`, `saas/**` y `hotfix/**` (antes solo `main`, que va 11 días atrás).
2. **Lo más grave que sigue abierto no es técnico:** `main` sigue atrasado respecto de producción y el despliegue diario sigue siendo a mano con la cuenta dueña. El flujo ya acepta ramas `feat/` y `saas/` para staging, pero falta **un comando de Juan David en Cloud Shell** (escrito en `docs/19`) para que Google las acepte.
3. **El repositorio pesa 57 MB menos por clon nuevo:** las 234 capturas de `scripts/visual_harness/out/` dejaron de versionarse (siguen en el disco y en el historial).
4. **Lo más valioso:** las dos limpiezas grandes (123 ramas, 99 documentos) quedaron como **scripts en modo seco** que se leen antes de ejecutar, con candados; decidir ya no exige confiar en una lista escrita a mano.
5. **Una sola versión de `ruff`** (0.16.9) en CI, pre-commit y el nuevo `requirements-dev.txt`; `CLAUDE.md` ya dice que producción es Cloud Run; el backlog marca lo construido.

## 2. Hallazgos
| # | Severidad | Qué pasa | Dónde | Por qué importa | Qué se hizo |
|---|---|---|---|---|---|
| 1 | Alta | Los escáneres (gitleaks, pip-audit, Bandit, Semgrep) solo corrían en `main`. | `.github/workflows/seguridad.yml` | Nada de lo desplegado desde el 11-nov había pasado por ellos. | **Corregido**: `push` en `main`, `feat/**`, `saas/**`, `hotfix/**`; `workflow_dispatch` ya existía; tope de 30 min por trabajo y cancelación de corridas repetidas de la misma rama. |
| 2 | Alta | Staging por Actions solo desde `migra/fase1-2` (rama muerta). El vínculo de Workload Identity compara la rama **exacta**: no admite `feat/*`, así que cambiar `DEPLOY_REF` no alcanza. | `cloudrun.yml`, `deploy/gcp/config.sh:25`, `bootstrap.sh:121` | Staging se despliega a mano, con la cuenta dueña y sin pruebas. | **Corregido en el flujo, pendiente en la nube**: staging acepta `feat/**` y `saas/**` **a mano** (Run workflow); comando exacto en `docs/19` § «Staging por GitHub Actions desde ramas feat/ y saas/». |
| 3 | Media | Decisión propia: staging desde `feat/`/`saas/` es **a mano, no por push** (el reporte 01 proponía push). | `cloudrun.yml` | Hay un solo staging y muchas ramas `feat/`: por push se pisarían, gastarían minutos y darían corridas rojas hasta que se corra el comando de la nube. | **Corregido** así; pasar a push es cambiar una línea si Juan David lo prefiere. |
| 4 | Media | `ruff` sin versión en CI y `v0.8.6` en pre-commit (tres versiones distintas). | `ci.yml`, `.pre-commit-config.yaml` | «En mi equipo pasa.» | **Corregido**: `0.16.9` en los tres sitios (la que da «All checks passed!» hoy). `diag.yml` no instala ruff. |
| 5 | Media | No había `requirements-dev.txt`. | raíz | Un desarrollador nuevo adivinaba qué instalar. | **Corregido** (pytest 9.1.1, PyYAML 6.0.3, ruff 0.16.9, playwright 1.63.0 fijos; httpx, pre-commit, pip-audit y bandit **sin fijar**: no estaban instalados aquí ni había red para comprobar la versión). El CI **no** lo usa todavía. |
| 6 | Media | Acciones de GitHub por etiqueta (`@v7`, `@v4`…), no por SHA. | todos los flujos | Una etiqueta movida cambia lo que corre sin cambiar el repositorio. | **Pendiente, a propósito**: no conozco con certeza los SHA de estas versiones (`checkout@v7`, `setup-python@v7`, `build-push-action@v7`…) y sin red no se pueden verificar; un SHA inventado rompe todos los flujos. Plan en §4. |
| 7 | Baja | 234 PNG (57 MB) versionados como salida de una herramienta. | `scripts/visual_harness/out/` | Cada clon los baja; crecen sin tope. | **Corregido**: fuera del índice, regla en `.gitignore`, `README.md` en la carpeta. Ninguna prueba los lee (solo `pages.py` y `mocks.py`, que no se tocaron). |
| 8 | Baja | `Golden Logo 25.PNG` (1 MB) en la raíz. | raíz | Peso menor. | **No se tocó**: **no** es idéntico a `static/img/logo-golden.png` (huellas distintas) y está fuera de mi área. Decide Juan David si se conserva el original. |
| 9 | Media | `CLAUDE.md` decía que producción era la VM. | `CLAUDE.md` § Infraestructura | Es lo primero que lee cada agente. | **Corregido** (solo esa sección; ahora «Infraestructura: hoy y heredado»). |
| 10 | Media | Backlog al 5-oct con piezas ya construidas marcadas «☐». | `docs/16_BACKLOG_PRODUCTO.md` | El dueño decidía con datos viejos. | **Corregido**: B1, B1b, B3, B3a, B3b, B4, B5, B6, N1, N1b, N1c, N3, N4 marcadas con fecha y documento; el estado anterior quedó al lado («Decía: …»); nota de qué sigue pendiente. Sin sección SaaS. |
| 11 | Alta | 136 ramas remotas. | GitHub | Nadie sabe de dónde cortar. | **Propuesto**: `scripts/limpiar_ramas_2026-11-22.sh` (123 ramas, grupos A/B/C1/C2/D). Nada borrado. |
| 12 | Media | 96 documentos en la raíz de `docs/`. | `docs/` | Lo vigente y lo muerto pesan igual. | **Propuesto**: `scripts/reorganizar_docs.sh` + `docs/REORGANIZACION_DOCS_PROPUESTA.md`. Nada movido. |
| 13 | Media | `docs/historial.md` terminaba el 5-nov. | `docs/historial.md` | Hueco de 17 días. | **Corregido**: resumen 5 al 22-nov al final, tomado de `CHANGELOG.md`. |

## 3. Qué se cambió
| Archivo | Qué hace el cambio |
|---|---|
| `.github/workflows/seguridad.yml` | Corre en `main`, `feat/**`, `saas/**`, `hotfix/**`; `timeout-minutes: 30`; `concurrency` (nunca cancela en `main`). |
| `.github/workflows/cloudrun.yml` | El trabajo `staging` corre también por `workflow_dispatch` desde `feat/` o `saas/`; `concurrency: cloudrun-staging` (uno a la vez). La lista de `push` y la condición de producción **no cambiaron**. |
| `.github/workflows/ci.yml` | `pip install ruff==0.16.9`. |
| `.pre-commit-config.yaml` | `rev: v0.16.9`. |
| `requirements-dev.txt` (nuevo) | Herramientas de desarrollo y pruebas. |
| `.gitignore`, `scripts/visual_harness/out/` | 234 PNG fuera del índice (`git rm -r --cached`); `README.md` que explica que son salidas. |
| `CLAUDE.md` | Solo la sección de infraestructura. |
| `docs/16_BACKLOG_PRODUCTO.md` | 13 estados actualizados y nota del 22-nov. |
| `docs/19_GUIA_PRODUCCION.md` | Sección nueva con el comando de Workload Identity, comprobación, cuidados y vuelta atrás. |
| `docs/historial.md` | Resumen 5 al 22-nov al final. |
| `docs/REORGANIZACION_DOCS_PROPUESTA.md`, `scripts/reorganizar_docs.sh` (nuevos) | Mapa de 99 movimientos; modo seco por defecto, `--aplicar` mueve y corrige enlaces de los `.md`. |
| `scripts/limpiar_ramas_2026-11-22.sh` (nuevo) | Lista por defecto; `--ejecutar` pide escribir «BORRAR <grupo>» por grupo. Orden por rama: etiqueta `archivo/<rama>` → subirla → comprobar que quedó en GitHub → borrar. No toca una rama que cambió de commit desde la revisión ni las 13 protegidas. |
| **`tests/test_cutover_workflows.py` (fuera de mi área, aviso)** | Una afirmación comparaba el `if` de staging con el texto exacto anterior: sin ajustarla, la prueba que el encargo pide correr fallaba. Se cambió solo esa afirmación (ahora exige la condición nueva y la fila única de staging). Las pruebas de producción quedaron iguales. |

**Verificado:** YAML válido en los 8 flujos; `bash -n` en los dos scripts; `ruff check .` → «All checks passed!»; `tests/test_cutover_workflows.py`, `test_gcloud_env_vars.py`, `test_cobros_gastos_f10b_texto.py`, `test_crm_etapa_texto.py`, `test_crm_c4_texto.py`, `test_csp_trinquete.py` → **71 pasan**. Los 123 nombres y commits del script de ramas coinciden uno a uno con las referencias remotas locales. `reorganizar_docs.sh --aplicar` se ensayó en una copia desechable: 0 enlaces Markdown rotos antes y después.

## 4. Qué queda pendiente y por qué (en orden)
| Orden | Qué | Horas | Quién |
|---|---|---|---|
| 1 | Correr el comando de Workload Identity de `docs/19` en el proyecto de staging y lanzar una vez el flujo desde una rama `feat/`. | 15 min + una corrida | Juan David |
| 2 | Poner `main` al día (reporte 02 §4.1). Sin eso, `cloudrun.yml` de producción sigue sin usarse. | 2 h + autorización | Juan David + Claude |
| 3 | `bash scripts/limpiar_ramas_2026-11-22.sh --ejecutar A B` (33 ramas sin riesgo); C1 tras revisar las que tienen commits propios; C2 y D después del paso 2. | 1,5 h | Juan David |
| 4 | Fijar acciones por SHA: con red, `gh api repos/<dueño>/<acción>/git/ref/tags/<versión>` por cada una, o activar Dependabot para `github-actions`, que escribe y mantiene los SHA. De paso unificar `setup-node@v4`→`v7`, `upload-artifact`, `setup-buildx@v3`→`v4`. | 2 h | Claude, con una corrida de prueba |
| 5 | Llevar el atributo `ref_group` a `bootstrap.sh` paso 4 (hoy solo está en `docs/19`); `deploy/gcp/*.sh` no era de mi área. | 1 h | Agente de `deploy/` |
| 6 | Fijar las 4 herramientas sin versión de `requirements-dev.txt` y hacer que el CI instale desde ese archivo. | 30 min | Claude |
| 7 | Reordenar `docs/` con el script, al final y sin otras ramas abiertas (≈144 archivos no `.md` por revisar a mano). | 3 h | Claude, con autorización |

## 5. Qué NO se pudo comprobar
- **Ningún flujo de GitHub se ejecutó.** `seguridad.yml` en ramas `feat/` puede salir rojo la primera vez (gitleaks y Bandit ALTA bloquean): eso sería un hallazgo real, no un fallo del cambio.
- **El comando de Workload Identity no se probó contra Google.** La expresión del atributo sigue la sintaxis documentada, pero no hubo nube ni red para confirmarlo. Si `update-oidc` la rechaza, no cambia nada.
- **Si el Environment `staging` de GitHub restringe ramas**: no se ve desde aquí.
- **Los SHA de las acciones** y las versiones vigentes de httpx, pre-commit, pip-audit y bandit.
- **La suite completa**: sin `fastapi`/`sqlalchemy`/Postgres aquí. `test_instalador_windows.py` y `test_ajustes_sabado17.py` (leen flujos que no toqué) no cargan por esa razón.
- **Que las ramas remotas sigan en el mismo commit en GitHub**: se comparó contra las referencias locales; el script lo vuelve a comprobar con `git fetch` al ejecutar.

## 6. Consejo en corto y veredicto
- **Contrario:** más escáneres en más ramas son más correos rojos; si nadie los lee, no cambió nada.
- **Primeros principios:** lo que se despliega debe ser lo que se revisó; hoy ya se revisa la rama, falta que la despliegue la máquina y no la cuenta dueña.
- **Expansionista:** con Dependabot para acciones y `pip`, la cadena de suministro se mantiene sola y es un argumento de venta del SaaS.
- **Forastero:** dos scripts que por defecto no hacen nada son la forma correcta de pedirle una decisión a un dueño no técnico.
- **Ejecutor:** esta semana, comando de `docs/19` (15 min) y grupos A y B de ramas (33 ramas, sin riesgo).

**Veredicto:** el gobierno del repositorio quedó preparado; lo que falta son decisiones, no trabajo. **Siguiente paso:** Juan David corre en Cloud Shell el comando de `docs/19` § «Staging por GitHub Actions desde ramas feat/ y saas/» y lanza el flujo una vez desde la rama de trabajo.
