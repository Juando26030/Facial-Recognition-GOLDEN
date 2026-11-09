# Fase 4: contraseña de primer ingreso (8-nov-2026)

**Decisión del dueño.** Digitador temporal: ingresa solo con su cédula, nunca usa ni cambia contraseña. Todas las demás cuentas de personal (cliente, coordinador, comercial, admin, super_admin): cambio OBLIGATORIO en el primer ingreso cuando otra persona creó la cuenta o reinició la contraseña (inicial = cédula). Ya no es un interruptor opcional.

## Cómo funciona
- Regla única: `security.must_change_on_set_by_other(role)` (`False` solo para `digitador`).
- Se marca `must_change_password=True` al crear (`POST /api/staff`, cliente de formulario en `form_client.py`, evento en `events.py` si algún día se vuelve a permitir `cliente`) y en `PUT /api/staff/{id}/password`. Este último ya no respeta `must_change` del cuerpo (se quitó el parámetro opcional, que por defecto era `True` pero se podía apagar). El digitador queda en `False` siempre (`use_username` o contraseña dada).
- `complete_login` ignora un indicador viejo en un digitador (no ve la pantalla).
- Con el indicador en la sesión, el middleware de `app/main.py` solo deja pasar `/cambiar-contrasena`, `/logout`, `/login`, `/static/` y `/api/password-policy` (se agregó esta última para que los requisitos en vivo de la pantalla funcionen). Todo lo demás: redirección (HTML) o 403.
- `POST /cambiar-contrasena`: pide la contraseña actual (la cédula), exige una nueva distinta de la actual y del usuario (la cédula) y que cumpla `password_problem`; limpia el indicador y sube `session_epoch` (`revoke_others`; la sesión actual sigue). Cambiar la propia contraseña, o el enlace «olvidé mi contraseña», no marca nada.
- Sin migración: la columna existía (`0036_security`).

## Cuentas existentes
No se fuerza nada retroactivo: solo aplica a creaciones y reinicios nuevos. Si el dueño lo quiere, basta una acción de admin o un script único (`UPDATE staff_users SET must_change_password = true WHERE role <> 'digitador' AND is_active`), ejecutado con su autorización; en el próximo ingreso cada persona elegiría la suya. Quienes se crean con `scripts/create_staff_user.py` eligen su contraseña en la consola y no se marcan.

Pruebas: `tests/test_clave_primera_vez.py`.
