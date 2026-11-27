"""«Configurar el evento por cuestionario» (26-nov-2026, pedido de Juan David): primera pestaña de Parámetros del evento.

Preguntas de sí/no y de opción múltiple CERRADA, en lenguaje natural, que dejan configurado el evento:
- Cada opción trae `set`: los controles de la misma pantalla de Parámetros que esa respuesta pone (interruptores, opciones, listas). El navegador los cambia como si la persona
  los tocara (static/js/event-quiz.js) y todo se guarda con el «Guardar cambios» de siempre: el cuestionario NO tiene una vía de guardado aparte para la configuración, así que valen
  las mismas validaciones, permisos e historial de cada sección.
- Lo que una respuesta no puede dejar hecho sola (crear los ítems, las zonas, las categorías, diseñar la escarapela, subir el anexo…) queda como ACCIÓN PENDIENTE: en amarillo con «!»
  en la pestaña y en la sección que la necesita, hasta que se haga. Las acciones se calculan EN VIVO con las respuestas guardadas y el estado real del evento (`collect_state`).

Las respuestas se guardan en `app_settings` con la clave `setup_quiz:<evento>` (sin migración, como el formulario de persona). Solo se guardan claves y valores que existen aquí.
Reglas puras (`QUESTIONS`, `clean_answers`, `visible`, `actions`) sin base de datos: tests/test_setup_quiz.py."""
import json
from typing import Optional

# ------------------------------------------------------------------ cómo se escribe un cambio en un control de la pantalla
def chk(el_id: str, value: bool, label: str) -> dict:
    return {"k": "check", "id": el_id, "v": bool(value), "label": label}


def radio(name: str, value: str, label: str) -> dict:
    return {"k": "radio", "name": name, "v": value, "label": label}


def sel(el_id: str, value: str, label: str) -> dict:
    return {"k": "select", "id": el_id, "v": value, "label": label}


def val(el_id: str, value: str, label: str) -> dict:
    return {"k": "value", "id": el_id, "v": value, "label": label}


def lanes(el_id: str, n: int, label: str) -> dict:
    return {"k": "lanes", "id": el_id, "v": int(n), "label": label}


def state(key: str, value: bool) -> dict:
    """Solo para reconocer la respuesta que ya corresponde al evento (no cambia nada)."""
    return {"k": "state", "key": key, "v": bool(value)}


def opt(value: str, label: str, *ops, hint: str = "") -> dict:
    return {"v": value, "label": label, "hint": hint, "set": list(ops)}


def yes_no(on_ops=(), off_ops=(), yes="Sí", no="No", yes_hint="", no_hint="") -> list:
    return [opt("si", yes, *on_ops, hint=yes_hint), opt("no", no, *off_ops, hint=no_hint)]


def q(qid: str, section: str, text: str, options: list, when: Optional[dict] = None, help: str = "", only: Optional[str] = None) -> dict:
    """`when` = {pregunta: [valores]}: la pregunta solo aparece con esas respuestas. `only` = 'cloud' (no en el servidor local) o 'personform' (si se puede diseñar el formulario)."""
    return {"id": qid, "section": section, "text": text, "help": help, "options": options, "when": when or {}, "only": only}


SECTIONS = [
    ("personas", "Las personas y el registro"),
    ("rostro", "Reconocimiento facial"),
    ("celular", "Invitaciones al celular"),
    ("escarapelas", "Escarapelas, roles y certificados"),
    ("zonas", "Zonas y salones"),
    ("entregas", "Entregas (inventario)"),
    ("turnos", "Turnos y filas"),
    ("datos", "Datos de la persona y código"),
]

SEARCH_OPTS = [("id_first", "Primero la cédula y luego el código"), ("code_first", "Primero el código y luego la cédula"),
               ("code_only", "Solo por código"), ("id_only", "Solo por cédula")]


