# Fase 8 · Turnos y filas

Decidido por Juan David (9-nov-2026). Módulo en **Parámetros → Zonas e inventario → Turnos y filas** (interruptor propio, columnas `events.queue_enabled` / `queue_config_json`; migración `0116_queue_turns`).

## Cómo funciona
- **Letras (filas)**: 1 a 8 letras A–Z con nombre opcional («A=Mesa 1, B=Mesa 2»). Los turnos son A1, A2… y se reparten por fila parejo (la persona nueva cae en la fila con menos esperando).
- **Orden**: `arrival` (por llegada: el turno se da al escanear el QR), `form` (orden de inscripción confirmada), `alpha` (apellido, nombre) y `manual` (Excel: Cédula, Orden, Fila; plantilla descargable; mismas defensas que las demás cargas: `variant_table.check_archive`, solo lectura, tope de filas).
- **Asignar** crea solo los turnos que faltan (nunca cambia un número ya dado). «Rehacer» borra únicamente los que siguen esperando/saltados.
- **Persona de prueba «PRUEBA»**: nunca recibe turno. **Menores**: nunca se muestra su nombre. **Cédulas**: no salen en ninguna pantalla pública ni en logs; el nombre en el celular solo si el evento lo activa.
- **Celular** (`/turno/{evento}`, sin login): la persona escribe su documento (POST, limitado por IP; **ojo:** responder «tu turno» o «aún no tienes turno» SÍ dice si esa cédula está acreditada en el evento: ver docs/seguridad/F5-9_B_publico.md, B-04) y recibe un enlace con token propio (`/turno/{evento}/{token}`) que muestra su turno, cuántos faltan y «Eres el A1, ya puedes seguir». Sondeo cada ~6 s con variación (sale de la memoria sin tocar la base mientras el estado tenga menos de 3 s), se frena con la pestaña oculta y se espacia si hay errores. Sin websockets.
- **TV** (`/kiosk/{evento}/turnos/tv`, con sesión del personal): turno llamado en grande por fila, últimos llamados, resalte y sonido opcional (hay que tocar «Activar sonido» una vez por política del navegador).
- **Consola** (`/kiosk/{evento}/turnos`): Llamar siguiente (con puesto opcional), Repetir, Saltar, Volver a la fila, QR para imprimir. Llamar cierra el turno que ese mismo funcionario tenía abierto en la fila. `FOR UPDATE SKIP LOCKED` evita que dos puestos llamen al mismo.

## Carga en la nube (regla «nada frecuente toca la base»)
El estado del evento se calcula una vez cada 3 s por proceso (`queue_svc.snapshot`) y se reparte desde memoria a todos los celulares y TVs; cada cambio local lo invalida. Con varios procesos, un cambio tarda como máximo 3 s en verse en los demás.

## Permisos
Configurar: coordinador+ (comercial excluida). Operar: digitador+ con acceso al evento y evento «en proceso» (también respeta el arriendo a servidor local). Rutas públicas bajo `/turno/` (agregadas a `appmode.PUBLIC_PREFIXES`).

## Lo que NO se probó
No se pudo correr pytest ni la base aquí: se verificó compilación, ruff, `node --check` y parseo de plantillas; `tests/test_turnos.py` corre en el CI. No se probó en un teléfono real ni con la TV. El export/import de eventos entre entornos **no** lleva los turnos. Pendiente si se quiere: QR por escarapela que abra el turno directo (hoy la persona escribe su documento).
