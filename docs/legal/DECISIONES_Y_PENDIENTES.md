# Decisiones y pendientes del bloque legal del piloto (GoldenWeb 2.0)

> Documento vivo. Los textos de la auditora están en `TEXTOS_AUDITORA_2026-10-05.md` (literales, sin editar).

## Texto para pegar en la descripción del proyecto y en el «About» de GitHub (lo pega Juan David)

**Descripción larga (proyecto en Claude):**

> GoldenWeb 2.0 es la plataforma de gestión de identidades y acceso de Golden Eventos y Logística S.A.S. para eventos presenciales: inscripción, acreditación y control de acceso por cédula, QR o reconocimiento facial voluntario, escarapelas, certificados, control de áreas e inventario, formularios web con pagos y reportes. Está hecha con FastAPI y PostgreSQL (Neon) sobre Cloud Run, y funciona también sin conexión a internet gracias a un modo de contingencia en el quiosco. Es privada por diseño (Ley 1581 de 2012): el rostro solo se usa con la autorización explícita de la persona, registrada de forma inmutable; los menores de edad quedan fuera del reconocimiento facial; lo biométrico se borra a los 7 días de finalizado el evento; y cada persona puede revocar su autorización o pedir la supresión de sus datos.

**«About» de GitHub (una línea):**

> Plataforma de gestión de identidades y acceso para eventos con reconocimiento facial voluntario, modo sin conexión, consentimiento explícito y borrado a 7 días (FastAPI, PostgreSQL/Neon, Cloud Run).

**Temas (topics) sugeridos:** `fastapi`, `postgresql`, `cloud-run`, `facial-recognition`, `access-control`, `data-protection`, `offline-first`.

## Backlog nuevo (SIN implementar)

1. **Tarea de operaciones `export-person-data`** (golden-ops): dada una cédula, lista QUÉ datos hay de esa persona (tablas y conteos, y un archivo con el contenido) para atender una consulta de habeas data. Igual que `export-consent`: el resultado y el log llevan solo conteos y la clave del archivo, nunca la cédula.
2. **Bandera «reclamo en trámite»** sobre el dato de una persona: se activa en máximo 2 días hábiles desde el reclamo; mientras está activa el dato no se suprime por la purga ordinaria y se muestra la leyenda; se desactiva al resolverse el reclamo.
3. **`audit-consent-purge`** (después del piloto): cómo purgar `audit_consent_logs` a los 3 años con el disparador de solo inserción: tarea de operaciones que corre con el rol dueño (nunca el de la app), desactiva el disparador SOLO dentro de su transacción (`ALTER TABLE … DISABLE TRIGGER`), borra los registros con más de 3 años y deja constancia del conteo; requiere confirmación de la auditora sobre el plazo exacto y sobre el identificador (cédula) que hoy se conserva.
4. **L7** (después del piloto): purga ordinaria de datos personales a los 90 días del cierre del evento (no toca pagos ni consentimientos).
5. **Modo A de un tercero con anexo firmado y fotos previas** (después del piloto).

## Decisiones tomadas

- Evento del piloto: propio de Golden (`controller_mode=golden`, variante 2, sin anexo).
- Dos caminos que pueden mezclarse en el mismo evento: A (cédula/QR → pantalla → clic → captura en vivo → vector por tarea) y B (`/aceptar/<evento>`, aceptación previa desde el celular).
- Sin aceptación registrada de la persona no se usa su rostro; el vector no se calcula antes de aceptar (precálculo solo con anexo firmado, solo super_admin).
- Sin coincidencia en el quiosco: no se guarda nada y se muestra el mensaje de la auditora.

## Decisiones técnicas tomadas (2026-10-06, criterio del consultor; Juan David decide solo el flujo de negocio)

- **Vector después de aceptar, siempre.** Carga masiva y alta en el quiosco guardan la foto cifrada y NO calculan el vector; se calcula por tarea (`app/enroll.py`) cuando la persona acepta (pantalla en puerta o `/aceptar`). Única excepción: evento de un tercero con pre-cálculo autorizado por un super_admin (anexo firmado). Una foto sin vector se borra igual a los 7 días (el reloj corre desde que se guarda).
- **La puerta nunca espera.** El vector se calcula aparte; mientras tanto la persona entra por cédula o QR.
- **Aceptación desde el celular = «por verificar».** No sirve para el reconocimiento hasta que el personal confirme la identidad en puerta con el documento o el QR. Código personal por correo: recomendado solo si el listado del organizador trae correos reales; no implementado.
- **Cola local de ingresos a 7 días.** Aviso amarillo desde el día 3 y rojo desde el 6; a los 7 se elimina automáticamente (texto C''') con un aviso visible, nunca en silencio. La bandeja de salida de R1 (`producto/piloto`) tenía «caducada: solo descarta una persona»: al integrar se ajusta para que a los 7 días se elimine solo, con aviso.
- **Cifrar la cola de ingresos (costo, sin implementar):** AES-GCM con clave no extraíble guardada en IndexedDB (la misma técnica de R1); el `client_id` queda en claro (llave de no duplicación) y huella, nombre, hora y método van cifrados. Cerca de 1 día con pruebas; riesgo bajo; el roster no se cifra (decisión de Juan David).
- **Clave facial obligatoria en producción:** sin `FACE_ENCRYPTION_KEY` la aplicación no arranca y no se escribe nada biométrico (falla cerrado). El bootstrap de producción ya crea el secreto `golden-face-encryption-key`.
- **Regla de borrado:** «sigue en otro evento abierto» solo cuenta donde la persona aceptó; si nunca aceptó en ninguno cuentan todos los suyos; tope de 180 días intacto. `/sistema` avisa de eventos cuyo fin pasó hace más de 3 días y siguen sin finalizar.
- **Verificar al integrar (R1):** la bandeja de salida de R1 debe quedar sin fotos ni vectores (cumple C''') y con el cifrado AES-GCM de las inscripciones nuevas.