def _search_question(qid: str, col: str, screen: str, when: dict) -> dict:
    return q(qid, "datos", f"En {screen}, ¿cómo se busca a la persona?",
             [opt(v, t, sel(col, v, f"{screen}: {t.lower()}")) for v, t in SEARCH_OPTS], when=when,
             help="Lo que se escribe, se lee con el lector o se escanea con la cámara. Los nombres siempre se pueden buscar.")


QUESTIONS = [
    # ---------------------------------------------------------------- personas y registro
    q("lista", "personas", "¿Cómo vas a tener a las personas del evento?", [
        opt("base", "Me pasan una lista (base de datos) antes del evento", chk("selfregOn", False, "Autorregistro: apagado")),
        opt("sola", "No hay lista: cada persona se registra sola al llegar", chk("selfregOn", True, "Autorregistro: encendido"),
            hint="Se abre una pantalla donde cada persona escribe sus datos."),
        opt("ambas", "Hay lista y también llegan personas nuevas que se registran solas", chk("selfregOn", True, "Autorregistro: encendido")),
    ]),
    q("apellido", "personas", "En la lista, ¿los nombres y los apellidos vienen en columnas separadas?", [
        opt("sep", "Sí, vienen separados", radio("lastNameMode", "required", "Apellido: obligatorio")),
        opt("junto", "No, el nombre completo viene junto", radio("lastNameMode", "optional", "Apellido: opcional")),
        opt("nose", "No sé: que lo decida el sistema al cargar la lista", radio("lastNameMode", "auto", "Apellido: automático")),
    ], when={"lista": ["base", "ambas"]}),
    q("formweb", "personas", "¿Las personas se inscriben antes por un formulario web (un enlace que se les comparte)?",
      yes_no(on_ops=[state("forms", True)], off_ops=[state("forms", False)])),
    q("gear", "personas", "En la puerta, ¿el digitador puede cambiar la impresora, el autorregistro y la impresión automática sin pedir contraseña?",
      yes_no(on_ops=[chk("regGearDig", True, "Configuración del registro: la ven los digitadores")],
             off_ops=[chk("regGearDig", False, "Configuración del registro: pide contraseña al digitador")],
             no_hint="Hará falta una contraseña de desbloqueo.")),
    q("sesion", "personas", "¿Cuánto tiempo puede quedar quieto un equipo antes de cerrar la sesión del personal?", [
        opt("general", "El tiempo general del sistema", val("idleMinutes", "", "Cierre de sesión: el general")),
        opt("5", "5 minutos (equipos en lugares públicos)", val("idleMinutes", "5", "Cierre de sesión: 5 minutos")),
        opt("15", "15 minutos", val("idleMinutes", "15", "Cierre de sesión: 15 minutos")),
        opt("30", "30 minutos", val("idleMinutes", "30", "Cierre de sesión: 30 minutos")),
        opt("60", "1 hora", val("idleMinutes", "60", "Cierre de sesión: 60 minutos")),
    ]),
    q("logo", "personas", "¿Qué logo se ve en las pantallas del evento?", [
        opt("golden", "El de Golden", radio("logoMode", "default", "Logo: el de Golden")),
        opt("cliente", "El del cliente", radio("logoMode", "custom", "Logo: el propio del evento"), hint="Si todavía no está, hay que subirlo."),
        opt("ninguno", "Ninguno", radio("logoMode", "hidden", "Logo: sin logo")),
    ]),
    q("color", "personas", "¿Las páginas públicas (formularios, aceptación, certificados) llevan el color de marca del cliente?",
      yes_no(on_ops=[radio("brandMode", "custom", "Color de marca: propio")], off_ops=[radio("brandMode", "default", "Color de marca: el de Golden")])),

    # ---------------------------------------------------------------- rostro
    q("rostro", "rostro", "¿Vas a usar reconocimiento facial?",
      yes_no(on_ops=[radio("bsUse", "on", "Reconocimiento facial: usa rostro")], off_ops=[radio("bsUse", "off", "Reconocimiento facial: no usa rostro")],
             no_hint="Todos entran por cédula, QR o búsqueda."), only="cloud",
      help="El rostro siempre es voluntario: quien no quiera, entra por cédula o QR."),
    q("fotos", "rostro", "¿De dónde salen las fotos y quién recoge la aceptación?", [
        opt("golden", "Golden: cada persona se toma una selfie en la puerta", radio("bsSource", "selfie", "Fotos: selfie en la puerta (Golden)")),
        opt("cliente", "El cliente entrega las fotos antes del evento", radio("bsSource", "client", "Fotos: las entrega el cliente"),
            hint="Hace falta el anexo firmado y los datos del organizador."),
        opt("cada", "Cada quien acepta por formulario, QR o enlace", radio("bsSource", "each", "Fotos: cada quien acepta"), hint="Hacen falta los datos del organizador."),
    ], when={"rostro": ["si"]}, only="cloud"),
    q("puerta", "rostro", "¿Las personas pueden entrar solas mirando la cámara, sin que nadie escriba nada?",
      yes_no(on_ops=[chk("ccFaceDoor", True, "Entrada con rostro sin ayuda: encendida")], off_ops=[chk("ccFaceDoor", False, "Entrada con rostro sin ayuda: apagada")],
             yes_hint="Siempre con una persona del equipo frente a la pantalla."), when={"rostro": ["si"]}, only="cloud"),
    q("permiso", "rostro", "¿Cada cuánto se le pide la autorización a la persona?", [
        opt("once", "Una sola vez por persona y evento", sel("ccPrompt", "once", "Autorización: una vez por persona")),
        opt("every_scan", "Antes de cada uso", sel("ccPrompt", "every_scan", "Autorización: antes de cada uso")),
    ], when={"rostro": ["si"]}, only="cloud"),
    q("fotoescarapela", "rostro", "¿La foto del rostro se imprime en la escarapela?",
      yes_no(on_ops=[chk("badgeBioPhoto", True, "Foto del rostro en la escarapela: permitida")], off_ops=[chk("badgeBioPhoto", False, "Foto del rostro en la escarapela: no")]),
      when={"rostro": ["si"]}, only="cloud"),

    # ---------------------------------------------------------------- celular
    q("celular", "celular", "¿Las personas aceptan y se toman la selfie desde su celular antes de llegar?",
      yes_no(on_ops=[chk("ccAceptar", True, "Aceptación desde el celular: encendida")], off_ops=[chk("ccAceptar", False, "Aceptación desde el celular: apagada")]),
      when={"rostro": ["si"]}, only="cloud"),
    q("enlace", "celular", "Al inscribirse por formulario, ¿se les envía por correo su enlace personal?",
      yes_no(on_ops=[chk("ccAcceptLink", True, "Enlace personal por correo: sí")], off_ops=[chk("ccAcceptLink", False, "Enlace personal por correo: no")]),
      when={"celular": ["si"]}, only="cloud"),
    q("sinfecha", "celular", "Si la lista no trae la fecha de nacimiento, ¿quién puede aceptar desde el celular?", [
        opt("enlace", "Solo quien recibió su enlace personal por correo", sel("ccNoBirth", "require_personal_link", "Sin fecha de nacimiento: exige el enlace personal")),
        opt("cualquiera", "Cualquiera que escriba una fecha de adulto", sel("ccNoBirth", "any", "Sin fecha de nacimiento: acepta cualquier fecha de adulto")),
    ], when={"celular": ["si"]}, only="cloud"),

    # ---------------------------------------------------------------- escarapelas, roles y certificados
    q("imprime", "escarapelas", "¿Se imprimen escarapelas en el evento?",
      yes_no(on_ops=[state("badge_designed", True)])),
    q("reimprimir", "escarapelas", "Si alguien pide otra escarapela, ¿se puede reimprimir sin pedir permiso?",
      yes_no(on_ops=[radio("reprintMode", "enabled", "Reimpresión: habilitada")], off_ops=[radio("reprintMode", "disabled", "Reimpresión: solo con permiso del coordinador")]),
      when={"imprime": ["si"]}, help="Solo un administrador cambia esta opción."),
    q("compartida", "escarapelas", "¿Una sola impresora atiende a varios equipos (impresión compartida o por USB en un Android)?",
      yes_no(on_ops=[chk("sharedPrintEnabled", True, "Impresión compartida: encendida")], off_ops=[chk("sharedPrintEnabled", False, "Impresión compartida: apagada")],
             yes_hint="Después eliges dónde imprime cada usuario."), when={"imprime": ["si"]}),
    q("roles", "escarapelas", "¿Habrá tipos de asistente o roles (por ejemplo VIP, Prensa, Staff)?",
      yes_no(on_ops=[state("categories", True)], off_ops=[state("categories", False)], yes_hint="Los roles son las categorías del evento.")),
    q("escarapelarol", "escarapelas", "¿Cada rol lleva una escarapela distinta?",
      yes_no(on_ops=[chk("badgePerCategory", True, "Una escarapela distinta por categoría")], off_ops=[chk("badgePerCategory", False, "Una sola escarapela para todos")]),
      when={"roles": ["si"], "imprime": ["si"]}),
    q("digital", "escarapelas", "¿A cada persona le llega su escarapela al correo?",
      yes_no(on_ops=[chk("digitalEnabled", True, "Escarapela digital: encendida")], off_ops=[chk("digitalEnabled", False, "Escarapela digital: apagada")])),
    q("certificados", "escarapelas", "¿Se entregan certificados al terminar el evento?",
      yes_no(on_ops=[chk("certificatesEnabled", True, "Certificados: encendidos")], off_ops=[chk("certificatesEnabled", False, "Certificados: apagados")])),

    # ---------------------------------------------------------------- zonas
    q("zonas", "zonas", "¿Vas a controlar quién entra y sale de zonas o salones?",
      yes_no(on_ops=[chk("areasEnabled", True, "Control de zonas: encendido")], off_ops=[chk("areasEnabled", False, "Control de zonas: apagado")])),
    q("permanencia", "zonas", "¿Necesitas saber cuánto tiempo pasa cada persona dentro de las zonas?",
      yes_no(on_ops=[chk("dwellEnabled", True, "Medir la permanencia: sí")], off_ops=[chk("dwellEnabled", False, "Medir la permanencia: no")]), when={"zonas": ["si"]}),
    q("minimo", "zonas", "¿Solo recibe certificado o regalos quien cumple un mínimo de permanencia?",
      yes_no(on_ops=[chk("dwellPrize", True, "Exigir un mínimo de permanencia: sí")], off_ops=[chk("dwellPrize", False, "Exigir un mínimo de permanencia: no")]),
      when={"permanencia": ["si"]}),
    q("zonasauto", "zonas", "Al escanear en la zona, ¿la entrada o la salida queda registrada sola, sin pulsar «Acreditar»?",
      yes_no(on_ops=[chk("areasAutoscan", True, "Zonas: registra solo al escanear")], off_ops=[chk("areasAutoscan", False, "Zonas: hay que pulsar «Acreditar»")]),
      when={"zonas": ["si"]}),
    q("zonasbloq", "zonas", "¿La tableta de cada zona queda fija en su zona para que el digitador no la cambie?",
      yes_no(on_ops=[chk("lockAreas", True, "Bloquear la zona del digitador: sí")], off_ops=[chk("lockAreas", False, "Bloquear la zona del digitador: no")]),
      when={"zonas": ["si"]}),

    # ---------------------------------------------------------------- entregas
    q("repartir", "entregas", "¿Vas a repartir algo (comida, regalos, kits, dotación)?",
      yes_no(on_ops=[chk("inventoryEnabled", True, "Control de inventario: encendido")], off_ops=[chk("inventoryEnabled", False, "Control de inventario: apagado")])),
    q("quien", "entregas", "¿Quién decide qué recibe cada persona?", [
        opt("elige", "La persona elige al llegar", radio("invMode", "choose", "Inventario: la persona elige"), hint="Tú creas los productos que se reparten."),
        opt("base", "La lista ya dice qué le toca a cada quien", radio("invMode", "assigned", "Inventario: la base lo define"),
            hint="Eliges la columna de la lista que trae el producto."),
    ], when={"repartir": ["si"]}),
    q("dependientes", "entregas", "¿Las personas vienen con acompañantes o hijos que también reciben algo?",
      yes_no(on_ops=[state("dependents", True)], off_ops=[state("dependents", False)]), when={"quien": ["base"]}),
    q("invauto", "entregas", "Al escanear, ¿se entrega de una vez lo marcado, sin pulsar «Entregar»?",
      yes_no(on_ops=[chk("inventoryAutoscan", True, "Inventario: entrega solo al escanear")], off_ops=[chk("inventoryAutoscan", False, "Inventario: hay que pulsar «Entregar»")]),
      when={"repartir": ["si"]}),
    q("invbloq", "entregas", "¿Cada puesto de entrega queda fijo en lo que reparte para que el digitador no lo cambie?",
      yes_no(on_ops=[chk("lockInventory", True, "Bloquear lo que entrega el digitador: sí")], off_ops=[chk("lockInventory", False, "Bloquear lo que entrega el digitador: no")]),
      when={"repartir": ["si"]}),

    # ---------------------------------------------------------------- turnos
    q("turnos", "turnos", "¿Habrá turnos y filas (la persona ve su turno en el celular y en un televisor)?",
      yes_no(on_ops=[chk("queueEnabled", True, "Turnos y filas: encendido")], off_ops=[chk("queueEnabled", False, "Turnos y filas: apagado")])),
    q("orden", "turnos", "¿En qué orden se atiende a la gente?", [
        opt("arrival", "Por llegada", sel("queueMode", "arrival", "Turnos: por llegada")),
        opt("form", "Por orden de inscripción en el formulario", sel("queueMode", "form", "Turnos: por inscripción")),
        opt("alpha", "Alfabético", sel("queueMode", "alpha", "Turnos: alfabético")),
        opt("manual", "Con un orden que yo subo en Excel", sel("queueMode", "manual", "Turnos: orden manual")),
    ], when={"turnos": ["si"]}),
    q("filas", "turnos", "¿Cuántas filas o mesas atienden?", [opt(str(n), str(n), lanes("queueLanes", n, f"Turnos: {n} fila{'s' if n > 1 else ''}")) for n in (1, 2, 3, 4)],
      when={"turnos": ["si"]}),
    q("nombre", "turnos", "¿En el celular se ve el primer nombre de la persona?",
      yes_no(on_ops=[chk("queueShowName", True, "Turnos: muestra el primer nombre")], off_ops=[chk("queueShowName", False, "Turnos: no muestra el nombre")]),
      when={"turnos": ["si"]}),

    # ---------------------------------------------------------------- datos y código
    q("datosextra", "datos", "Además del nombre y la cédula, ¿pides otros datos (empresa, cargo, talla, alergias…)?",
      yes_no(on_ops=[state("optional_fields", True)], off_ops=[state("optional_fields", False)])),
    q("formpersona", "datos", "¿Quieres cambiar el orden y los grupos de los datos en «Registrar nuevo» y «Editar»?",
      yes_no(on_ops=[state("person_form", True)]), only="personform"),
    q("codigo", "datos", "Además de la cédula, ¿cada persona tiene un código propio (el que va en el QR de la escarapela)?",
      yes_no(on_ops=[chk("codeEnabled", True, "Código de la persona: encendido")], off_ops=[chk("codeEnabled", False, "Código de la persona: apagado")])),
    q("codigooblig", "datos", "¿Toda persona debe tener código al registrarla?",
      yes_no(on_ops=[chk("codeRequired", True, "Código obligatorio: sí")], off_ops=[chk("codeRequired", False, "Código obligatorio: no")]), when={"codigo": ["si"]}),
    _search_question("buscaregistro", "code_search_registro", "Registro", {"codigo": ["si"]}),
    _search_question("buscainv", "code_search_inventario", "Control de inventario", {"codigo": ["si"], "repartir": ["si"]}),
    _search_question("buscazonas", "code_search_zonas", "Control de zonas", {"codigo": ["si"], "zonas": ["si"]}),
]
BY_ID = {x["id"]: x for x in QUESTIONS}


