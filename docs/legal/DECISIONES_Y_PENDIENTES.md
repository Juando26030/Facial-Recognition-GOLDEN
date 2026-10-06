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
