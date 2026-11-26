"""Textos del COMPROMISO DIGITAL DEL DIGITADOR POR EVENTO (Fase 4).

Dos clases de texto, con dueños distintos:

1. EL COMPROMISO (`TITLE`, `SUBTITLE`, `INTRO`, `SECTIONS`, `DECLARATION`, `FOOTER`): es de Golden Eventos y Logística S.A.S. («Formato de compromiso — Digitadores y personal de registro en eventos»,
   PDF original del dueño). Se usa LITERAL. Cualquier cambio cambia `VERSION` (la huella SHA-256 que se guarda con cada firma incluye el texto que la persona vio).
2. LA AUTORIZACIÓN DE TRATAMIENTO DE DATOS SENSIBLES (`SENSITIVE_AUTH_TEXT`): debe ser de la AUDITORA. Lo que hay hoy es un BORRADOR provisional, marcado `PENDIENTE_AUDITORA`. Mientras `APPROVED` sea
   False, el formulario con datos sensibles NO se publica en producción (ver `pledge.available`): solo en staging/pruebas o con PLEDGE_ALLOW_DRAFT_TEXT=1. Cuando la auditora entregue el texto: pegarlo
   LITERAL en `SENSITIVE_AUTH_TEXT`, poner `APPROVED = True`, `SENSITIVE_AUTH_VERSION = "<versión de la auditora>"` y subir `VERSION`. No se edita de otra forma (igual que app/legal_texts_data.py)."""

VERSION = "compromiso-2026-11-25.2"          # 25-nov-2026: autorización aprobada y preguntas de contrato/asistencia resaltadas

TITLE = "Formato de compromiso"
SUBTITLE = "Digitadores y personal de registro en eventos"
TAGLINE = "“Usted es la imagen del evento”"

INTRO = ("Yo, el(la) firmante, recibo este documento y me comprometo a tener cumplimiento del mismo durante el evento, de acuerdo con los estándares de calidad y servicio de la empresa, "
         "cumpliendo lo siguiente:")