def questions_for(local_server: bool = False, person_form: bool = False) -> list:
    """Las preguntas que aplican a esta pantalla (sin las del rostro en el servidor local; la del formulario de persona solo si se puede diseñar)."""
    out = []
    for x in QUESTIONS:
        if x["only"] == "cloud" and local_server:
            continue
        if x["only"] == "personform" and not person_form:
            continue
        out.append(x)
    return out


def clean_answers(raw, allowed: Optional[list] = None) -> dict:
    """Solo preguntas y valores que existen. `allowed` = la lista de preguntas de esta pantalla (questions_for)."""
    pool = {x["id"]: x for x in (allowed if allowed is not None else QUESTIONS)}
    out = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        qq = pool.get(str(k))
        if qq is None or not isinstance(v, str):
            continue
        if any(o["v"] == v for o in qq["options"]):
            out[qq["id"]] = v
    return out


def visible(qid: str, answers: dict, _seen=None) -> bool:
    """La pregunta se ve si sus condiciones se cumplen y las preguntas de las que depende también se ven."""
    qq = BY_ID.get(qid)
    if qq is None:
        return False
    seen = _seen or set()
    if qid in seen:
        return False
    seen = seen | {qid}
    for dep, vals in qq["when"].items():
        if answers.get(dep) not in vals or not visible(dep, answers, seen):
            return False
    return True


