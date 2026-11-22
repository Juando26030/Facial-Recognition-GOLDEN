# Revisión integral de GoldenWeb 2.0 y del sitio web — reporte final (22-nov-2026)

Rama: **`saas/revision-integral`** (sale de `diag/inventario-base`, commit `fed2c99` hacia atrás = inventario por base ya probado en staging).
**Nada de esto está en staging, en `main` ni en producción.** Trae dos migraciones nuevas: `0162_organizations` y `0163_local_nodes_tenant` (aditivas).
Reglas que mandan: [`docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md`](../REGLAS_INAMOVIBLES_Y_DECISIONES.md).

## 1. Qué se revisó y dónde está cada reporte
| # | Rol | Reporte | Veredicto en una línea |
|---|---|---|---|
| 01 | Arquitecto + DevOps | `01_arquitectura_devops.md` | Sana para Golden; para SaaS falta la entidad «empresa» y el aislamiento encendido. Nunca se ha ensayado restaurar un respaldo de producción. |
| 02 | Developer + QA + Scrum/PO | `02_codigo_calidad_repo.md` | Código sano y bien probado; el riesgo es de gobierno: 136 ramas, `main` 11 días atrás de producción, cero pruebas de extremo a extremo. |
| 03 | Seguridad (nube) | `03_seguridad_nube.md` | 804 rutas revisadas: ninguna expone datos sin sesión. Lo más serio solo aplica al abrir el SaaS (aislamiento apagado). |
| 04 | Seguridad (servidor local) | `04_seguridad_servidor_local.md` | Seguro frente a la red; frágil si roban el portátil (disco sin cifrar) y ante un servidor que suba datos manipulados. |
| 05 | Digitador, cliente, público | `05_usabilidad_digitador_cliente_publico.md` | Rápido (2-3 toques por tarea); dos riesgos altos: «Editar» registraba sin avisar y el digitador veía el menú completo. |
| 06 | Coordinador, comercial, admin | `06_usabilidad_gestion.md` | 24 de 27 bloques de Parámetros tienen ayuda; acciones destructivas con un simple Sí/No. |
| 07 | Prospectos SaaS + finanzas | `07_saas_prospectos_finanzas_planes.md` | Costos por evento, planes y precios propuestos, y lo que falta para vender. **Los precios son propuesta, no decisión.** |
| 08 | Google/SEO + UX + regulación de IA | `08_google_seo_ux_regulacion_ia.md` | El sitio hoy pide no ser indexado, no tiene sitemap, datos estructurados ni páginas por servicio; borradores de textos de privacidad e IA. |

## 2. Qué se hizo al respecto (ya en la rama)
| # | Pieza | Reporte | Estado |
|---|---|---|---|
| 09 | Sitio web montable en golden-eventos.com: segundo sitio de Firebase Hosting, script y workflow manual, parche SEO, guía [`docs/26_SITIO_WEB_MONTAJE.md`](../26_SITIO_WEB_MONTAJE.md) | `09_integracion_sitio_web.md` | Listo para ejecutar. **No compilado ni comparado aquí** (sin acceso a npm). |
| 10 | SaaS: empresas, planes, límites, pantalla «Empresas (SaaS)», `/instalar` | `10_saas_capa_empresa.md`, [`docs/27_SAAS_EMPRESAS.md`](../27_SAAS_EMPRESAS.md) | Primera pieza. Pruebas con base escritas, sin correr. |
| 11 | SEO de la plataforma: `/robots.txt`, `noindex`, canónico en legales | `11_seo_plataforma.md` | Hecho. |
| 12 | Seguridad: llave de servidor local por cliente, subidas solo de asistentes del evento, roles de vinculación, impresión por POST, dependencia con CVE | `12_seguridad_correcciones.md` | 5 de 7. Foto pendiente en `/aceptar` NO hecha; plazo de gracia a medias. |
| 13 | Gestión: confirmaciones escritas, aviso de cobro real, «¿Qué sigue?», ayudas por rol | `13_usabilidad_gestion_correcciones.md` | Hecho. |
| 14 | Repositorio: escáneres en más ramas, `CHANGELOG`, `CONTRIBUTING`, scripts para limpiar ramas y reordenar docs (solo listan) | `14_gobierno_repositorio.md` | Hecho. **Ninguna rama borrada.** |
| 15 | Digitador: aviso «queda Registrada», «Guardar sin registrar», menú oculto, botones de 44 px | `15_usabilidad_digitador_correcciones.md` | Hecho; campana solo mitigada. |
| — | Servidor local: borrado seguro del portátil, descarga sin redirecciones | 04 | Hecho; PowerShell sin probar en Windows. |
| — | HSTS con subdominios, `lock_timeout` en migraciones, tiempos límite en CI | 01, 03 | Hecho. |

