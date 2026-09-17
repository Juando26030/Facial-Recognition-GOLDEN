# QA Handoff — todo lo nuevo desde la última pasada de QA

**Para:** quien vaya a probar esto en local (persona o agente).
**Rama:** `sprint2/reverify-fixes-and-badges` (NO está mergeada a `main` — no mergear sin aprobación explícita de Juan David después de que él la pruebe).
**Rango:** desde `33fed6e` ("ronda 2 de QA sobre Sprint 2.3", la última vez que alguien probó esto en serio) hasta `a90cd86` (HEAD actual).
**Tamaño:** 18 commits, 48 archivos, ~3000 líneas nuevas, 9 migraciones nuevas (`0015` a `0023`).

## Lo más importante antes de empezar

Todo lo de este documento fue **verificado con `TestClient` (FastAPI, contra SQLite con `PRAGMA foreign_keys=ON`), sweeps de render Jinja, `node --check` sobre el JS, y en el caso del reporte Excel, abriendo el `.xlsx` real con `openpyxl`** — más de 250 aserciones automatizadas en total, todas en verde a la fecha de este documento.

**Ninguno de estos cambios se vio en un navegador real.** El panel de navegador integrado de esta sesión rechazó conectarse a `localhost` durante toda esta ronda (un bloqueo de permisos del entorno, no del código) — así que aunque la lógica está verificada exhaustivamente, **nadie ha visto con sus propios ojos cómo se ve/siente ninguna de estas pantallas nuevas**. Esa es la razón de ser de esta pasada de QA: mirar con ojos humanos lo que el testing automatizado no puede.

## Cómo levantar el entorno

```bash
git checkout sprint2/reverify-fixes-and-badges
pip install -r requirements.txt
alembic upgrade head   # trae las 9 migraciones nuevas: 0015 (teléfono staff) a 0023 (tipo de registro)
uvicorn app.main:app --reload --port 5000
```

Si la base ya existía desde antes de `33fed6e`, `alembic upgrade head` va a aplicar de una las 9 migraciones nuevas sin pedir nada — ninguna necesita un paso manual. La migración `0017_staff_phone_unique` sí hace un `UPDATE` real sobre datos existentes (limpia teléfonos duplicados o vacíos antes de poner la restricción `UNIQUE`) — no es destructiva, pero vale la pena avisar que toca filas existentes, no solo el esquema.

---

## 1. Rol "comercial" (nuevo, de cero) — Fases 0, 1, 4, 5, 6

Un rol nuevo, entre `coordinador` y `admin` en jerarquía. Hereda casi todo el acceso operativo de `coordinador` (editar evento/cliente, ver Estadísticas/Reporte, cambiar estado), pero:
- **Puede** crear clientes/eventos y cuentas `cliente` (privilegios NUEVOS que `coordinador` perdió).
- **NO puede** crear cuentas `digitador`.
- **NO puede** ver ni usar Adjuntar Base de Datos, Escarapelas, ni Parámetros del Evento — ni el link, ni la página por URL directa, ni el endpoint si se llama a mano (`TESTING.md` §22, §28).
- Sigue viendo Usuarios del Evento (solo para crear `cliente`, nunca `digitador`) y Estadísticas.

**Qué mirar:** crear una cuenta `comercial` desde Staff, loguearse con ella, confirmar visualmente que las 3 tarjetas bloqueadas de verdad no aparecen en la pantalla de selección del evento (no solo que dan 403 si se fuerza la URL).

## 2. Doble rol coordinador+comercial (nuevo) — Fase 15

Un admin puede, desde Staff, marcar a una cuenta `coordinador` como también `comercial` (o viceversa) — es el ÚNICO par de roles combinable. Esa persona debe ver/poder TODO lo que ve un `coordinador` normal (incluyendo lo que un `comercial` puro tiene bloqueado) más los privilegios extra de `comercial` (crear tenant/evento, reasignar la comercial de un evento).

**Qué mirar:** asignar el doble rol desde Staff (botón "+ También comercial"), loguearse con esa cuenta, y confirmar que ve Escarapelas/Adjuntar BD/Parámetros (que un comercial puro NO ve) — es el caso más fácil de romper por accidente si se toca algo de permisos después.

## 3. Teléfono obligatorio y único para staff — Fase 4

Crear una cuenta `coordinador`/`comercial`/`admin` ahora exige teléfono, y no puede repetirse entre cuentas. `digitador`/`cliente` (cuentas temporales) siguen sin necesitarlo.

**Qué mirar:** el formulario de "Nueva cuenta" en Staff pide teléfono con `required`; intentar crear dos cuentas con el mismo teléfono debe fallar con un mensaje claro.

## 4. Comercial asignada a eventos + filtros de pertenencia — Fase 5

Al crear un evento, además del coordinador se asigna una "comercial" (se autoasigna si quien crea es comercial; admin+ tiene que elegir). En `/eventos` y `/calendario`: una comercial ve un toggle "Mis eventos"/"Todos"; admin+ ve selectores para filtrar por cualquier comercial o coordinador.

