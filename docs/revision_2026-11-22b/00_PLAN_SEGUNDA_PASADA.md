# Plan de la segunda pasada (23-nov-2026) — para ejecutar en una sesión nueva

Rama: **`saas/revision-integral`**, último commit al escribir esto: `27d6cb4` (+ el de este plan).
Lo que manda: [`CLAUDE.md`](../../CLAUDE.md), [`docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md`](../REGLAS_INAMOVIBLES_Y_DECISIONES.md) y este plan.
Idioma de trabajo con Juan David: español, sin tecnicismos; una orden de consola por mensaje.

## 1. Dónde estamos (verificado el 23-nov)
| Cosa | Estado |
|---|---|
| Rama `saas/revision-integral` | Primera pasada + segundo lote (22-nov) terminados y empujados. |
| Staging (`goldenweb-staging`, `staging.golden-eventos.com`) | Corre `7938ef2`. Faltan `c69ebf4` (teléfono del sitio), `ef39264` (texto del error), `8f8cb59` (cableado de cotización) y `27d6cb4`. **Hay que redesplegar.** |
| Producción (`goldenweb-prod`) | Migración 0160. No se toca. |
| `main` | `db63a7f` = merge sin conflictos de `prod/llaves-escaner-2026-11-20`, `hotfix/subida-formulario-2026-11-21` y `feat/evento-compartido-nube`. Una sola cabeza Alembic (0160). |
| Ramas | 33 de los grupos A y B borradas con etiqueta `archivo/…`. Quedan los grupos C1, C2 y D (sin revisar). |
| Migraciones nuevas en la rama | 0162_organizations, 0163_local_nodes_tenant, 0164_accept_verify_photo (cabeza actual). |
| Pruebas | Solo corren aquí las de texto (`python3 -m pytest --noconftest`). **Ninguna prueba con base de datos ha corrido.** |
| Sitio web (repo `golden-sitio-web`, commit `6eb6b6a`) | Entrega como parche `deploy/sitio/parche/0001-montaje-golden-eventos.patch`. **Nunca se compiló.** No está en staging. |

## 2. Decisiones de Juan David ya tomadas (no volver a preguntar)
1. `/instalar` retirada (hecho). 2. Staging primero, suite de GitHub una sola vez al final.
3. Aislamiento entre clientes (`ENFORCE_STAFF_TENANT`, `ENFORCE_STAFF_EVENT_SCOPE`): probarlo en staging con un cliente ficticio.
4. Contacto oficial en todo lado (sitio y plataforma): el correo de soporte y el teléfono +57 318 098 1752 que están en `deploy/sitio/` (`sitio.json`) y en el pie legal de la plataforma. El área comercial **solo** recibe el formulario de cotización; su correo va únicamente en el secreto `quote-to-email` (nunca en el repo, en documentos ni publicado).
5. Tipografía: Poppins (OFL) en lugar de Agrandir (sin licencia); ya aplicada con `size-adjust`; falta compararla a ojo con el sitio real.
6. DNS: cada paso se ensaya primero en staging y se escribe uno por uno. Nunca se ejecuta un DNS sin su orden.
7. Propuesta financiera: ya escrita (`docs/PROPUESTA_FINANCIERA_SAAS_2026-11-22.md`); él la revisa luego. Los precios son propuesta.
8. BitLocker solo si es gratis (lo es: viene con Windows Pro). Script `proteger-disco.ps1` hecho, sin probar.
9. Deshabilitar una llave desde la nube debe además **desinstalar y borrar** el servidor local (hecho: `autodestruir.ps1`; sin probar en Windows).
10. Borradores de IA/privacidad: ya enviados a Juan David por correo; **no se publica nada** hasta que opine la auditora.
11. «Foto pendiente» en `/aceptar`: configurable por evento, ambos flujos disponibles (hecho, migración 0164, activa por defecto).
12. Plazo de gracia del servidor local: implementado (`LOCAL_GRACE_DAYS=14`).
13. Campana: los digitadores no la tienen; la tienen todos los usuarios salvo los temporales. Se deja como mitigada.
14. Pruebas de extremo a extremo (Playwright) solo contra staging: construidas (`tests/e2e/`), sin correr.
15. `main` al día: hecho, prioridad cumplida.

