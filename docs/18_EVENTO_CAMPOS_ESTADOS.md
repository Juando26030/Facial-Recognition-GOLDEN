# Formulario del evento configurable, estados con reglas e inventario ligado (diseño)

Origen: pantallazos del software anterior (2026-10-05) y las decisiones de Juan David. Meta: **replicar todo lo que el software anterior tenía en la ficha del evento**, pero con los campos
diseñados por un administrador en Configuración (como el diseñador de formularios web, sin la parte pública), estados con reglas, historial de cambios para los correos y recursos ligados al inventario.

## 1. Lo que tiene la ficha del evento hoy (software anterior)
**Datos generales:** Código · Nombre · Tipo (lista: «Congreso», …) · Estado (lista: «Creado», …) · Factura · Valor · Comentarios · Comercial (usuario) · Coordinador (usuario o «[Por Asignar]») ·
Fecha Inicio · Fecha Fin · Fecha Montaje · Hora Montaje · Hora Inicio Registro · Hora Fin Registro · País · Ciudad · Dirección · Lugar · Observaciones · Campos a capturar en registro ·
Adicionales en evento.

**Recursos (tabla por día):** Fecha · Jornada (lista: «Full», …) · Comentario · R Conve · R Bidi · R Touch · R Ipad · Controles · Impresoras · Semáforos · Protocolos (cantidades), con editar y borrar por
fila (ej. «IMPRESORA TERMICA DE STICKER», varios días).

**Logística y contactos:** Ubicación Puntos · Número Puntos · Tipo Impresión (lista: «Local», …) · Nombre Impresora (ej. «Brother QL-710W») · Logo (archivo) · Sitios a controlar · Hora Entrega BD (fecha) ·
Patrón Emails (lista de dominios separados por coma) · Cuenta CRM · Contacto · Teléfono · Contacto Evento · Mail · Requerimiento materiales · Tipo Uniforme · Color Pañoleta (color) · Color Pañoleta Texto ·
Cintas · % Mínimo Asistentes · Número de Grupos · Link descarga memorias.

**Interruptores (sí/no):** Tomar Foto/Firma/Huella · Contar Acompañantes · Registrar Acompañantes · Maneja Grupos · Manejo Costo Evento · Pago en Evento · Hay Entrega Productos · Marca de Agua Digital ·
Refrigerio Empresa · Hay Parqueadero · Hay Seguridad · Pagos Online.

**Indicadores de calidad:** Estado (lista: «Sin Novedad», …) · Referencia (lista: «Staff», …) · Descripción. **Texto Habeas Data** (texto con formato).

## 2. Qué ya existe en el sistema nuevo y qué es nuevo
- **Ya existe** (columnas de `events`): código, nombre, lugar, dirección, país, ciudad, fechas de inicio/fin/montaje, horas de evento y de montaje, observaciones/notas, estado (creado, en_proceso,
  finalizado), coordinador, comercial, color de pañoleta (con nombre), logo (propio/oculto), categorías, y los módulos que se prenden en Parámetros (certificados, escarapela digital, control de áreas, inventario,
  autoimpresión y autoregistro).
- **Falta** casi todo el resto de la lista: tipo, factura, valor, comentarios, adicionales, recursos por día, logística y contactos, interruptores y calidad, Habeas Data por evento.

## 3. Diseño: ficha del evento diseñada por el administrador
- **Dos clases de campos.** (a) **Núcleo**: los que el sistema usa para decidir cosas (código, nombre, estado, fechas, coordinador, comercial, ciudad…): siempre están, el administrador solo cambia su etiqueta, su
  orden y si son obligatorios. (b) **Campos de la ficha**: los demás; el administrador los crea, ordena, agrupa en secciones, marca obligatorios y define su tipo, sin programar.
- **Tipos de campo:** texto corto y largo, número, dinero, fecha, hora, lista desplegable (con sus opciones), sí/no, color, correo, teléfono, archivo, texto con formato, usuario del sistema (comercial,
  coordinador, almacén, contabilidad), y **tabla de líneas** (para «Recursos»).
- **Dónde se guarda:** el diseño (secciones, campos, tipos, opciones, reglas de visibilidad) en un documento por instalación (el mismo motor del diseñador de formularios web, SIN la parte pública); los valores de
  los campos que no son núcleo en `events.extra_json`, y las tablas de líneas en tablas propias. No hace falta una migración nueva cada vez que se agrega un campo.
- **Se muestra en TODOS los sitios** que hoy leen el evento (alta, edición, calendario, detalle, informe), a partir del mismo diseño: un campo nuevo aparece donde el administrador decida («mostrar en el
  calendario», «mostrar en el informe»).
- **Campos a capturar en registro** (los de las personas) siguen siendo los «Parámetros del evento» que ya existen; la ficha solo los resume.

## 4. Estados del evento con reglas
- Hoy hay tres estados fijos con comportamiento fijo. Pasan a ser una **lista configurable** (nombre, orden, color), con los tres actuales como base.
- **Cada estado lleva reglas** que prenden o apagan cosas del evento mientras está en ese estado: el cliente tiene acceso o no; el cliente puede o no descargar estadísticas; pueden o no entrar los digitadores
  temporales; se puede o no usar la ruleta, el registro, el registro touch, el control de áreas, el control de inventario del evento, los certificados, etc. La regla efectiva sale del estado actual (y los
  interruptores propios del evento siguen mandando cuando son más restrictivos).