**Qué mirar:** crear un evento como comercial (se autoasigna) y como admin (obliga a elegir); probar los filtros en Eventos y Calendario con distintas cuentas.

## 5. Módulo de Calendario, de cero — Fases 8, 12, 14

`/calendario` pasó de ser un placeholder a un calendario funcional:
- Vistas Mes (por defecto)/Semana/Día, con navegación `←`/`→`/"Hoy".
- Cada evento se ve como una tarjeta de color — **el color es el "de pañoleta" que se le asignó al evento**, no un color por estado (ver punto 7).
- Clic en un evento abre un modal: editar todos sus campos (incluido el color de pañoleta y el estado) O pulsar "🚪 Ingresar al evento" para entrar al kiosko directo.
- Recordatorios libres por día ("+ recordatorio"), con buscador de destinatarios (lista desplegable + texto libre, elegir varios) — si no se elige a nadie, es visible para todo el equipo; si se elige gente puntual, solo esas personas (+ quien lo creó) lo ven en su propio calendario. `cliente`/`digitador` nunca pueden ser destinatarios.
- Mismos filtros de pertenencia que Eventos (punto 4).

**Qué mirar (lo más nuevo de todo el sprint, dale tiempo):** crear un evento con fechas que abarquen varios días y confirmar que aparece en cada día correspondiente, incluso cruzando de un mes a otro; probar las 3 vistas; crear un recordatorio dirigido a una persona específica y confirmar (con otra sesión) que nadie más lo ve; entrar a un evento por el botón "Ingresar" desde el modal.

## 6. Corrección de bugs de acreditación por cédula — Fase 3

- El "modo autoregistro" apagado ahora sí deja a alguien en blanco ("No registrado") tras un escaneo de cédula con match exacto, con un botón inline "✅ Acreditar" en esa misma fila — antes (bug real) se acreditaba solo, ignorando el switch.
- El matching de nombre por cédula no encontrada ahora funciona en ambos sentidos (antes solo funcionaba si el nombre escaneado era MÁS CORTO que el de la base; el caso reportado era al revés — escaneo largo, base corta).
- Los formularios flotantes (Editar persona, Registrar nueva) ya NO se cierran al hacer clic afuera — solo con Guardar/Cancelar.
- Botón "🧹 Limpiar filtros" en Registro.
- Avisos de "ya registrado"/"ya impreso" ahora dicen cuántas veces pasó antes.

**Qué mirar:** con autoregistro apagado, escanear una cédula de alguien ya cargado y confirmar que queda en blanco hasta pulsar "Acreditar"; hacer clic afuera de un formulario abierto y confirmar que NO se cierra.

## 7. Color de pañoleta + contraste automático de texto — Fase 12

Cada evento tiene un "Color de pañoleta" (selector de color nativo, con gotero, más un nombre libre tipo "Rojo Golden"). El Calendario colorea sus tarjetas por ese color, no por estado. Además, en toda la app, el texto sobre un color de acento personalizado (Configuración) o sobre un chip de pañoleta se pone automáticamente blanco o negro según qué tan claro/oscuro sea el color, para que siempre se lea bien.

**Qué mirar:** elegir un color de pañoleta bien oscuro y uno bien claro para dos eventos distintos y ver que el texto del chip en el Calendario se lea en ambos casos; en Configuración, elegir un color de acento muy claro (ej. amarillo pastel) y confirmar que el texto de los botones se ve negro, no blanco ilegible.

## 8. Reporte Excel, rediseñado por completo — Fase 16

El reporte dejó de tener el formato fijo/legacy (columnas como "Tipo_Pago", "usuario") — ahora:
- Solo trae columnas con al menos un dato real cargado en ese evento (si nadie tiene correo, no sale la columna Correo).
- Los campos opcionales usan su nombre real ("Talla de Camisa"), no "Opcional 1".
- Siempre trae "Tipo de Registro" (Tradicional / Autoregistro / Biométrico / QR — según cómo se acreditó cada persona) y la hora exacta CON segundos.
- Formato de Excel de verdad: 3 filas de título arriba (Cliente/Cuenta, Evento, Código), encabezados con estilo, autofiltro activo en cada columna, ancho de columna ajustado.

**Qué mirar:** exportar el reporte de un evento con gente registrada por distintos métodos (facial, cédula con y sin autoregistro, alta manual) y confirmar que "Tipo de Registro" es correcto en cada fila; abrir el Excel y confirmar que el filtro automático funciona en los encabezados.

## 9. Permisos ampliados a coordinador + botón único — Fase 11

- `coordinador` ahora puede eliminar un asistente de un evento y cambiar su estado registrado/no-registrado (antes solo `admin`+).
- El cambio de estado ya no tiene un botón "Aplicar" aparte — viaja junto con el resto de cambios en el único "Guardar cambios" del modal de Editar.
- `cliente` ya no puede exportar el reporte (sigue viendo Estadísticas/gráficos).
- El estado de un evento (Creado/En Proceso/Finalizado) ahora se puede cambiar también desde `/eventos` y desde el Calendario, no solo entrando a la tarjeta del cliente.