## 3. Autorizaciones y límites de esta pasada
**Juan David autorizó (23-nov):** usar su computador y el navegador integrado para hacer clics y acciones por mi cuenta; acceder a lo que haga falta.
**Siguen siendo límites duros** (reglas de seguridad y de `CLAUDE.md`; no los levanta ninguna autorización general):
- **Producción:** ningún despliegue, migración, DNS ni prueba contra ella sin su «sí» explícito para ESA acción. Nada a `main` ni merges sin su «sí» para esa acción.
- Contraseñas, códigos de verificación, CAPTCHA, tarjetas, claves: **nunca los escribo yo**. Si hay que iniciar sesión, él lo hace en el navegador integrado (la sesión queda guardada) y yo sigo desde ahí.
- La ventana «Authorize Cloud Shell» y cualquier permiso nuevo sobre sus credenciales de Google: la aprueba él. Si lo hace, puedo correr los comandos de **staging** (`goldenweb-staging`); producción no.
- No crear recursos de nube nuevos sin avisarle (los crea él, salvo el sitio de Hosting de staging, aprobado en este plan).
- Secretos y correos del área comercial nunca en el repo ni en el chat (solo nombres de variables). Lectura a ciegas (`read -rsp`) para crearlos.
- Sin datos personales reales en logs, commits ni reportes. Resultados solo agregados.
- Un commit + push por pieza terminada, con sus pruebas de texto pasando. Mensajes de commit con la atribución indicada por el sistema.
- Ramas: no borrar más sin su «sí» (grupos C1, C2, D).

## 4. Orden de ejecución
Cada fase termina con una línea de estado a Juan David. Si una fase falla, se corrige antes de seguir.

### Fase 0 — Arranque (10 min)
1. Leer `CLAUDE.md`, este plan, `docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md`, `docs/revision_2026-11-22/README.md`, `docs/PRUEBAS_STAGING_2026-11-23.md`.
2. `git fetch && git checkout saas/revision-integral && git pull && git log --oneline -1` (debe incluir `27d6cb4`).
3. Correr las pruebas de texto: `python3 -m pytest --noconftest -q tests/test_seguridad_correcciones_2026-11-22.py tests/test_quote_request_puro.py tests/test_foto_pendiente_puro.py tests/test_e2e_estructura.py tests/test_firebase_config.py tests/test_cutover_workflows.py`.
4. Crear la lista de tareas con las fases de abajo.

### Fase 1 — Redesplegar staging (necesita a Juan David una vez)
1. Pedirle que apruebe «Authorize Cloud Shell» **o** que pegue, de a uno por mensaje:
   - `cd ~/gw-hosting && git fetch origin && git checkout saas/revision-integral && git pull && git log --oneline -1`
   - `cd ~/gw-hosting && REGION=us-east4 CLOUDSDK_CORE_PROJECT=goldenweb-staging bash deploy/gcp/manual_deploy.sh staging goldenweb-staging`
   (Antes de dar el comando, releer `deploy/gcp/README.md`: formato exacto, `FORCE=1`, comprobar rama/commit.)
2. Verificar sin sesión desde el navegador integrado (fetch por JS; curl no llega a staging): `/health` 200, `/robots.txt`, `/login` con `noindex`, `/instalar` 404, cotización (honeypot 200; datos malos 400 con `errors`).
3. Confirmar que la migración 0164 corrió (el Job de migraciones de staging terminó bien).

### Fase 2 — Sitio web en staging (docs/26 Parte A0)
1. Crear el sitio de Hosting `golden-sitio-<número de proyecto de staging>`.
2. `bash deploy/sitio/deploy_sitio.sh goldenweb-staging` con `SITIO_LOCAL` apuntando a un clon de `golden-sitio-web` en Cloud Shell (aquí no compila: sin npm).
3. Revisión visual en el navegador integrado por anchos (320, 375, 768, 1024, 1440): Poppins vs sitio actual, menú, contacto oficial, formulario de cotización (envía y muestra «Recibimos su solicitud»; en staging no sale correo real).
4. Opcional, si Juan David lo pide: subdominio `sitio-staging.golden-eventos.com`; escribir **cada paso de DNS** en un mensaje aparte con qué esperar.
5. Si el sitio cambia, regenerar el parche (`deploy/sitio/rehacer_parche.sh abrir/guardar`).

