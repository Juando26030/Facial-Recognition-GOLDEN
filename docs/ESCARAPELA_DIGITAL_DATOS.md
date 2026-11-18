# Escarapela digital: qué datos se ven

El enlace público `/b/<token>` (quien lo tiene ve la escarapela) entrega solo los datos que el evento permite.

- **Ajuste:** `events.digital_badge_fields` (migración `0099_digital_badge_fields`), lista JSON de claves. `NULL` = por defecto: solo los campos que usa la plantilla de escarapela, sin teléfono ni correo (misma regla que `certificates_public.py`).
- **Claves permitidas** (`app/digital_fields.py`): `role`, `entity`, `opt_1`, `categories`, los `opcional_N` rotulados del evento y, solo si se marcan expresamente, `phone` y `email`. Nombre y apellido salen siempre. Cualquier otra clave (incluida la cédula) se rechaza con 400.
- **Con lista:** se entregan exactamente esos campos (si el diseño usa uno no marcado, queda en blanco) y la página los muestra con su rótulo bajo el nombre (`extra_list`).
- **Parámetros > Escarapelas y certificados:** bloque «Datos que se ven en la escarapela digital», solo con la escarapela digital activa. Al marcar teléfono o correo aparece el aviso de que son datos personales visibles para quien tenga el enlace. Se guarda con el «Guardar» global (clave `dfields`).
- **API:** `GET/PUT /api/events/{id}/digital-badge-fields` (admin+, coordinador sí, comercial no; igual que el resto de la escarapela digital). Cada cambio queda en `audit_actions` (`edit` / `event_digital_badge_fields`, solo claves).
- **Cédula:** no es elegible. `person.id` sigue viajando solo para dibujar el QR de entrada de la escarapela, como antes.

## Misma plantilla que la escarapela física (19-nov-2026)
La digital pinta la plantilla de la física con el mismo motor (`static/js/badge-render.js`): variables, textos, posiciones y el QR. Lo único que cambia es el QR: en la digital lleva el **código dinámico** (cada 30 s), nunca la cédula, envuelto en el modo que elija el diseño del QR (vCard con sus campos, MECARD, enlace a la tarjeta o solo el código; el lector de Golden saca el código de cualquiera de los cuatro). Si el diseño no tiene QR, se sigue usando la caja de QR de entrada de abajo.
- Los campos que pide el QR (empresa, cargo, teléfono, correo, categoría) cuentan como usados por la plantilla; teléfono y correo siguen la regla de siempre: solo salen si el evento los marca en «Datos que se ven en la escarapela digital».
- La variable «Código de la persona» se entrega cuando el evento usa código y la plantilla la usa. El modo «enlace» agrega `person.card_url` (tarjeta pública; solo muestra datos de quien aceptó compartirlos).
- El pase de Wallet no cambia (su vCard sigue la regla de `digital_badge_fields`).