def effective(answers: dict) -> dict:
    """Las respuestas que cuentan: las de preguntas visibles."""
    return {k: v for k, v in answers.items() if visible(k, answers)}


# ------------------------------------------------------------------ acciones pendientes
# Cada una: cuándo aplica (respuestas), cuándo está hecha (estado del evento), en qué parte de la pantalla se marca (`target` = id del bloque) y qué hay que hacer.
def _a(aid, when, done, target, title, text, link=None):
    return {"id": aid, "when": when, "done": done, "target": target, "title": title, "text": text, "link": link}


ACTIONS = [
    _a("roster", {"lista": ["base", "ambas"]}, lambda s: s["roster_loaded"], "qzRosterItem", "Cargar la lista de personas",
       "Sube la base de datos del evento en «Adjuntar base de datos».", "/kiosk/{eid}/roster"),
    _a("forms", {"formweb": ["si"]}, lambda s: s["forms"] > 0, "qzFormsItem", "Crear el formulario de inscripción",
       "Crea al menos un formulario web en «Formularios».", "/kiosk/{eid}/formularios"),
    _a("logo", {"logo": ["cliente"]}, lambda s: s["has_logo"], "qzLogoItem", "Subir el logo del cliente",
       "Sube la imagen del logo en «Subir un logo nuevo»."),
    _a("color", {"color": ["si"]}, lambda s: s["brand_color"], "qzLogoItem", "Elegir el color de marca",
       "Elige el color del cliente en «Color de marca del evento» y guarda."),
    _a("annex", {"rostro": ["si"], "fotos": ["cliente"]}, lambda s: s["annex"], "qzFacialItem", "Subir el anexo firmado del cliente",
       "Sin el anexo la cámara queda bloqueada. Súbelo en «Anexo firmado del cliente»."),
    _a("organizer", {"rostro": ["si"], "fotos": ["cliente", "cada"]}, lambda s: s["organizer"], "qzFacialItem", "Completar los datos del organizador",
       "Escribe la razón social, el NIT y el correo de privacidad del organizador."),
    _a("badge", {"imprime": ["si"]}, lambda s: s["badge_designed"], "qzBadgeItem", "Diseñar la escarapela",
       "Arma el diseño en el diseñador de escarapelas.", "/kiosk/{eid}/escarapela"),
    _a("print_routes", {"imprime": ["si"], "compartida": ["si"]}, lambda s: s["print_routes"] > 0, "sharedPrintCard", "Elegir dónde imprime cada usuario",
       "En la tabla de «Impresión compartida», elige para cada usuario en qué equipo imprime."),
    _a("categories", {"roles": ["si"]}, lambda s: len(s["categories"]) > 0, "qzCategoriesItem", "Escribir los roles (categorías)",
       "Escribe una categoría por línea en «Categorías del evento» y guarda."),
    _a("badge_per_cat", {"roles": ["si"], "imprime": ["si"], "escarapelarol": ["si"]},
       lambda s: s["per_category"] and len(s["categories"]) > 0 and all(c in s["category_templates"] for c in s["categories"]), "qzBadgeItem",
       "Diseñar una escarapela por cada rol",
       "Marca «Una escarapela distinta por categoría» y diseña la de cada categoría en el diseñador.", "/kiosk/{eid}/escarapela"),
    _a("cert", {"certificados": ["si"]}, lambda s: s["cert_designed"], "qzCertItem", "Diseñar el certificado",
       "Arma el certificado en el diseñador de certificados.", "/kiosk/{eid}/certificado"),
    _a("areas", {"zonas": ["si"]}, lambda s: s["areas"] > 0, "qzAreasItem", "Crear las zonas",
       "Agrega las zonas o salones en la tabla de «Control de áreas»."),
    _a("lock_pw", {"__any__": [("zonas", "si", "zonasbloq", "si"), ("repartir", "si", "invbloq", "si")]}, lambda s: s["unlock_pw"], "cfgLockBox",
       "Definir la contraseña de desbloqueo", "Para bloquear la tableta del digitador hace falta una contraseña de desbloqueo."),
    _a("items", {"repartir": ["si"], "quien": ["elige"]}, lambda s: s["items"] > 0, "qzInventoryItem", "Crear los productos que se reparten",
       "Agrega los ítems con su cantidad en la tabla de «Control de inventario»."),
    _a("assign", {"repartir": ["si"], "quien": ["base"]}, lambda s: s["assign_holder"] or s["assign_dep"], "qzInventoryItem", "Elegir la columna del producto",
       "En «La base lo define», elige el campo de la lista que dice el producto y pulsa «Actualizar productos desde la base»."),
    _a("dependents", {"repartir": ["si"], "quien": ["base"], "dependientes": ["si"]}, lambda s: s["dependents"] > 0 and s["assign_dep"], "qzInventoryItem",
       "Cargar la base de dependientes", "Carga la base de dependientes (Adjuntar base de datos › Base de dependientes) y elige su columna de producto.", "/kiosk/{eid}/roster"),
    _a("fields", {"datosextra": ["si"]}, lambda s: s["optional_fields"], "qzFieldsItem", "Crear los datos adicionales",
       "Agrega cada dato (empresa, cargo, talla…) con «Agregar campo opcional»."),
    _a("person_form", {"formpersona": ["si"]}, lambda s: s["person_form"], "personFormCard", "Diseñar el formulario de persona",
       "Ordena los campos y los grupos del formulario y guarda."),
]


