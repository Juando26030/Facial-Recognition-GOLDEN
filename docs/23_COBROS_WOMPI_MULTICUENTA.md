# 23 · Cobros con Wompi: multi-cuenta y QR (Fase 8, pieza 7)

**Qué resuelve.** Hasta ahora todo formulario cobraba con la cuenta de Wompi de Golden (variables `WOMPI_*`). Ahora un tercero puede prestarnos su comercio de Wompi:
guardamos SUS llaves, asignamos esa cuenta a un formulario y el pago entra directo a SU cuenta. Cada formulario (o sección) puede tener su cuenta y su QR.

## Cómo se usa (admin / super_admin)
1. Pantalla **Cuentas de cobro** (`/cuentas-de-cobro`, barra lateral). «Agregar cuenta» y pegar: llave pública (`pub_…`), secreto de integridad, secreto de eventos y, opcional, la llave privada (`prv_…`).
2. «Probar» consulta a Wompi (`GET /merchants/<llave pública>`) y muestra el nombre del comercio.
3. En Wompi del titular (Desarrolladores → Seguimiento de transacciones) pegar la **URL de eventos** que muestra la cuenta: `https://<dominio>/webhooks/wompi/<ref>`. Cada cuenta tiene la suya.
4. «Formularios y QR»: elegir la cuenta de cada formulario (vacío = cuenta de Golden) y «QR» para bajar el QR de su página de inscripción/pago (se dibuja en el navegador).
5. Con llave privada: «Crear enlace de pago» arma un *Payment Link* de Wompi (monto fijo o libre) y muestra su QR (`https://checkout.wompi.co/l/<id>`).

## Seguridad
- Las llaves privada, de integridad y de eventos se guardan **cifradas** (Fernet) con `PAYMENT_KEYS_ENCRYPTION_KEY` (varias separadas por coma = rotación). Sin esa variable no se guarda ninguna cuenta (falla cerrado). Perderla = pedir las llaves de nuevo al titular. Guardarla en Secret Manager (`payment-keys-encryption-key`) y en un gestor de contraseñas; **la crea Juan David** (no se crean recursos de nube desde aquí).
- Las llaves nunca salen por la API ni van a logs; la auditoría registra alta, cambios, borrado, asignación y enlaces creados (sin valores).
- Webhook por cuenta: se verifica SOLO con el secreto de eventos de esa cuenta; un evento de una cuenta no aprueba pagos de otra ni del formulario de Golden (y viceversa).
- Un formulario en `pruebas` nunca usa llaves de producción de una cuenta.
- Cada pago guarda `account_id`: reembolsos, conciliación, consulta de transacción y reintentos usan la cuenta con la que SE COBRÓ, aunque luego se reasigne el formulario.
- No se puede cambiar la cuenta de un formulario que ya tiene pagos reales o pendientes, ni borrar una cuenta que ya cobró (se desactiva); no se puede pasar una cuenta cobrada de pruebas a producción.

## Datos
Migración `0118_payment_accounts`: tabla `payment_accounts`, `web_forms.payment_account_id`, `form_payments.account_id` (todas nulas = comportamiento anterior, cuenta de Golden).

## Límites conocidos
- El método «QR» nativo de Wompi (Bancolombia QR) no tiene API verificada: el QR de esta pieza es el de la página del formulario o el del *Payment Link*.
- Los enlaces de pago no pasan por el formulario: su pago no crea inscripción (se ve en el panel de Wompi del titular).
- Pruebas: `tests/test_cuentas_cobro.py` (escritas; correrlas en la corrida completa con Postgres).
