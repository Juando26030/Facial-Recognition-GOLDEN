# Seguridad de sesiones e ingreso (revisión S, 6-nov-2026)

Qué se corrigió en el código (rama `sec/ag2`) y qué queda en manos de la infraestructura.

## Ingreso de digitadores (S1, decisión de Juan David)
- La cuenta digitador sigue entrando con la cédula como usuario y contraseña, pero:
  - solo si está asignada a un evento **en proceso** (si no, el mismo «Usuario o contraseña incorrectos»);
  - 3 contraseñas malas seguidas la **bloquean** (`staff_users.locked_at`); la desbloquea el coordinador en «Usuarios del evento»;
  - con la contraseña correcta NO se crea la sesión: queda una solicitud y el navegador espera en `/ingreso/espera`. El coordinador toca «Permitir» o «No permitir» en «Usuarios del evento». La solicitud vence a los 5 minutos, sirve una sola vez y solo la puede completar el navegador que la pidió (token en su cookie firmada; en la base solo el SHA-256).
- Código: `app/login_control.py`, `app/routers/login_approval.py`, `app/routers/auth.py` (`complete_login`, la única función que crea la sesión). Migración `0086_digitador_login_control`.
- `DIGITADOR_LOGIN_CONTROL=0` apaga la condición del evento en proceso y la autorización (lo usan las pruebas antiguas). El bloqueo tras 3 fallos siempre aplica. En producción NO se define (vale 1).

## Sesiones (S2)
- `staff_users.session_epoch` va dentro de la cookie (`ep`). Cambiar la contraseña sube la época y deja viva solo la sesión actual; restablecerla (por enlace o por un admin/coordinador) cierra todas.
- Cerrar sesión deja un token «libre» (`free:…`) en vez de NULL: antes NULL revivía las cookies viejas de la cuenta.
- Límite conocido: en admin/super_admin (sesiones múltiples), «Salir» borra la cookie de ese navegador pero no invalida una copia robada. Para eso está cambiar la contraseña.

## Intentos (S3, S5, S6, S7)
- IPv6 se cuenta por /64. El tope global de 40 fallos por usuario no frena a una IP desde la que la cuenta entró bien en las últimas 24 h (`login_ok`).
- El intento se anota antes de bcrypt. Un usuario inexistente también paga un bcrypt (hash de relleno). «Cambiar contraseña» tiene el mismo límite que el login.
- «Olvidé mi contraseña» responde siempre el mismo mensaje, también con el límite lleno.
- **Pendiente (S6):** el correo de restablecimiento se envía dentro de la petición, así que tarda más cuando la cuenta existe y tiene correo. No se pasó a `app/jobs.py` porque el enlace (token en claro) quedaría guardado en la tabla `jobs`. Si se quiere cerrar, habría que cifrar el token en el payload (como `person_ref`) o generarlo dentro del manejador.

## Otros
- S8: `/restablecer/<token>` se enmascara en el log de peticiones (`app/obs.py`). El registro de peticiones de la propia plataforma (Cloud Run / Firebase) sigue guardando la URL completa.
- S9: `GET /api/events/{id}/print-jobs-next` rechaza las navegaciones y las peticiones de otro sitio (`Sec-Fetch-Mode: navigate` / `Sec-Fetch-Site: cross-site`).
- S10: `/ready` solo dice qué componente falla; el motivo va al log, enmascarado.
- S11: fuera de `ENVIRONMENT=development` la app no arranca si `SECRET_KEY` falta, es un valor de ejemplo del repositorio o tiene menos de 32 caracteres (`app/secretcheck.py`).

## Infraestructura (S4, lo hace Juan David)
En la VM la app confía en `CF-Connecting-IP` (`TRUST_CF_CONNECTING_IP=1` por defecto). Si el puerto 443 de `golden-biometrics-prod` responde a tráfico que NO viene de Cloudflare, cualquiera puede inventar esa cabecera y saltarse los límites por IP. Hay que comprobarlo y, si es así:
1. regla de firewall de GCP que permita el 443 (y el 80) solo desde los rangos publicados de Cloudflare (https://www.cloudflare.com/ips/), o
2. en Nginx, `set_real_ip_from <rangos de Cloudflare>; real_ip_header CF-Connecting-IP;` y `deny all` para lo demás.

En Cloud Run no aplica: `TRUST_CF_CONNECTING_IP=0` y `XFF_STRIP_GOOGLE=1`.
