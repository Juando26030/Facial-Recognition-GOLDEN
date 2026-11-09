# Ronda de seguridad de las Fases 5 a 9 (9-nov-2026) · Resumen

Revisión adversarial de código de todo lo que no está en producción (`2c8c4d7..f5/integracion`), en cinco áreas, con arreglos integrados en `f5/integracion`. **Nada se ha probado con base de datos todavía**: las pruebas nuevas corren en la suite completa de Cloud Shell (11-nov). Detalle con archivo, línea, escenario y prueba en cada informe:

| Área | Informe | Arreglado | Abierto (decisión) |
|---|---|---|---|
| A · Servidor local y traspaso de eventos | [`F5-9_A_servidor_local.md`](F5-9_A_servidor_local.md) | 5 altas, 8 medias (incluida D5), 1 baja | A-08 (hash de cuentas activas a todo nodo), alcance del token por cliente, A-14, A-15, A-16, A-17 |
| B · Lo que ve internet sin sesión | [`F5-9_B_publico.md`](F5-9_B_publico.md) | 1 alta (B-01 autoregistro con cédula ajena) + B-02, B-07…B-11 | B-03, B-04, B-05, B-06; B-12 aceptado por diseño |
| C · Dinero (Wompi multicuenta, facturado) | [`F5-9_C_pagos.md`](F5-9_C_pagos.md) | 1 alta (C1, **también presente en producción**), 2 medias, 3 bajas | Verificación de webhooks de terceros, re-cifrado de llaves, `merchant.public_key` en sandbox |
| D · Fase 5 y panel interno | [`F5-9_D_eventos.md`](F5-9_D_eventos.md) | 1 alta (D1 almacén/contabilidad veían asistentes), 1 media, 2 bajas | D5 resuelto por A |
| E · Plataforma, operaciones, despliegue y migraciones | [`F5-9_E_plataforma.md`](F5-9_E_plataforma.md) | 1 alta (E-1 alertas silenciables), 4 medias, 4 bajas | Permisos BigQuery, llave de pagos en `publico`, alertas solo super_admin; correo personal en la migración 0119: **resuelto** (ya no está en el código) |

## Lo más grave que se arregló
1. **C1 (alta, existía en producción):** la confirmación de pago aceptaba una transacción de Wompi de **otro comercio** con la misma referencia y monto → inscripción aprobada sin que el dinero llegara. Ahora solo vale la transacción del comercio que cobró. **Producción sigue con el código viejo hasta el despliegue**; mientras tanto, cotejar los pagos con el panel de Wompi.
2. **B-01 (alta):** el autoregistro con la cédula de otra persona marcaba su ingreso, podía borrarle el rostro (fecha de menor) o cambiarle el correo y llevarse su credencial digital.
3. **D1 (alta):** cuentas solo de almacén o contabilidad veían el directorio completo de asistentes.
4. **A-01…A-05 (altas):** exportar biometría (ahora solo super_admin), descargar exportaciones ajenas, permisos de `C:\GoldenLocal` (escalada a SYSTEM), actualizador que confiaba en un archivo local, token de nodo que bajaba cualquier evento.
5. **E-1 (alta):** un admin podía apagar la alerta de borrado y borrar sin rastro.

## Decisiones pendientes de Juan David (agrupadas)
- **Quiosco y público:** B-03 (sesión completa de digitador en la pantalla de autoregistro: candado de autoservicio o rol «kiosco»), B-04 (la consulta de turno por cédula revela si alguien está acreditado), B-05 (enlace propio para la TV en vez de reutilizar el de estadísticas), B-06 (el expositor puede escribir cédulas sin que la persona muestre su código).
- **Pagos de terceros:** confirmar con Wompi cada aviso de pago de cuentas de terceros; re-cifrado al rotar la llave; `publico` puede descifrar llaves privadas (separarlas exige otra llave).
- **Servidor local:** hash de todas las cuentas activas a cualquier nodo; nodos sin alcance por cliente; app como SYSTEM y cortafuegos abierto a la subred; paquete de actualización sin firma propia; liberación forzada desde la nube sin todo subido.
- **Plataforma:** permisos de BigQuery para la cuenta del Job de operaciones; ¿la configuración de alertas solo para super_admin?