# (título, [párrafos o listas]). Un elemento `list` es una lista con viñetas; un `str`, un párrafo.
SECTIONS = [
    ("PRESENTACIÓN PERSONAL", [
        "MUJERES",
        ["Uniforme completo: traje ejecutivo negro (pantalón y chaqueta abotonada), línea clásica, sin jean, pana ni materiales informales; pantalón no entubado ni ajustado. Para los eventos a realizarse en regiones cálidas se utilizará traje sin bléiser. Solamente el pantalón y la camisa.",
         "Camisa o blusa perfectamente blanca, cuello impecable, dentro del pantalón.",
         "Cabello limpio, cepillado y recogido, sin que caiga a la cara; accesorios acordes al uniforme (moños negros medianos).",
         "Medias en buen estado, de color piel.",
         "Zapatos cerrados de cuero negro clásico, sin adornos, lustrados, tacón máximo 5 cm (no plataforma).",
         "Uñas cortas, limpias y arregladas; esmalte transparente o pastel (nunca rojo ni fucsia).",
         "Maquillaje suave; perfume y desodorante de aroma suave; aretes cortos o ninguno.",
         "Sin sacos, chaquetas, chales ni bufandas, joyas ostentosas, ni tatuajes o piercing visibles.",
         "Pashmina del color solicitado por el cliente."],
        "HOMBRES",
        ["Traje completo negro, línea clásica, sin jean, pana ni materiales informales. Para los eventos a realizarse en regiones cálidas se utilizará traje sin bléiser. Solamente el pantalón y la camisa.",
         "Camisa perfectamente blanca, cuello impecable y en excelente estado.",
         "Corbata del color solicitado, bien anudada y en perfecto estado. Nudo de la corbata Windsor.",
         "Cabello limpio, corte clásico ejecutivo, organizado (sin crestas ni rapados; gel moderado).",
         "Afeitado a diario.",
         "Zapatos exclusivamente de cuero negro clásico, sin adornos y lustrados (nunca tenis a no ser que el cliente lo solicite, en este caso siempre los cordones deben ser del mismo color de los Tenis).",
         "Uñas cortas, limpias y arregladas; esmalte solo transparente.",
         "Loción y desodorante de aroma suave."],
    ]),
    ("1. PUNTUALIDAD Y ASISTENCIA", [
        ["Llegar puntual al sitio acordado, con el uniforme completo, limpio y planchado, y cumplir el horario del evento desde la hora de citación hasta que el coordinador indique el cierre.",
         "Asistir a los eventos que confirme. Si no puedo asistir, avisar con antelación al personal de Golden (Gloria Garzón – 316 878 9804). La inasistencia sin aviso previo y justificación válida es incumplimiento.",
         "Llegar sobrio(a) y descansado(a). No consumir drogas, cigarrillos ni vapeadores durante la jornada.",
         "Salir del sitio del evento, al finalizar la jornada, con el uniforme completo, aunque tenga otro compromiso (universidad, gimnasio, etc.)."],
    ]),
    ("2. COMPORTAMIENTO Y ATENCIÓN AL CLIENTE", [
        ["Mantener una actitud amable y sonreír a los asistentes, aun bajo presión (filas, fallas del sistema, reclamos). No levantar la voz ni mostrar impaciencia o desacuerdo; comentar las dudas de forma cordial al coordinador.",
         "Identificar al coordinador, acatar sus instrucciones y pedirle autorización para cualquier actividad distinta a la asignada.",
         "Al llegar, tomar atenta nota de mis deberes y actividades; conocer el nombre del evento, el programa y la forma de capturar los datos.",
         "Trabajar en equipo, sin generar discordias, y colaborar en las tareas que el coordinador solicite (montaje, desmonte, protocolo, organización de material).",
         "Entregar reporte en la mañana y al finalizar la jornada.",
         "Llegar a los eventos previamente organizado, para el caso de las damas llegar maquilladas, peinadas y organizadas. Para el caso de los caballeros no realizar actividades como: cortarse las uñas, peinarse en el registro o quitarse prendas.",
         "No coquetear ni abusar de la confianza del cliente, y no participar en cócteles, fiestas o cierres organizados por el cliente ni en los almuerzos programados por el mismo.",
         "No realizar NINGÚN tipo de negociación con el cliente para brindar servicios independientes tales como: digitación, llamadas o actividades por prestación de servicios. Está rotundamente prohibido realizar cualquier tipo de relación comercial con los clientes en nombre propio."],
    ]),
    ("3. PUESTO DE TRABAJO, EQUIPOS Y MATERIALES", [
        ["Usar el celular únicamente con autorización; una vez dentro del sitio del evento, mantenerlo suspendido.",
         "No comer ni masticar chicle en el área de trabajo; tomar refrigerio o almuerzo solo con autorización del coordinador y respetar el horario asignado. Llevar dinero para almuerzo y transporte.",
         "Permanecer bien sentado(a) y no levantarme del puesto sin autorización. Arreglo personal en el baño por turnos asignados (no en grupo), máximo 10 minutos.",
         "Responder por el equipo de cómputo, la impresora y el material asignado (escarapelas, certificados, esferos, carpetas). Entregar al coordinador el material dañado, sin romperlo ni botarlo, y dejar el puesto ordenado y limpio.",
         "No tomar material de expositores u organizadores (esferos, agendas, revistas, etc.) sin autorización, ni guardar objetos personales de los asistentes. Mis objetos personales son de mi responsabilidad."],
    ]),
    ("4. DIGITACIÓN", [
        ["Manejar el sistema según la capacitación recibida, digitar de forma rápida y con excelente ortografía y, ante cualquier duda, preguntar al asistente cómo escribe su nombre.",
         "Si surge un problema, avisar con calma al coordinador, sin correr ni alzar la voz. Un porcentaje de errores de digitación superior al 30 % en la auditoría se considera incumplimiento."],
    ]),
    ("5. IMPACTO", [
        "El incumplimiento de estas indicaciones puede dar lugar a que el coordinador me retire del evento (por presentación personal, horario o manejo al cliente) y a las sanciones previstas por la empresa.",
    ]),
]

DECLARATION = "Declaro que recibí este documento, lo leí y lo entendí, y acepto todas las condiciones contenidas en él, comprometiéndome a cumplirlas a cabalidad."
FOOTER = "Carrera 14A No 71A – 59, oficina 508 · Bogotá D.C., Colombia"

# ---------------------------------------------------------------------------------------------------- encuesta
Q_MEDICAL = "¿Presentas alguna condición médica especial?"
Q_MEDICATION = "¿Tomas algún medicamento?"
Q_SUPPORT = "¿Requieres algún apoyo emocional o de alguna circunstancia que estés manejando en este momento, tal como enfermedad familiar, manejo de hijos?"
Q_CONTRACT = "¿Tienes claras las condiciones del contrato de prestación de servicios?"
Q_ATTENDANCE = "¿Confirmas tu asistencia al evento?"
YES, NO = "Sí", "No"

# ---------------------------------------------------------------------------------------------------- PENDIENTE_AUDITORA
# 25-nov-2026: Juan David confirma que la auditora APROBÓ este texto tal cual (el borrador sin el aviso «BORRADOR – pendiente de aprobación de la auditora»). No se edita.
APPROVED = True
SENSITIVE_AUTH_VERSION = "auditora-aprobada-2026-11-25"
SENSITIVE_AUTH_TEXT = (
    "Autorizo a Golden Eventos y Logística S.A.S. para tratar los datos sensibles que diligencio en este formulario (condición médica, medicamentos, apoyo emocional y contacto de emergencia), "
    "únicamente para atender mi salud y seguridad durante el evento. Sé que son datos sensibles, que solo los verá el coordinador del evento y "
    "el personal autorizado de Golden, y que se eliminan 30 días después de finalizado el evento."
)
