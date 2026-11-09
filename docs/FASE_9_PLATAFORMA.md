# Fase 9 · Plataforma segura y panel de gastos

Estado: en construcción (nada desplegado). Se programa todo; un solo despliegue a staging y una sola corrida completa de pruebas al final.

## A. Alerta de borrado masivo (hecha, sin probar en la nube)

**Qué hace.** Si una acción borra muchos registros importantes de golpe, sale un correo al instante a los destinatarios configurados.
Cuenta: eventos, formularios, inscripciones, registros de asistentes, personas, registros de acceso, archivos de evento y cuentas del personal.

**Cuándo avisa** (configurable en Configuración → «Alertas del sistema», solo admin y super admin):
- una sola acción borra **≥ 50** registros, o
- la misma cuenta acumula **≥ 200** en **10 minutos**.
Los tres números se cambian ahí mismo (con límites para no dejar la alerta inútil) y la alerta se puede apagar.

**Qué dice el correo.** Quién (usuario y rol), qué se borró y cuántos, evento (nombre y número), fecha y hora de Bogotá y qué hacer. **Nunca** lleva datos de asistentes (ni cédulas, ni nombres, ni correos).
Además llega a la campana de las cuentas de la plataforma que estén en la lista.

**Quién recibe.** Se siembra con `juando02603@gmail.com` y `callcenter@goldenlogisticas.com` (migración `0119_system_alerts`). En la pestaña se agregan o quitan correos externos y cuentas de la plataforma (con correo registrado), se pausan sin borrarlos y hay botón «Enviar alerta de prueba».

**No es una alerta** (se marca como esperada): la purga programada de retención de biometría (`privacy.purge_expired`) y la de un evento finalizado (`privacy.purge_event`).

**Cómo funciona por dentro** (`app/mass_delete.py`).
- Se engancha a la sesión de SQLAlchemy: cuenta los `db.delete(...)` (después del flush) y los `query.delete()` (después del borrado masivo). No hay consultas periódicas: Neon puede apagarse.
- Antes de confirmar la transacción evalúa. Solo consulta la base si la acción borró **10 o más** filas (guarda esas acciones en `mass_delete_log` para sumar la ventana de la cuenta).
- La alerta (historial `system_alerts`, correos por la cola `system_alert_mail`, campana) entra en la MISMA transacción: si el borrado se revierte, no hay alerta. Al confirmar se despierta la cola.
- Si algo falla al evaluar, se registra en el log y el borrado de la persona sigue intacto (la alerta nunca bloquea).
- Una misma situación no repite correo: clave por cuenta + evento + tipo + tramo de la ventana.
- La cuenta que borra se toma de la sesión de la petición (`auth.get_current_staff`); sin cuenta (tareas del sistema) el correo dice «el sistema».

**Límites honestos.**
- Los `DELETE` escritos a mano con `text()` no se cuentan; en el código solo los usa la supresión de UNA persona y la purga esperada.
- Un borrado directo en la base de datos (fuera de la aplicación) no se detecta aquí; eso lo cubre el respaldo de Neon.
- El correo sale por el mismo servicio de correo de la plataforma: si no está configurado, queda guardado y se ve en el log.

**Archivos.** `app/mass_delete.py`, `app/routers/system_alerts.py`, `alembic/versions/0119_system_alerts.py`, `templates/configuracion.html` (pestaña), `static/js/system-alerts-admin.js`, `tests/test_alertas_borrado.py`.