def _applies(when: dict, ans: dict) -> bool:
    for k, vals in when.items():
        if k == "__any__":
            if not any(ans.get(a) == av and ans.get(b) == bv for a, av, b, bv in vals):
                return False
        elif ans.get(k) not in vals:
            return False
    return True


def actions(answers: dict, st: dict, event_id: int) -> list:
    """Las acciones que tocan según las respuestas (solo de preguntas visibles), cada una con `done`."""
    ans = effective(answers)
    out, seen = [], set()
    for a in ACTIONS:
        if not _applies(a["when"], ans):
            continue
        key = (a["target"], a["title"])
        if key in seen:          # misma acción pedida por dos respuestas (la contraseña): una sola vez
            continue
        seen.add(key)
        try:
            done = bool(a["done"](st))
        except (KeyError, TypeError):
            done = False
        out.append({"id": a["id"], "target": a["target"], "title": a["title"], "text": a["text"],
                    "link": a["link"].format(eid=event_id) if a["link"] else None, "done": done})
    return out


def state_flags(st: dict) -> dict:
    """Lo que el navegador usa para reconocer las respuestas que ya corresponden al evento (opciones con `state`)."""
    return {"forms": st["forms"] > 0, "badge_designed": bool(st["badge_designed"]), "categories": len(st["categories"]) > 0,
            "dependents": st["dependents"] > 0, "optional_fields": bool(st["optional_fields"]), "person_form": bool(st["person_form"])}