## 3. Decisiones que necesita Juan David (en este orden)
1. **`/instalar`** (página sin sesión que crea el primer super administrador cuando no hay cuentas): autorizarla en la lista de rutas públicas o retirarla. Hoy deja en rojo `tests/test_seguridad_2026-11-22.py` a propósito. Recomendación: retirarla por ahora.
2. **Subir esta rama a staging** y probar (lista en §5). La suite completa de GitHub, una sola vez, después de aprobar.
3. **Aislamiento entre clientes** (`ENFORCE_STAFF_TENANT=1`, `ENFORCE_STAFF_EVENT_SCOPE=1`): encenderlo en staging y probar con una cuenta de un cliente ficticio. Es requisito antes de dar una cuenta a otra empresa.
4. **BitLocker** en cada portátil servidor (30 min por portátil) y protocolo de pérdida (`docs/17_SERVIDOR_LOCAL.md` § Seguridad del portátil).
5. **Ensayo de restauración** de un respaldo real (`scripts/restore_test.sh`, 1-2 h).
6. **Sitio web:** teléfono y correo oficiales (hoy difieren entre sitio y plataforma), licencia de Agrandir, si privacidad e IA se publican como borrador, y los pasos de DNS de `docs/26` (cada uno con su orden escrita).
7. **Precios y planes SaaS** (reporte 07) y **ramas a borrar** (`scripts/limpiar_ramas_2026-11-22.sh`; grupos A y B sin riesgo).
8. **`main` al día** con lo que corre en producción (hoy 11 días atrás): es lo que destraba escáneres, etiquetas y la limpieza.
9. **Auditora:** `docs/legal/PENDIENTE_AUDITORA_2026-11-22.md` y los borradores del reporte 08 §9.

## 4. Lo que NO se pudo comprobar
- Ninguna prueba con base de datos corrió (aquí no hay FastAPI, SQLAlchemy ni Postgres): ni las nuevas de SaaS, seguridad y nodos, ni la suite existente. Las migraciones 0162/0163 no se ejecutaron con Alembic (el SQL delicado de 0162 sí se probó a mano en un Postgres local).
- El sitio no se compiló; «idéntico» sigue sin verificar. La sintaxis de `firebase.json` no se confirmó contra la documentación.
- Nada contra producción. En staging solo lectura sin sesión (cabeceras y 401).
- Scripts de PowerShell del servidor local, workflows de GitHub y comandos de nube: escritos y validados de sintaxis, no ejecutados.
- Tres pruebas de texto ya fallaban antes de esta rama (`test_privacy` ×2, `test_codigo_campo` ×1): no son de este trabajo.

## 5. Qué probar en staging
- Registro: editar a alguien no registrado como digitador (aviso y «Guardar sin registrar»); Inventario/Áreas/Turnos sin menú para el digitador.
- Parámetros › Privacidad, Usuarios, reembolso y reabrir evento: piden escribir la palabra.
- Formulario con pago en «Activo»: confirma y muestra «Cobra con».
- Crear evento: aparece «¿Qué sigue?».
- Configuración › Servidor local: crear una llave «solo eventos del cliente…» y vincular un servidor de prueba; sincronizar un evento compartido.
- `/plataforma` (super administrador): crear una empresa de prueba y ver uso y límites.
- `/robots.txt` responde 200; `/login` trae `noindex`.

## 6. Lo que sigue (no construido)
Filtro por empresa en todas las consultas y RLS (160-220 h, reporte 01 Anexo A.3) · facturación y marca propia por empresa · formulario de cotización del sitio con envío real · páginas por servicio del sitio · registro de decisiones del modelo facial y pruebas de sesgo · foto pendiente en `/aceptar` · purga de eventos devueltos en el servidor local · pruebas de extremo a extremo en staging · CSP estricta.

## 7. Texto para una sesión nueva (segunda pasada con la memoria fresca)
```
Lee CLAUDE.md, docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md y docs/revision_2026-11-22/README.md (y los reportes 01-15 de esa carpeta).
Estás en el repositorio Facial-Recognition-GOLDEN, rama saas/revision-integral. El sitio web está en el repo golden-sitio-web (commit en deploy/sitio/VERSION).
Tarea: SEGUNDA PASADA de la revisión integral. Con agentes por rol (arquitecto, Scrum master, QA, developer, PO, DevOps, ciberseguridad;
digitador, cliente y roles de gestión; empresas interesadas en el SaaS desde ingeniería y contabilidad; expertos financieros internos y externos;
expertos en estándares de Google; expertos en UX y en regulación de IA; auditores de seguridad de la nube y del servidor local y quienes corrigen):
1) verifica de forma independiente lo que la primera pasada dice haber hecho (no lo des por cierto: léelo en el código);
2) busca lo que la primera pasada no vio; 3) continúa con «Lo que sigue» del README en el orden de «Decisiones», sin repetir trabajo;
4) corrige lo que sea acotado, con pruebas; lo grande, plan exacto.
Límites: nada a main, ningún merge, ningún despliegue ni comando de nube, ninguna rama borrada, ningún DNS; secretos y datos personales nunca;
staging primero y la suite de GitHub una sola vez al final. Trabaja en la misma rama, un commit + push por pieza, y entrega un reporte por rol en
docs/revision_2026-11-22b/ más un README final con: qué confirmaste, qué corregiste, qué queda y qué no pudiste comprobar.
Optimiza tokens: lee fragmentos (grep + rangos), pocos agentes a la vez, reportes concisos.
```
