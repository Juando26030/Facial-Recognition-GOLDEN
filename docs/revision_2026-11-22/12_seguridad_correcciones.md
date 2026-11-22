# 12 · Correcciones de seguridad aplicadas (nube y servidor local) — 22-nov-2026

Rol: desarrollador de seguridad que APLICA lo acotado de los reportes `03_seguridad_nube.md` y `04_seguridad_servidor_local.md`. Rama `saas/revision-integral`, sin commit ni push.
Nada se probó contra staging ni producción. En este entorno no hay SQLAlchemy ni PostgreSQL: **las pruebas con base quedaron escritas pero NO se corrieron** (ver §5).

## 1. Resumen en 5 líneas
1. De las 7 piezas pedidas, **5 quedaron hechas** (alcance por cliente de cada servidor local, subidas solo de asistentes del evento, servidores vinculados por coordinador/comercial ya pueden subir, «tomar» impresión por POST, `setuptools` sin CVE), **1 a medias a propósito** (plazo de gracia: la regla está, falta enchufarla en `app/main.py`, que es de otro agente) y **1 NO se hizo** (foto pendiente de `/aceptar`: resultó más grande de lo descrito).
2. Lo más grave que se cierra: un servidor local ya no puede «autorizar» el rostro de alguien por su cuenta ni editar personas de otros eventos, y una llave puede atarse a UN cliente (un portátil perdido deja de alcanzar los eventos de los demás).
3. Lo más valioso para la operación de hoy: un portátil vinculado por un coordinador o comercial **estaba perdiendo sus subidas** (403 en cada ciclo); ya no.
4. Todo es compatible con lo instalado: llaves y servidores existentes quedan «sin cliente» (como hoy), el GET de impresión sigue respondiendo, las respuestas a los servidores solo ganaron un campo (`rejected`).
5. Antes de producción hace falta correr la suite con base (GitHub) y probar en staging: migración `0163`, un evento compartido de punta a punta y el arranque con `setuptools 78.1.1`.

