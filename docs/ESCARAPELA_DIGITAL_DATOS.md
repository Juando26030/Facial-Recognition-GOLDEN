# Escarapela digital: qué datos se ven

El enlace público `/b/<token>` (quien lo tiene ve la escarapela) entrega solo los datos que el evento permite.

- **Ajuste:** `events.digital_badge_fields` (migración `0099_digital_badge_fields`), lista JSON de claves. `NULL` = por defecto: solo los campos que usa la plantilla de escarapela, sin teléfono ni correo (misma regla que `certificates_public.py`).
- **Claves permitidas** (`app/digital_fields.py`): `role`, `entity`, `opt_1`, `categories`, los `opcional_N` rotulados del evento y, solo si se marcan expresamente, `phone` y `email`. Nombre y apellido salen siempre. Cualquier otra clave (incluida la cédula) se rechaza con 400.
- **Con lista:** se entregan exactamente esos campos (si el diseño usa uno no marcado, queda en blanco) y la página los muestra con su rótulo bajo el nombre (`extra_list`).
- **Parámetros > Escarapelas y certificados:** bloque «Datos que se ven en la escarapela digital», solo con la escarapela digital activa. Al marcar teléfono o correo aparece el aviso de que son datos personales visibles para quien tenga el enlace. Se guarda con el «Guardar» global (clave `dfields`).
- **API:** `GET/PUT /api/events/{id}/digital-badge-fields` (admin+, coordinador sí, comercial no; igual que el resto de la escarapela digital). Cada cambio queda en `audit_actions` (`edit` / `event_digital_badge_fields`, solo claves).
- **Cédula:** no es elegible. `person.id` sigue viajando solo para dibujar el QR de entrada de la escarapela, como antes.