**Qué mirar:** con una cuenta `coordinador` (no admin), confirmar que puede eliminar/cambiar estado de un asistente; confirmar que `cliente` no ve el botón de exportar ni puede llamarlo directo.

## 10. Autoimpresión — bug real corregido — Fase 13

La autoimpresión **no estaba funcionando en absoluto**: internamente, cualquier impresión (automática o manual) pasaba por un aviso de "¿ya se imprimió antes, seguro quieres repetir?" — un modal que en el flujo automático nadie está mirando para confirmar, así que la impresión automática se quedaba esperando para siempre sin abrir nada. Corregido: la autoimpresión nunca pregunta nada, solo el botón manual de impresión sigue avisando si ya se había impreso antes. También se agregó autoimpresión al cambiar el estado de alguien a "Registrado" manualmente (antes solo disparaba con un escaneo).

**Qué mirar — este es el más importante de probar en la práctica real:** con autoimpresión activada y autoregistro TAMBIÉN activado, escanear a alguien y confirmar que se acredita e imprime sola, sin ningún diálogo. Con autoimpresión activada pero autoregistro apagado, cambiar el estado de alguien a "Registrado" desde el modal de Editar y confirmar que también imprime sola.

## 11. Imagen que no aparecía en la vista previa de impresión — Fase 13

Una escarapela con una imagen (logo/fondo) se veía bien en pantalla, pero la imagen no aparecía en la vista previa de impresión del navegador (Ctrl+P). Corregido usando `img.decode()` en vez de solo esperar el evento `load`.

**Qué mirar:** diseñar una escarapela con una imagen fija, imprimir a alguien, y revisar la VISTA PREVIA de impresión del navegador (no solo la pantalla antes de imprimir) — la imagen debe aparecer ahí también.

## 12. Correcciones de UI menores — Fase 10

- El link a Configuración estaba oculto para todo el mundo salvo admin en el menú lateral, aunque la página en sí ya era de acceso libre — bug real, corregido.
- El selector de tipografía en Configuración muestra cada opción en su propia fuente (antes había que aplicarla para verla).
- Nuevo evento precarga País=Colombia/Ciudad=Bogotá (editable).
- Buscador de eventos dentro de la tarjeta de cada cliente (para clientes con muchos eventos).
- "Clientes" pasó a llamarse "Clientes - Cuentas" en toda la app (sidebar, títulos, franjas de contexto) — el rol de cuenta `cliente` (el que usan los invitados de un evento para loguearse) NO cambió de nombre, son dos conceptos distintos.

---

## Dónde mirar el detalle exacto de cada caso

`TESTING.md` tiene el checklist completo, caso por caso, con pasos y resultado esperado — las secciones nuevas de esta ronda son:

| Sección | Tema |
|---|---|
| 22–24 | Rol comercial (Fase 0), ajustes de UI (Fase 1), rediseño de cédula (Fase 2) |
| 25 | Batch de correcciones: nombres, modales, autoregistro, filtros, duplicados (Fase 3) |
| 26 | Teléfono obligatorio y único (Fase 4) |
| 27 | Comercial asignada a eventos + filtros (Fase 5) |
| 28 | Ocultar funciones operativas para comercial (Fase 6) |
| 29 | Unicidad de cédula (Fase 7) |
| 30 | Módulo de Calendario (Fase 8) |
| 31 | Fuente Agrandir por defecto (Fase 9) |
| 32 | Correcciones de UI (Fase 10) |
| 33 | Permisos ampliados + botón único + estado desde Eventos/Calendario (Fase 11) |
| 34 | Color de pañoleta + contraste automático (Fase 12) |
| 35 | Bug de autoimpresión + imagen en vista previa (Fase 13) |
| 36 | Destinatarios en recordatorios del Calendario (Fase 14) |
| 37 | Doble rol coordinador+comercial (Fase 15) |
| 38 | Reporte Excel rediseñado (Fase 16) |

`CLAUDE.md` tiene, en las mismas secciones (buscar "Fase 0" a "Fase 16" dentro de "Sprint 2.4"), la explicación técnica de CÓMO se implementó cada cosa y CUÁLES fueron los bugs reales encontrados en el camino (hay 4 bugs reales documentados ahí que no fueron pedidos explícitos, sino cosas que se rompían: el print-log al renombrar una cédula, la autoimpresión, la imagen en la vista previa, y el reporte con un evento vacío).

## Fuera de alcance de esta ronda (no tocado, no probar como si fuera nuevo)

- La fuente Agrandir (Fase 9) ya estaba en una ronda anterior a esta lista de 18 pedidos, pero se incluye en el rango de commits — si ya se había revisado, se puede saltar.
- El módulo de notificaciones por WhatsApp (Cloud API) mencionado en un plan mucho más viejo de este sprint sigue sin empezar — no está en ningún commit de este rango.
- QR como método de check-in sigue siendo "Próximamente" (el valor "QR" en Tipo de Registro del reporte está listo para cuando exista, pero el escaneo QR en sí no está implementado).