## 2. Hallazgos
| # | Severidad | Qué pasa | Dónde | Por qué importa | Qué se hizo |
|---|---|---|---|---|---|
| 1 | Alta (03 #3, 04 #3) | El token de un servidor local alcanzaba los eventos de TODOS los clientes (listar, tomar, bajar la base de personas). | `app/routers/node_api.py`, `app/routers/nodes.py` | Portátil perdido o de un tercero = base de cualquier cliente; en el SaaS, cruce entre empresas. | **Corregido** (opcional por llave): migración `0163_local_nodes_tenant`, `_event_for_node`, selector «Solo eventos del cliente…» con ayuda ⓘ. Sin elegir cliente, como hoy. |
| 2 | Alta (04 #4) | La nube aplicaba ediciones, fecha de nacimiento, aceptaciones y autorizaciones de CUALQUIER persona del cliente, no solo de los asistentes del evento arrendado. | `app/node_extra.py`, `nodes.node_records` | Un servidor (o una copia alterada de su base) cambiaba datos de personas de otros eventos. | **Corregido**: solo asistentes (`event_attendees`); lo demás se cuenta en `rejected` y el ciclo sigue (200). |
| 3 | Alta (04 #4) | Un servidor podía subir `accepted_biometric=True` de alguien que nunca aceptó y la nube lo dejaba reconocer por rostro. | `node_extra.apply_consents` | Rompe la regla legal «sin aceptación de la PERSONA no hay reconocimiento». | **Corregido** reutilizando la marca que ya existía (`web_acceptances` sin `verified_at`, la que `consent.accepted_user_ids` excluye): queda «por verificar» hasta que el personal confirme. No se inventó una marca nueva. |
| 4 | Alta (04 #5) | Servidor vinculado por coordinador/comercial: 403 en cada subida; personas e ingresos se quedaban en el portátil. | `app/node_auth.py::node_staff` | Pérdida silenciosa de datos del evento. | **Corregido**: suben las mismas cuentas que pueden vincular; una que no es admin solo a eventos que puede ver (`get_event_for_staff`). |
| 5 | Media (03 #4) | En `/aceptar`, quien sepa cédula + fecha de nacimiento reemplaza la foto de registro de otra persona (el rostro no se suplanta, la foto que ve el operador sí). | `app/routers/aceptar.py::submit` | El operador verifica contra una foto que puede ser del impostor. | **Propuesto, NO implementado** (plan exacto en §4.1): la foto pendiente debe entrar en TODAS las purgas biométricas (`app/privacy.py` y otros 4 archivos fuera de mi área); hacerlo a medias dejaría fotos de rostros fuera de la regla de 7 días. |
| 6 | Baja (03 #12) | `GET …/print-jobs-next` cambia estado (toma un trabajo). | `app/routers/shared_print.py`, `static/js/shared-print.js` | Un GET que escribe depende solo de las cabeceras `Sec-Fetch-*`. | **Corregido**: acepta POST y el JS llama por POST; el GET queda en transición (cuándo quitarlo: §4.4). |
| 7 | Baja (03 #11) | `setuptools==69.5.1` con CVE-2024-6345 y CVE-2025-47273. | `requirements.txt` | Riesgo real casi nulo, pero `pip-audit` lo marca siempre. | **Corregido**: `78.1.1` (conserva `pkg_resources`). El reporte no señaló ninguna otra dependencia. Falta la prueba de arranque en staging. |
| 8 | Media (04 #6) | Un servidor perdido que no vuelve a internet, o con token revocado (401), sigue trabajando para siempre. | `app/server_lock.py` | El bloqueo solo llega si el equipo habla con la nube. | **Corregido en parte**: la regla (`grace_state`, `LOCAL_GRACE_DAYS=14`) y sus marcas ya existen y se alimentan en cada llamada a la nube; **falta aplicarla** en el middleware de `app/main.py` (§4.2). Hoy no cambia el comportamiento. |
| 9 | Media (visto de paso, sin comprobar) | En un evento compartido, `node_sync.pull_event` sumaba con `total[k] += v` sobre un diccionario que no tiene las claves de `node_extra` (`edits`, `areas`…): la primera edición bajada de otro servidor daría `KeyError` y ese ciclo no guardaría el cursor. | `app/node_sync.py` | Si es así, un servidor de un evento compartido repetiría el mismo lote sin avanzar. | **Corregido** (`total.get(k, 0)`), una línea. No lo pude reproducir sin base: confirmar con `tests/test_evento_compartido.py`. |

## 3. Qué se cambió en el código
- `alembic/versions/0163_local_nodes_tenant.py` (nuevo, aditiva, va después de `0162_organizations`): `local_nodes.tenant_id` y `local_server_keys.tenant_id`, texto, NULL = sin restricción.
- `app/models.py`: esas dos columnas. **Desvío del encargo:** hizo falta también la de `local_server_keys` (la llave se crea antes de que exista el servidor; tiene que guardar el cliente hasta la vinculación).
- `app/routers/node_api.py`: `node_tenant_allows` y `_event_for_node(db, node, event_id)` (404 si el evento es de otro cliente) en arrendar, paquete, checklist, deshacer, precheck y cambios; la lista de eventos se filtra.
- `app/routers/nodes.py`: el mismo filtro en `_leased_event` (devolver, sincronizar, «uploaded», records, extra) y en la copia completa; `enroll_node` pasa el cliente de la llave al servidor; `_upload_staff`; `rejected` en las respuestas de `/records` y `/extra`. (No estaba en la lista literal del encargo, pero es donde viven la vinculación y las subidas que citan los reportes.)
- `app/routers/server_keys.py`: `POST /api/server-keys` acepta `tenant_id` opcional (400 si no existe o está archivado); la lista devuelve `tenant_id` y `tenant_name`.
- `templates/configuracion.html` + `static/js/server-keys-card.js`: selector «Todos los clientes (como siempre) / Solo eventos de: …», ayuda ⓘ con las seis partes del principio dummy, columna «Cliente». **Desvío del encargo:** la tarjeta de llaves está en `configuracion.html` (Configuración › Servidor local), no en `servidor_local.html`; solo se tocó esa tarjeta.
- `app/node_extra.py`: `_Users` exige asistente del evento cuando la nube recibe de un servidor (`from_peer=None`); `apply_person_change_effect(..., attendee_only=True)`; aceptación biométrica de un servidor → por verificar; `apply_all` devuelve `rejected`. Áreas, entregas, turnos y contactos NO se tocaron (siguen por cliente).
- `app/node_auth.py`: `ENROLL_ROLES` (única lista), `staff_can_upload` (regla pura) y `node_staff` con esos roles.
- `app/routers/shared_print.py` + `static/js/shared-print.js`: POST además de GET; las dos llamadas del JS van por POST.
- `requirements.txt`: `setuptools==78.1.1`.
- `app/server_lock.py`: `grace_days`, `grace_decision` (pura), `grace_state`, `note_cloud_ok`, conteo de 401, `write_blocked`. `app/node_sync.py`: `_call` avisa `note_cloud_ok()`; arreglo del hallazgo 9.
- `docs/17_SERVIDOR_LOCAL.md` (§ Llaves) y `docs/23_EVENTO_COMPARTIDO_NUBE.md` (§3b): lo anterior.
- Pruebas: `tests/test_seguridad_correcciones_2026-11-22.py` (14 puras/texto, **pasan**) y `tests/test_seguridad_correcciones_bd.py` (8 con base, **sin correr**). `ruff check .` en verde.

## 4. Qué queda pendiente y por qué (orden recomendado)
1. **Foto pendiente en `/aceptar` (03 #4) — 4 h + suite.** Plan exacto, en UNA pieza: (a) `enroll.pending_photo_key(tenant, uid)` = `photo_key(...)` con `.pending.jpg`; (b) en `aceptar.submit`, si `trusted` es falso y ya existe `photo_key`, guardar la selfie en la clave pendiente, NO encolar `face_enroll` y no tocar la foto vigente; (c) en `consents.verify_web_acceptance`, si hay pendiente: `get_storage().move(pendiente, vigente)` y encolar `face_enroll` si la persona no tiene vector; (d) borrar la pendiente en TODO lugar que borra `photo_key`: `privacy.py` (3 sitios), `enroll.run_enroll`, `roster_delete.py`, `ops_runner.py`, y excluirla de `event_transfer.py`; (e) prueba con base: enviar con cédula de otro → la foto vigente no cambia; verificar → cambia; purgar → no queda ninguna de las dos. Mientras tanto: encender «exigir el enlace personal» en eventos con base del cliente.
2. **Enchufar el plazo de gracia (04 #6) — 2 h.** En `app/main.py::local_catalog_readonly`, después del bloqueo: `st = server_lock.grace_state(); if server_lock.write_blocked(request.method, request.url.path, st["state"]): return JSONResponse(403, {"detail": st["message"]})`; aviso `gw-alert` en la plantilla base cuando `state != "ok"`; exponer el estado en `/api/ops/server-id`. Revisar con Juan David la lista de lo que SÍ se deja escribir en solo lectura (hoy: entrar, salir y sincronizar/subir) y agregar `LOCAL_GRACE_DAYS` a `.env.example`. No choca con docs/17 ni con las pruebas existentes: el 401 sigue sin «deshabilitar».
3. **Suite con base y staging — 2 h.** Correr `test_seguridad_correcciones_bd.py`, `test_evento_compartido.py`, `test_nodos_subida.py`, `test_server_keys.py`, `test_impresion_compartida.py`; en staging: `alembic upgrade head`, crear una llave con cliente y arrancar con `setuptools 78.1.1`.
4. **Quitar el GET de `print-jobs-next` — 1 h.** Cuando producción lleve un despliegue con este cambio y todos los servidores figuren «Al día» en Llaves de producto; ahí se cambian a POST las ~35 llamadas de las pruebas y se borra `_require_page_fetch`.
5. **Mirar en producción con qué cuenta se vinculó cada servidor** (columna «creado por»): los vinculados por coordinador/comercial tienen datos sin subir; al actualizar la nube subirán solos en el siguiente ciclo.
6. Sin hacer, de los reportes: alertas de servidor «raro», no enviar hashes de admin a los portátiles, purga local, BitLocker.

## 5. Qué NO se pudo comprobar
- **Ninguna prueba con base corrió** (no hay SQLAlchemy ni PostgreSQL aquí): ni las 8 nuevas ni las existentes de nodos, evento compartido, llaves e impresión. El código nuevo compila y pasa `ruff`, nada más. En particular no vi correr: la migración 0163, `get_event_for_staff` con una cuenta de coordinador llegando por un servidor, ni la marca «por verificar» en `apply_consents`.
- Si algún flujo legítimo sube ediciones/aceptaciones de alguien que NO es asistente del evento (ahora se rechazarían). Por el orden de subida (personas primero) no debería; vigilar `rejected` en los logs tras desplegar.
- Si un servidor local muestra hoy la pantalla de aceptación biométrica: si lo hace sin subir la verificación del personal, esas personas quedarán «por verificar» en la nube (es lo pedido, pero cambia la operación).
- El hallazgo 9 (KeyError) es lectura de código.
- `setuptools 78.1.1` con `face_recognition_models`: no se instaló nada (sin red).
- `tests/test_seguridad_2026-11-22.py` falla hoy por rutas `/instalar` de `platform.py` (otro agente), no por estos cambios.
- Nada en Windows, nada en navegador: el selector de cliente y su ayuda no se vieron en pantalla ni se revisaron ancho por ancho.

## 6. Consejo en corto y veredicto
- **Contrario:** «Cinco arreglos sin una sola prueba con base corrida no son cinco arreglos: son cinco hipótesis bien escritas.»
- **Primeros principios:** «La nube no debe creerle a un portátil más de lo que le creería a un formulario público: solo su evento, solo sus asistentes, y el rostro siempre lo confirma una persona.»
- **Expansionista:** «La llave por cliente es la pieza que permite prestarle un servidor local a otra empresa en el SaaS.»
- **Forastero:** «Me sorprende que un coordinador pudiera vincular un servidor que después no podía subir nada, y que nadie lo notara.»
- **Ejecutor:** «Suite completa, staging con una llave de cliente y un evento compartido, y después la foto pendiente como pieza aparte.»

**Veredicto:** cambios acotados y compatibles, listos para la suite con base; no listos para producción hasta verla en verde y probar staging.
**UN siguiente paso:** correr en GitHub `tests/test_seguridad_correcciones_bd.py` junto con `tests/test_evento_compartido.py` y `tests/test_nodos_subida.py`.