- **Compatibilidad:** `creado / en_proceso / finalizado` conservan su significado actual (la retención biométrica y «registrar solo en proceso» siguen dependiendo de ellos): cada estado nuevo declara con cuál
  de los tres se comporta para esas reglas.

## 5. Historial de cambios y correos
- Cada campo de la ficha tiene una casilla **«llevar historial de cambios»**. Los marcados guardan quién, cuándo, qué había y qué hay ahora, y son los únicos que generan correo.
- **Correo** (por cambios en campos clave): «El evento [código] de nombre [nombre] del cliente [cliente] tuvo los siguientes cambios: [antes → ahora por campo]». Destinatarios: comercial, coordinador, encargado de
  almacén del evento (campo nuevo) y la cuenta de **contabilidad** (rol nuevo, un usuario asociado a cada evento). Varios cambios seguidos se juntan en un solo correo (no uno por clic en Guardar).

## 6. Recursos del evento ↔ inventario
- Los renglones de «Recursos» (R Conve, R Bidi, R Touch, R Ipad, Controles, Impresoras, Semáforos, Protocolos…) pasan a ser **tipos de equipo del catálogo de inventario** (por cantidad, serie opcional) y cada
  línea es una **reserva** por día y jornada. Al guardar, el sistema descuenta del inventario del día en la ciudad del evento; si no alcanza avisa y no deja seguir hasta conseguirlo o alquilarlo.
- Reglas de tu respuesta: bodega principal en Bogotá; los equipos pueden estar en cualquier ciudad; **1 día** de anticipación si el equipo está en la ciudad del evento y alerta de **1 semana** si está en otra.

## 7. Registro touch
Una sección nueva en el menú del evento, al lado de Registro y Ruleta: **«Registro touch»**, pensada para pantallas táctiles (también 16:9 y módulos touch, vertical u horizontal, y responsive): botones y campos grandes,
teclado en pantalla propio para cédula y nombre, sin menús pequeños ni acciones con el mouse, y el mismo flujo de registro por debajo.

## 8. Orden de construcción
1. Estados configurables con reglas (se apoya en lo que ya existe) y el historial de cambios.
2. Diseñador de la ficha del evento + todos los campos del software anterior cargados como diseño inicial.
3. Correos por cambios y rol de contabilidad.
4. Recursos ligados al inventario con reservas.
5. Registro touch (puede ir en paralelo).

## 9. Decisiones de Juan David (2026-10-05, respuestas a las preguntas)
1. **Tipo de evento:** una lista que el administrador puede ampliar a su gusto desde el propio formulario (sin código).
2. **Estados:** los crea el administrador, los que quiera, y a cada uno le adjunta sus reglas (sección 4).
3. **Jornada:** «Full» o «Medio día»; además cada línea lleva hora de inicio y hora de fin.
4. **«Tipo de impresión»: se elimina.** Juan David arma la ficha: el sistema solo ofrece crear y ordenar campos (no hay que precargar el contenido del software anterior salvo lo que él decida).
5. **Inventario con categorías obligatorias (sección 10).**
6. **«Campos a capturar en registro»:** se puede elegir de una lista (los campos de la persona) o escribir más detalle.
7. **Habeas Data:** se ignora (no se trabaja ahora).
8. **Multiimpresión (sección 11).**

## 10. Inventario con categorías (regla central)
**Catálogo de equipos** (lo que maneja la empresa; Juan David lo puede ampliar): computadores, impresoras QL, impresoras negras, pañoletas (por color), corbatas (por color), lectores bidimensionales, fundas de
escarapela (por tamaño: 12 o 16 mm), cintas (por tamaño: 12 o 16 mm, y por color), cordones (por color). Cada tipo declara sus **atributos categorizables** (color, tamaño…) con **valores predefinidos** que se
eligen con botones u opciones, nunca escribiendo texto («300 fundas de 12 mm y 200 de 16 mm», no «200 escarapelas azules» en un campo libre): así los datos siempre son iguales y se pueden contar.
- **Cantidad total** por tipo en la ficha del evento (la comercial pone, por ejemplo, 500 fundas). Una opción avanzada («categorizar») permite repartir esas 500 por los atributos del tipo (todas iguales, o
  por tamaño y/o color, combinando atributos).
- **Regla de cuentas:** al categorizar, la suma de las categorías debe ser EXACTAMENTE el total (500, no 499 ni 501); el sistema lo calcula en vivo y no deja guardar una distribución que no cuadre.
- **Estado del evento:** mientras esté en `creado` se puede dejar sin categorizar; **para pasar a `en_proceso` todo el inventario del evento debe estar categorizado y cuadrado**, y el sistema dice qué falta.
- **Disponibilidad (docs/16, N5):** al guardar descuenta del inventario del día en la ciudad del evento; si no alcanza avisa y no deja continuar hasta conseguirlo o alquilarlo. Las reglas de anticipación
  (1 día si el equipo está en la misma ciudad, alerta de 1 semana si está en otra) y la bodega principal en Bogotá siguen igual.

## 11. Multiimpresión
En los **Parámetros del evento**, el administrador activa «multiimpresión». Con ella activa, los usuarios activos del evento (digitadores temporales **y el coordinador**, que también registra) pueden elegir **desde
qué equipo se imprime cada escarapela**: cada usuario/equipo se asigna a la estación que tiene la impresora, y **varios equipos pueden compartir la misma impresora** (más de 2). La estación imprime sola, sin que nadie
haga nada ahí (docs/16, B1b). Sirve para iPad, para celulares sin cable y para computadores sin impresora. Se construye sobre la cola de impresión y la estación de impresión (aún no construidas).