# ------------------------------------------------------------------ base de datos
def setting_key(event_id: int) -> str:
    return f"setup_quiz:{int(event_id)}"


def load(db, event_id: int) -> dict:
    from app.models import AppSetting
    row = db.query(AppSetting).filter(AppSetting.key == setting_key(event_id)).first()
    if not row or not row.value:
        return {}
    try:
        data = json.loads(row.value)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def save(db, event_id: int, answers: dict, by: str) -> dict:
    from app.models import AppSetting
    from app.timeutil import utcnow
    now = utcnow()
    data = {"answers": answers, "updated_at": now.isoformat() + "Z", "by": by}
    row = db.query(AppSetting).filter(AppSetting.key == setting_key(event_id)).first()
    if row is None:
        row = AppSetting(key=setting_key(event_id), value=json.dumps(data, ensure_ascii=False), updated_at=now)
        db.add(row)
    else:
        row.value = json.dumps(data, ensure_ascii=False)
        row.updated_at = now
    return data


def _has_elements(t) -> bool:
    try:
        return bool(t.get_elements())
    except ValueError:
        return False


def collect_state(db, event) -> dict:
    """El estado real del evento que decide si una acción ya está hecha. Solo conteos y banderas: nada de datos personales."""
    from app import inv_assign, personform
    from app.models import BadgeTemplate, EventArea, EventDependent, InventoryItem, PrintRoute, WebForm
    tpls = db.query(BadgeTemplate).filter(BadgeTemplate.event_id == event.id).all()
    badges = [t for t in tpls if (t.kind or "badge") == "badge"]
    cfg = inv_assign.get_config(event)
    try:
        labels = json.loads(event.optional_field_labels) if event.optional_field_labels else {}
    except ValueError:
        labels = {}
    pf = personform.load_raw(db, event)
    return {
        "roster_loaded": bool(event.roster_uploaded),
        "forms": db.query(WebForm.id).filter(WebForm.event_id == event.id).count(),
        "has_logo": bool(event.logo_path),
        "brand_color": bool(event.brand_color),
        "unlock_pw": bool(event.config_unlock_hash),
        "annex": bool(event.precalculo_anexo_ref),
        "organizer": bool((event.organizer_name or "").strip() and (event.organizer_nit or "").strip() and (event.organizer_privacy_email or "").strip()),
        "badge_designed": any(t.category is None and _has_elements(t) for t in badges),
        "print_routes": db.query(PrintRoute.id).filter(PrintRoute.event_id == event.id).count(),
        "categories": event.get_categories() or [],
        "per_category": bool(event.badge_per_category),
        "category_templates": sorted({t.category for t in badges if t.category and _has_elements(t)}),
        "cert_designed": any(t.kind == "certificate" and _has_elements(t) for t in tpls),
        "areas": db.query(EventArea.id).filter(EventArea.event_id == event.id, EventArea.archived_at.is_(None)).count(),
        "items": db.query(InventoryItem.id).filter(InventoryItem.event_id == event.id, InventoryItem.archived_at.is_(None)).count(),
        "assign_holder": bool(cfg.get("holder_product")),
        "assign_dep": bool(cfg.get("dep_product")),
        "dependents": db.query(EventDependent.id).filter(EventDependent.event_id == event.id).count(),
        "optional_fields": bool(labels),
        "person_form": bool(pf),
    }
