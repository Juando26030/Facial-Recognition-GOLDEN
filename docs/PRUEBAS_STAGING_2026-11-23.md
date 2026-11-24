# Qué probar en staging y cómo (23-nov-2026)

Para Juan David. Cada prueba dice **qué hacer** y **qué debe pasar**. Si algo no pasa, anota el número de la prueba y qué viste (una captura sirve).
Usa un evento de prueba (nombre «PRUEBA …») y la persona de prueba (cédula `PRUEBA`); en staging no se manda ningún correo real ni se cobra de verdad.

## Ya comprobado por Claude (sin sesión) el 22-nov
`/robots.txt` pide no indexar · `/login` trae «noindex» · `/health` responde 200 · `/instalar` responde 404 · la cotización responde bien con el campo trampa (200) y con datos malos (400 con un mensaje por campo).

## A. Con cuenta de super administrador
1. **Empresas (SaaS):** menú lateral › «Empresas (SaaS)». Crear una empresa «PRUEBA». *Debe:* aparecer en la lista con su plan; al crear su administrador, la contraseña temporal se muestra UNA vez.
2. **Límite del plan:** en esa empresa, con plan de pocos eventos, intentar crear más eventos que el tope. *Debe:* un mensaje claro «su plan no incluye…» y no crear el evento.
3. **Crear evento:** al terminar aparece «¿Qué sigue?».
4. **Confirmaciones que piden escribir la palabra** (si escribes mal, no pasa nada): reabrir un evento finalizado (`REABRIR`), eliminar usuarios temporales (`ELIMINAR`), suprimir datos de una persona, reembolsar (`REEMBOLSAR`), Configuración › Servidor local › Deshabilitar una llave de PRUEBA (`DESHABILITAR`; no uses una llave real).
5. **Formulario con pago en «Activo»:** pide confirmar y muestra «Cobra con: …».

## B. Con cuenta de digitador
6. **Menú:** en Inventario, Áreas y Turnos NO se ve el menú de administrador.
7. **Editar a alguien no registrado:** abrir Editar. *Debe:* aviso «Al guardar, esta persona queda Registrada…» y el botón «Guardar y registrar» (NO existe «Guardar sin registrar» para nadie desde el 24-nov). Un coordinador o superior que solo corrige un dato cambia «Estado de registro» a «No registrado» y la persona sigue No registrada.
8. **Tabla de Registro:** achica la ventana del navegador de ancha a angosta. *Debe:* nada cortado con «…», sin barra de desplazamiento horizontal, encabezados con el nombre del campo, nombres y apellidos siempre visibles, el origen y «Recién registrado» junto a Acreditar.

## C. Foto pendiente (la prueba más importante de seguridad)
9. En Parámetros del evento, buscar «Verificar antes de reemplazar la foto»: **activo por defecto**, con ⓘ.
10. Con una persona que ya tiene foto de registro, abrir `/aceptar` SIN su enlace personal, escribir su cédula y fecha, tomar una selfie y aceptar. *Debe:* la foto que ve el operador **no cambia**.
11. Verificar a esa persona (por su enlace personal o por el personal). *Debe:* ahora sí cambia la foto.
12. Apagar el interruptor y repetir 10. *Debe:* la selfie reemplaza la foto directo (el comportamiento de antes).
13. Borrar los datos de esa persona (supresión). *Debe:* no queda ninguna de las dos fotos.

## D. Servidor local (solo en un portátil de PRUEBA, nunca uno real)
14. Crear una llave de prueba «solo eventos del cliente…» y vincular el servidor de prueba. *Debe:* solo ve los eventos de ese cliente.
15. **Plazo de gracia:** en `config\local.env` del portátil de prueba poner `LOCAL_GRACE_DAYS=1`, dejarlo sin internet 2 días (o cambiar la marca `LOCAL_CLOUD_OK_AT` a una fecha vieja). *Debe:* franja roja «SOLO LECTURA»; entrar, salir y sincronizar siguen funcionando.
16. **Baja automática:** en la nube, Deshabilitar la llave del portátil de prueba (escribir `DESHABILITAR`); con el portátil conectado a internet. *Debe:* en unos minutos se desinstala solo, desaparece `C:\GoldenLocal` y queda una línea en `C:\ProgramData\GoldenLocal-baja.log`.
17. **BitLocker:** `proteger-disco.ps1 -StatusOnly` (PowerShell como administrador). *Debe:* decir si el disco está cifrado o por qué no se puede (sin TPM / edición de Windows). Para cifrar: `-RecoveryKeyFolder E:\` con una memoria USB; guarda esa clave fuera del portátil.

## E. Sitio web en staging (después de montarlo, `docs/26` parte A0)
18. Se ve igual que antes; la letra (Poppins) se ve bien en celular y computador; teléfono +57 318 098 1752 y correo soporteit@goldenlogisticas.com en el pie y la cabecera.
19. El sitio pide «no indexar» (`/robots.txt` en el sitio de staging).
20. **Cotización:** llenar y enviar. *Debe:* «Recibimos su solicitud…» (requiere el secreto `quote-to-email` en staging, con una dirección inventada; sin él responde 503 — comprobado el 23-nov). En staging el correo NO sale (no hay credenciales de correo); lo que se comprueba es el mensaje. La entrega real a la comercial solo se prueba en producción, con el secreto `quote-to-email` creado.

## F. Salud general
21. `/health` de los tres servicios responde 200; en Configuración › Sistema no hay alertas rojas nuevas.
22. **Pruebas automáticas con navegador:** `tests/e2e/LEEME.md` (un comando; contra staging, nunca producción).

## Qué no se probó nunca todavía
Las pruebas con base de datos (se corren en GitHub una sola vez cuando apruebes staging); la baja automática y BitLocker en Windows real; el sitio compilado.