### Fase 3 — Pruebas con sesión en staging
1. Pedir a Juan David que inicie sesión (super_admin de staging) en el navegador integrado. Yo no escribo contraseñas.
2. Recorrer `docs/PRUEBAS_STAGING_2026-11-23.md` secciones A, B, C, E, F con capturas y marcar resultado por prueba. D (servidor local) solo si hay un portátil de prueba: ahí le doy a él los pasos.
3. Prioridad: **C (foto pendiente)**, porque toca biometría y las purgas de 7 días.
4. Cada fallo: reproducir, corregir con prueba, commit + push, redesplegar staging.

### Fase 4 — Aislamiento entre clientes en staging
1. Crear en `/plataforma` una empresa ficticia y un usuario de esa empresa.
2. Encender `ENFORCE_STAFF_TENANT=1` y `ENFORCE_STAFF_EVENT_SCOPE=1` solo en staging (`deploy/gcp/config.sh`/env de staging, ver README).
3. Probar con la cuenta ficticia: no ve eventos, clientes, usuarios ni llaves de Golden; los 404/403 son correctos; Golden sigue viendo todo. Documentar resultado en `docs/revision_2026-11-22b/`.
4. Si hay filtraciones, listar rutas y corregir; lo grande (filtro por empresa en todas las consultas + RLS, 160-220 h) queda como plan exacto, no se improvisa.

### Fase 5 — Verificación independiente (agentes por rol, pocos a la vez)
Cada agente lee código (grep + rangos), **no** da por cierto lo que dice el reporte. Un reporte conciso por rol en `docs/revision_2026-11-22b/NN_<rol>.md`.
- Arquitecto + DevOps: migraciones 0162-0164 (reversibles, aditivas, id ≤32 caracteres, `lock_timeout`), rewrites de Hosting del sitio, restauración de respaldo (`scripts/restore_test.sh`: plan para que Juan David lo ejecute; 1-2 h).
- QA + Developer: las pruebas con base de datos escritas y no corridas (`test_saas_organizations*`, `test_foto_pendiente_bd`, `test_quote_request`, nodos): revisar a mano contra fixtures; ajustar lo evidente. Tres pruebas de texto ya fallaban antes (`test_privacy` ×2, `test_codigo_campo` ×1): decidir si se arreglan.
- Ciberseguridad nube: foto pendiente (cifrado y purga de `*.pending.jpg` en todas las rutas de borrado), endpoint de cotización (abuso, cabeceras, límites), CSRF exento solo en esa ruta, `/internal/*`.
- Ciberseguridad local: `autodestruir.ps1` (¿puede dispararse por error?: solo con el 403 «disabled» explícito), `proteger-disco.ps1` (no registra la clave), plazo de gracia (401 ≠ baja).
- UX digitador/cliente/gestión y expertos Google/SEO/IA: confirmar lo hecho en la primera pasada contra la pantalla real de staging.
- Finanzas (internos y externos) y prospecto SaaS: revisar `PROPUESTA_FINANCIERA_SAAS_2026-11-22.md` contra los costos reales de Cloud Run/Neon; no cambiar precios sin Juan David.

### Fase 6 — «Lo que sigue» (en este orden, solo lo acotado; lo grande = plan exacto)
1. Facturación y marca propia por empresa (plan).
2. Páginas por servicio del sitio y casilla de privacidad en la cotización (esperan a la auditora).
3. Registro de decisiones del modelo facial y pruebas de sesgo (plan).
4. Purga local de eventos devueltos.
5. CSP estricta (plan; medir antes con report-only).
6. Impresión de escarapelas de dependientes.
7. Revisar ramas C1, C2, D y proponer lista a borrar (sin borrar).
8. Opcional: quitar el disparador `migra/fase1-2` de `cloudrun.yml` junto con su prueba fijada.

### Fase 7 — Cierre
1. Una sola corrida de la suite completa en GitHub (con base de datos, incluidas 0162-0164, foto pendiente, cotización y SaaS). Arreglar lo rojo.
2. Re-ejecutar la lista de staging que haya cambiado.
3. Escribir `docs/revision_2026-11-22b/README.md` con: **qué confirmé, qué corregí, qué queda, qué no pude comprobar**, y actualizar `CHANGELOG.md` y el reporte final en el proyecto (`project_write`).
4. Preparar (no ejecutar) el paquete de producción: orden de migraciones (0161→0164), variables, secreto `quote-to-email`, DNS del sitio paso a paso, plan de reversa, y pedir la autorización explícita de Juan David por acción.

## 5. Lo pendiente que solo Juan David puede hacer
- Aprobar «Authorize Cloud Shell» (o pegar los comandos de staging).
- Iniciar sesión en staging en el navegador integrado.
- Crear en producción, cuando llegue el momento, el secreto de cotización con lectura a ciegas (el comando está en `deploy/gcp/README.md` §7; proyecto `goldenweb-prod`). En staging no hace falta: allí no se envían correos reales.
- Responder a la auditora y dar el visto bueno a los textos de IA/privacidad.
- Probar `autodestruir.ps1`/BitLocker/plazo de gracia en un portátil de prueba **con llave de prueba**.
- Revisar la propuesta financiera.

## 6. Qué NO está comprobado (no darlo por bueno)
Todas las pruebas con base de datos; migraciones 0162-0164 con Alembic real; sitio compilado y comparado; scripts PowerShell; flujo de GitHub; entrega real del correo de cotización (solo se verifica en producción); E2E contra staging; Poppins vs Agrandir a ojo; que Firebase Hosting deje pasar `/robots.txt` y `/api/public/**` en el sitio nuevo.

## 7. Mapa de archivos clave
- Reportes de la primera pasada: `docs/revision_2026-11-22/01…15`; privado (no se publica): `03b_seguridad_detalle_PRIVADO.md`.
- Sitio: `deploy/sitio/` (`deploy_sitio.sh`, `rehacer_parche.sh`, `parche/`), `docs/26_SITIO_WEB_MONTAJE.md`.
- SaaS: `app/orgs.py`, `app/routers/platform.py`, `docs/27_SAAS_EMPRESAS.md`.
- Cotización: `app/quote_core.py`, `app/quote_mail.py`, `app/routers/quote_request.py`.
- Foto pendiente: `app/enroll.py`, `app/routers/aceptar.py`, `alembic/versions/0164_accept_verify_photo.py`, `docs/revision_2026-11-22/12_seguridad_correcciones.md` §7.
- Servidor local: `deploy/windows/` (`updater-service.ps1`, `autodestruir.ps1`, `proteger-disco.ps1`), `app/server_lock.py`, `docs/17_SERVIDOR_LOCAL.md`.
- E2E: `tests/e2e/`, `.github/workflows/e2e-staging.yml` (manual).
- Pruebas manuales: `docs/PRUEBAS_STAGING_2026-11-23.md`. Finanzas: `docs/PROPUESTA_FINANCIERA_SAAS_2026-11-22.md`. Legal pendiente: `docs/legal/PENDIENTE_AUDITORA_2026-11-22.md`.
- Despliegue: `deploy/gcp/README.md`, `deploy/gcp/manual_deploy.sh`, `deploy/gcp/config.sh`.

## 8. Forma de responder a Juan David
Decisiones importantes: formato consejo (contrario, primeros principios, expansionista, forastero, ejecutor, presidente), corto. Trabajo normal: una frase de qué se hizo, qué falta de él y el siguiente paso. Una orden de consola por mensaje, con qué esperar. Sin recapitular pasos.

## 9. Texto para pegar después de `/clear`
```
Lee CLAUDE.md, docs/revision_2026-11-22b/00_PLAN_SEGUNDA_PASADA.md, docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md y docs/revision_2026-11-22/README.md.
Rama saas/revision-integral (repo Facial-Recognition-GOLDEN, clon en /home/claude/facial-recognition-golden).
Ejecuta el plan de la segunda pasada, fase por fase, en el orden escrito. Juan David autorizó usar su computador y el navegador integrado;
los límites duros del plan (producción, main, contraseñas, DNS sin orden) siguen vigentes. Empieza por la Fase 0 y la Fase 1:
dime si ya aprobó «Authorize Cloud Shell» o dame el comando de redespliegue de staging (uno por mensaje). Usa la estrategia de consejo
solo en decisiones; en lo demás, optimiza tokens (grep + rangos, pocos agentes a la vez, reportes concisos) y haz un commit + push por pieza.
```
