import json
from sqlalchemy import event as sa_event
from sqlalchemy import CheckConstraint, Column, Integer, String, DateTime, Date, Boolean, Float, Numeric, ForeignKey, Text, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import declarative_base, deferred, relationship
from app.crypto import EncryptedText
from datetime import datetime
from app.timeutil import utcnow

Base = declarative_base()

# Roles de staff. "cliente" NO es parte de la jerarquía de permisos habitual (no puede
# registrar/reconocer aunque esté "debajo" de digitador aquí) — ver la nota en
# app/auth.get_event_for_staff y app/routers/staff.py sobre quién puede crear cada rol.
# "comercial" (Sprint 2.4, 2026-09-16, pedido explícito) va justo encima de "coordinador": hereda
# todo lo que un coordinador ya puede hacer (editar evento/tenant, Estadísticas/Reporte, cambiar
# estado, Parámetros del Evento) vía require_role("coordinador") sin tocar nada — pero además
# puede crear clientes/eventos (permiso que coordinador PIERDE, ver create_tenant/create_event) y
# crear cuentas 'cliente' para un evento (antes admin+ solamente). Dos excepciones que NO siguen
# la jerarquía simple, codificadas a mano en create_event_staff: comercial NO puede crear cuentas
# 'digitador' (aunque quede "por encima" de coordinador aquí).
STAFF_ROLES = ("cliente", "digitador", "coordinador", "comercial", "admin", "super_admin")

# Ciclo de vida de un Event, en orden. "en_proceso" es el único estado en el que digitador/cliente
# pueden entrar a registrar (ver app/auth.get_event_for_staff) — "creado" es antes de empezar,
# "finalizado" es después de cerrar.
EVENT_STATUSES = ("creado", "en_proceso", "finalizado")

class Tenant(Base):
    """Un cliente de Golden (la empresa para la que se hacen los eventos), no un usuario de staff."""
    __tablename__ = 'tenants'
    id = Column(String, primary_key=True)
    client_code = Column(String, unique=True, nullable=False)  # generado al azar al crear, ver routers/tenants.py
    name = Column(String, nullable=False)
    contact_name = Column(String)
    contact_phone = Column(String)
    contact_email = Column(String)
    archived_at = Column(DateTime, nullable=True)  # 0088 (Fase 3): NULL = activo; con fecha = archivado (oculto de las listas, se restaura; nada se borra). Ver app/routers/tenants.py
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)

    users = relationship("User", back_populates="tenant", cascade="all, delete", overlaps="tenant,users,logs")
    logs = relationship("AccessLog", back_populates="tenant", cascade="all, delete", overlaps="tenant,users,logs")

class User(Base):
    __tablename__ = 'users'
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey('tenants.id'), primary_key=True)
    first_name = Column(String)
    last_name = Column(String)
    role = Column(String)
    entity = Column(String)  # antes `company`/"Empresa" — renombrado a "Entidad" en toda la app (reunión 2026-09-21, ítem 3b), migración 0024
    phone = Column(String)
    email = Column(String)
    opt_1 = Column(String)  # "Tipo de asistente" (2026-09-20; antes "tipo de empresa") — único campo opcional fijo, el resto son extra_fields
    opt_2 = Column(String)  # deprecado (2026-09-20, era "cantidad de empl") — ya no se escribe, reemplazado por extra_fields. Se deja la columna para no perder datos históricos.
    extra_fields = Column(Text)  # JSON {"opcional_1": "valor", ...} — campos dinámicos (sin límite práctico; techo técnico 500) definidos por el cliente, ver bulk_register en routers/api.py y CLAUDE.md
    face_encoding = deferred(Column(EncryptedText))      # deferred: no se descifra/carga al leer la persona (directorio, cédula...), solo cuando de verdad se pide; cifrado en reposo si hay FACE_ENCRYPTION_KEY (app/crypto.py); el código lo usa en claro
    birth_date = Column(Date, nullable=True)     # L3: la da la persona (formulario web, alta en el quiosco o columna `fecha_nacimiento` de la carga masiva); decide si puede tener captura biométrica
    is_biometric_enabled = Column(Boolean, default=True, server_default='true', nullable=False)   # False = menor de 18 años: sin cámara, sin pantalla de autorización, sin vector
    biometric_consent_at = Column(DateTime, nullable=True)      # cuándo se autorizó guardar el rostro (Ley 1581: dato sensible, autorización previa y expresa)
    face_captured_at = Column(DateTime, nullable=True, index=True)   # cuándo se guardó el rostro (lo estampa el listener de abajo); el tope de BIOMETRIC_MAX_DAYS cuenta desde aquí
    biometric_consent_source = Column(String, nullable=True)    # 'kiosko' (la persona autorizó ante el digitador) | 'carga_masiva' (declaración del organizador) | 'copiado' (heredado de otro evento)

    tenant = relationship("Tenant", back_populates="users", overlaps="tenant,users,logs")
    logs = relationship("AccessLog", back_populates="user", cascade="all, delete", overlaps="tenant,users,logs")

    def get_encoding(self):
        return json.loads(self.face_encoding) if self.face_encoding else None

    def get_extras(self) -> dict:
        return json.loads(self.extra_fields) if self.extra_fields else {}

    def set_extras(self, data: dict) -> None:
        self.extra_fields = json.dumps(data) if data else None

class EventAttendee(Base):
    """Lista de personas esperadas/asociadas a UN evento — separada de User a propósito (ver
    CLAUDE.md, 'decisión de modelado 2026-09-19'): agnóstica al método de registro. Se crea al
    cargar el roster del evento, y también se upsertea sobre la marcha cuando alguien se
    registra/reconoce sin haber estado precargado."""
    __tablename__ = 'event_attendees'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    user_id = Column(String, nullable=False)
    tenant_id = Column(String, nullable=False)
    categories = Column(Text, nullable=True)  # JSON: categorías de esta persona EN ESTE evento (reunión 2026-09-21, ítem 14)
    certificate = Column(Boolean, default=False, server_default='false', nullable=False)  # ítem 5: ¿le corresponde certificado en este evento?
    digital_contact = Column(String, nullable=True)  # ítem 17: correo o teléfono al que se envía la escarapela digital
    digital_token = Column(String, unique=True, nullable=True)  # ítem 17: enlace secreto /b/<token>
    digital_sent_at = Column(DateTime, nullable=True)
    accept_token = Column(String, unique=True, nullable=True)       # enlace personal de autorización /aceptar/<código>/<token> (0064): uno por persona y evento, revocable (se vuelve a generar)
    accept_trusted = Column(Boolean, default=False, server_default='false', nullable=False)   # el enlace salió del listado que cargó el organizador (correo propio): abrirlo verifica la aceptación; si salió de un formulario abierto, no
    accept_sent_at = Column(DateTime, nullable=True)
    origin = Column(String(16), nullable=True)  # 0073 (B1): origen de carga en ESTE evento — base | manual | autoregistro; NULL = Desconocido. No cambia con el estado de registro
    last_action_at = Column(DateTime, nullable=True)  # 0082 (cola compartida): hora del SERVIDOR de la última alta/acreditación en ESTE evento; NULL = sin acción desde que existe la columna
    archived_at = Column(DateTime, nullable=True)  # 0091 (Fase 3): NULL = visible en el directorio; con fecha = inscripción archivada (oculta por defecto, se restaura). No toca consentimientos ni audit_consent_logs
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(['user_id', 'tenant_id'], ['users.id', 'users.tenant_id']),
        UniqueConstraint('event_id', 'user_id', name='uq_event_attendee'),
    )

    event = relationship("Event")

    def get_categories(self) -> list:
        return json.loads(self.categories) if self.categories else []

    def set_categories(self, data: list) -> None:
        self.categories = json.dumps(data) if data else None


class AccessLog(Base):
    __tablename__ = 'access_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, ForeignKey('tenants.id'))
    user_id = Column(String)
    timestamp = Column(DateTime, default=utcnow)
    record_type = Column(String)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=True)
    registered_by_staff_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    client_id = Column(String, nullable=True)  # identificador generado por el kiosco/navegador: un reintento o una sincronización nunca duplica el ingreso (único por evento, ver 0047)
    doubtful_reason = Column(String(24), nullable=True)  # 0077: ingreso sincronizado tras devolver el evento a «Creado» SIN hora válida del dispositivo (`sin_hora_valida`): consultable para revisarlo
    registration_method = Column(String, nullable=True)  # Sprint 2.4 Fase 16 (2026-09-17, pedido explícito): 'tradicional' | 'autoregistro' | 'biometrico' | 'qr' — para el reporte, que siempre debe decir CÓMO se registró cada persona (ver reports.py y routers/api.py)
    took_ms = Column(Integer, nullable=True)  # 0079 (1A): ms del digitador desde la primera tecla en el buscador hasta enviar el registro; vacío en lo anterior y en clientes viejos (app/regtime.py lo acota 0..600000)
    ui_flow = Column(String(12), nullable=True)  # 0079 (1A): pantalla con que se registró («v0» = la de hoy) para comparar antes/después

    __table_args__ = (
        ForeignKeyConstraint(
            ['user_id', 'tenant_id'],
            ['users.id', 'users.tenant_id']
        ),
    )

    tenant = relationship("Tenant", back_populates="logs", overlaps="tenant,users,logs")
    user = relationship("User", back_populates="logs", overlaps="tenant,users,logs")
    event = relationship("Event")
    registered_by = relationship("StaffUser")


class PrintLog(Base):
    """Historial de impresiones de escarapela (Sprint 2.4 Fase 3, 2026-09-16, pedido explícito):
    antes imprimir no dejaba ningún rastro en la base — no había forma de saber si a alguien ya
    se le había impreso la escarapela, para avisar antes de repetir. Tabla aparte de AccessLog a
    propósito: no es un evento de acreditación, mezclarlo ahí rompería el cálculo de estado
    (Nuevo/Registrado) que ya depende de record_type."""
    __tablename__ = 'print_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, ForeignKey('tenants.id'), nullable=False)
    user_id = Column(String, nullable=False)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    printed_at = Column(DateTime, default=utcnow)
    printed_by_staff_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(['user_id', 'tenant_id'], ['users.id', 'users.tenant_id']),
    )

    event = relationship("Event")
    printed_by = relationship("StaffUser")


class CalendarNote(Base):
    """Recordatorio/anotación libre en el Calendario (Sprint 2.4 Fase 8, 2026-09-16, pedido
    explícito) — NO está atado a un evento en particular (para eso ya está Event.notes), es una
    nota suelta sobre un día cualquiera (ej. "llamar al cliente X", "confirmar transporte").
    `created_by_id` sirve para mostrar quién la dejó y para que solo su autor (o admin+) pueda
    borrarla.

    `target_staff_ids` (Fase 14, 2026-09-17, pedido explícito: "puede elegir a quién afectan esas
    notificaciones... a esas personas que elija también les aparecerá la notificación en sus
    calendarios") — JSON con una lista de StaffUser.id, mismo patrón de columna JSON-en-Text que
    Event.optional_field_labels. Vacía/None = visible para todo el equipo con acceso al Calendario
    (comportamiento original, sigue siendo el default); con ids = solo esas personas (+ quien la
    creó) la ven. Nunca incluye cuentas 'cliente'/'digitador' — se valida al crear, ver
    routers/calendar.py."""
    __tablename__ = 'calendar_notes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    text = Column(String, nullable=False)
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=False)
    target_staff_ids = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    created_by = relationship("StaffUser")

    def get_targets(self) -> list:
        return json.loads(self.target_staff_ids) if self.target_staff_ids else []

    def set_targets(self, ids: list) -> None:
        self.target_staff_ids = json.dumps(ids) if ids else None


class StaffUser(Base):
    """Cuenta de staff interno (no la persona biométrica registrada, eso es `User`)."""
    __tablename__ = 'staff_users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False)  # para digitadores, la cédula
    password_hash = Column(String, nullable=False)
    full_name = Column(String)
    role = Column(String, nullable=False)  # uno de STAFF_ROLES
    secondary_role = Column(String, nullable=True)  # Sprint 2.4 Fase 15 (2026-09-17, pedido explícito): "hay coordinadores que también pueden ser comerciales" — el ÚNICO doble rol permitido es coordinador+comercial (en cualquier orden), lo asigna admin+ desde Configuración > Staff (ver routers/staff.py: assign_secondary_role). Ver auth.py: effective_roles()/require_role()/require_role_excluding() para cómo se combina con la jerarquía normal.
    tenant_id = Column(String, ForeignKey('tenants.id'), nullable=True)  # null = alcance global (super_admin)
    email = Column(String, nullable=True)  # correo para notificaciones (informe final del evento a la comercial) — reunión 2026-09-21, ítem 6
    phone = Column(String, nullable=True, unique=True)  # Sprint 2.4, 2026-09-16: WhatsApp; Fase 4: obligatorio+único salvo cliente/digitador (ver routers/staff.py, routers/events.py)
    is_active = Column(Boolean, default=True, nullable=False)
    must_change_password = Column(Boolean, default=False, server_default='false', nullable=False)  # Sprint 4: tras un restablecimiento por un admin/coordinador, en el próximo ingreso debe elegir su propia contraseña
    print_station = Column(Boolean, default=False, server_default='false', nullable=False)  # 0072: «Puesto de impresión» (cuenta protegida: un segundo inicio de sesión se rechaza; app/sessions.py)
    tours_auto_off = Column(Boolean, default=False, server_default='false', nullable=False)  # 0085: «deshabilitar demos automáticas» (por cuenta, no por dispositivo; se copia a la sesión al ingresar)
    session_token = Column(String(40), nullable=True)  # 0072: sesión vigente de la cuenta (NULL = ninguna registrada: una sesión anterior al cambio sigue válida)
    # 0086 (app/login_control.py): bloqueo del digitador tras 3 fallos, solicitud de ingreso que autoriza el coordinador (solo el HASH del token) y época de sesión (app/sessions.py)
    failed_logins = Column(Integer, default=0, server_default='0', nullable=False)
    locked_at = Column(DateTime, nullable=True)
    login_req_hash = Column(String(64), nullable=True)
    login_req_at = Column(DateTime, nullable=True)
    login_req_status = Column(String(12), nullable=True)
    session_epoch = Column(Integer, default=0, server_default='0', nullable=False)
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    tenant = relationship("Tenant")
    created_by = relationship("StaffUser", remote_side=[id])


class Event(Base):
    __tablename__ = 'events'
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, ForeignKey('tenants.id'), nullable=False)
    event_code = Column(String, unique=True, nullable=False)  # único en todo el sistema, no solo por tenant
    name = Column(String, nullable=False)
    location = Column(String)  # nombre del lugar/venue
    address = Column(String)
    country = Column(String)
    city = Column(String)
    start_date = Column(Date)
    end_date = Column(Date)
    setup_date = Column(Date)  # fecha de montaje
    event_time_start = Column(String)  # "HH:MM", desde <input type="time">
    event_time_end = Column(String)
    setup_time_start = Column(String)
    setup_time_end = Column(String)
    notes = Column(Text)
    status = Column(String, default='creado', nullable=False)  # creado | en_proceso | finalizado
    coordinator_staff_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    commercial_staff_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)  # Sprint 2.4 Fase 5 (2026-09-16): quién es "el comercial dueño" del evento — nullable porque eventos viejos no tienen uno; para eventos nuevos es obligatorio a nivel de API (ver routers/events.py: create_event), no a nivel de columna, mismo criterio que coordinator_staff_id
    bandana_color = Column(String, nullable=True)  # "Color de pañoleta" (Sprint 2.4 Fase 12, 2026-09-17, pedido explícito) — hex (#rrggbb) elegido con <input type="color"> (gotero incluido); identifica el evento en el Calendario en vez del color por estado
    bandana_color_name = Column(String, nullable=True)  # nombre libre que el cliente/equipo le da a ese color (ej. "Rojo Golden") — el hex por sí solo no dice nada si el equipo usa sus propios nombres
    created_by_id = Column(Integer, ForeignKey('staff_users.id'))
    created_at = Column(DateTime, default=utcnow)
    optional_field_labels = Column(Text)  # JSON {"opcional_1": "Talla de camisa", ...} — nombres que el cliente le dio a las columnas "opcional_N" de SU roster (2026-09-20, ver bulk_register)
    facial_enabled = Column(Boolean, default=False, nullable=False)  # se enciende sola la primera vez que se sube un roster con zip de fotos (ver bulk_register); desde 2026-09-27 coordinador+ también puede prenderla/apagarla a mano en cualquier momento desde Parámetros del Evento (set_facial_enabled) — apagarla no borra ningún rostro ya guardado. Decide si /kiosk/{id}/registro muestra el escáner de cámara o se comporta como cédula tradicional.
    accept_link_email = Column(Boolean, default=False, server_default='false', nullable=False)   # al inscribirse por formulario se envía el enlace personal de autorización por correo (0064)
    accept_mail_run = Column(String, nullable=True)     # envío masivo de enlaces personales (0065, app/acceptmail.py): id de la tanda en curso; vacío = detenido o terminado
    biometrics_locked = Column(Boolean, default=False, server_default='false', nullable=False)   # candado «sin biometría» (0063): el servidor no deja activar el rostro, guardar fotos ni encolar vectores en este evento
    roster_uploaded = Column(Boolean, default=False, nullable=False)  # 2026-09-21: true desde la primera vez que bulk_register cargó al menos una fila para este evento. Sirve para bloquear un RE-upload accidental mientras el evento ya está en_proceso (ver bulk_register) — evita pisar registros que ya se hicieron en vivo.
    auto_print_badge = Column(Boolean, default=False, nullable=False)  # 2026-09-15 (Sprint 2, Historia 2.2): si está prendido, guardar un registro exitoso (cualquier método) dispara la impresión de la escarapela sola, sin que el digitador toque el botón. Apagado por default a propósito — el brief es explícito en que la impresión NO es automática salvo que se active este switch.
    shared_print_enabled = Column(Boolean, default=False, server_default='false', nullable=False)  # impresión compartida (22-oct-2026, 0069): APAGADA por defecto; app/routers/shared_print.py
    reprint_disabled = Column(Boolean, default=False, server_default='false', nullable=False)   # 0083 (Fase 1B): true = reimprimir a quien ya se imprimió exige permiso del coordinador (app/reprint.py); solo admin+ lo cambia
    print_settings_json = Column(Text, nullable=True)   # valores de impresión de escarapelas del evento (0070, app/routers/print_settings.py); NULL = de fábrica
    super_event_id = Column(Integer, ForeignKey('super_events.id'), nullable=True)  # ítem 19: superevento al que pertenece (NULL = evento suelto)
    certificates_enabled = Column(Boolean, default=False, server_default='false', nullable=False)  # ítem 5: módulo de certificados activado desde Parámetros
    certificates_token = Column(String, unique=True, nullable=True)  # enlace público /c/<token> para que cada persona descargue su certificado (2026-09-23)
    digital_badge_enabled = Column(Boolean, default=False, server_default='false', nullable=False)  # ítem 17: escarapela digital activada desde Parámetros
    areas_enabled = Column(Boolean, default=False, server_default='false', nullable=False)  # ítem 9a: Control de Áreas activado desde Parámetros
    inventory_enabled = Column(Boolean, default=False, server_default='false', nullable=False)  # ítem 9b: Control de Inventario activado desde Parámetros
    finalized_at = Column(DateTime, nullable=True)     # cuándo pasó a «finalizado» (lo estampa el listener de abajo; NULL si no lo está): desde aquí corren los BIOMETRIC_RETENTION_DAYS_AFTER_EVENT días
    biometrics_purged_at = Column(DateTime, nullable=True)     # última vez que se borraron los datos biométricos de este evento (privacidad)
    digital_email_subject = Column(String, nullable=True)  # plantilla propia del correo de la escarapela virtual (NULL = la de siempre)
    digital_email_body = Column(Text, nullable=True)       # HTML ya saneado (app/email_template.py)
    report_pdf_path = Column(String, nullable=True)  # PDF del informe final (ítem 6); NULL = pendiente
    report_uploaded_at = Column(DateTime, nullable=True)
    logo_height = Column(Integer, default=50, server_default='50', nullable=False)      # alto del logo propio en el header (30–80 px)
    logo_fit = Column(String, default='logo', server_default='logo', nullable=False)     # 'logo' (se ve completo) | 'banner' (rellena el ancho disponible y recorta)
    logo_mode = Column(String, default='default', server_default='default', nullable=False)  # 'default' (logo de Golden) | 'hidden' | 'custom' — reunión 2026-09-21, ítem 1
    categories = Column(Text, nullable=True)  # JSON: nombres de las categorías del evento (ítem 14)
    badge_per_category = Column(Boolean, default=False, server_default='false', nullable=False)  # False = una plantilla para todas las categorías, True = una por categoría
    logo_path = Column(String, nullable=True)  # archivo del logo propio (solo si logo_mode='custom'), en data/<tenant>/event_logos/
    faces_version = Column(Integer, default=0, server_default='0', nullable=False)  # sube en cada cambio de rostros del evento (app/faces_version.py); el reconocimiento recarga su matriz en memoria cuando cambia
    state_id = Column(Integer, ForeignKey('event_states.id'), nullable=True)  # estado configurable (docs/18): sus reglas mandan; `status` sigue siendo el estado BASE con el que se comporta (creado | en_proceso | finalizado)
    directory_page_size = Column(Integer, default=50, server_default='50', nullable=False)  # filas por página de la tabla del directorio (en vivo y lista local); 10, 20, 50, 100 o 200 (Parámetros del evento)
    controller_mode = Column(String, default='golden', server_default='golden', nullable=False)   # L1: 'golden' (evento propio, Golden = Responsable único) | 'tercero' (Golden = Encargado); decide la variante del texto de autorización
    organizer_name = Column(String, nullable=True)            # razón social del organizador (obligatoria si controller_mode='tercero')
    organizer_nit = Column(String, nullable=True)
    organizer_privacy_email = Column(String, nullable=True)   # correo del organizador para consultas y revocación
    consent_prompt_mode = Column(String, default='once', server_default='once', nullable=False)   # 'once' (una vez por persona y evento) | 'every_scan' (botones cortos antes de cada uso)
    aceptar_enabled = Column(Boolean, default=False, server_default='false', nullable=False)   # camino B: página pública /aceptar/<código del evento> para aceptar y dar la selfie desde el celular
    client_photos_before = Column(Boolean, default=False, server_default='false', nullable=False)   # el cliente entregará fotos de los asistentes ANTES del evento (paso guiado de biometría)
    precalculo_garantia = Column(Boolean, default=False, server_default='false', nullable=False)   # casilla de garantía del cliente (declaraciones, garantías e indemnidad), exigida para el pre-cálculo
    precalculo_autorizado = Column(Boolean, default=False, server_default='false', nullable=False)   # regla A: solo super_admin, solo evento de tercero, con la referencia y fecha del anexo firmado
    precalculo_anexo_ref = Column(String, nullable=True)
    precalculo_anexo_fecha = Column(Date, nullable=True)
    auto_register = Column(Boolean, default=False, nullable=False)  # 2026-09-16 (Sprint 2.2, Fase B): mismo criterio que auto_print_badge, pero para el registro en sí. Apagado por default: un match (facial o cédula, cualquier método) NO acredita solo — solo deja el match "pendiente" (result=MATCH_PENDING) hasta que el digitador confirme con "Guardar y autorizar acceso". Prendido, un match acredita de una, como se comportaba todo antes de este cambio.
    face_door_enabled = Column(Boolean, default=False, server_default='false', nullable=False)
    idle_minutes = Column(Integer, nullable=True)   # 0081: minutos de inactividad antes de cerrar la sesión del personal que trabaja en este evento (5-60), SOLO mientras está en proceso; NULL = el general (SESSION_IDLE_MINUTES, 10). app/idle.py
    face_door_liveness = Column(Boolean, default=True, server_default='true', nullable=False)   # 0068: prueba de movimiento en la entrada con rostro (app/liveness.py); encendida por defecto
    badge_bio_photo_allowed = Column(Boolean, default=False, server_default='false', nullable=False)   # A1 (0067): imprimir la foto BIOMÉTRICA en la escarapela; apagado = no se imprime (recuadro gris). Solo super_admin   # B1 (0066): pantalla de autoservicio «Entrar con mi rostro» (app/routers/door.py); apagada por defecto
    extra_json = Column(Text, nullable=True)   # 0087 (Fase 2): valores de los campos PERSONALIZADOS de la plantilla de evento {clave: valor} (app/event_template.py). Los campos base y los interruptores siguen en sus columnas

    tenant = relationship("Tenant")
    created_by = relationship("StaffUser", foreign_keys=[created_by_id])
    coordinator = relationship("StaffUser", foreign_keys=[coordinator_staff_id])
    commercial = relationship("StaffUser", foreign_keys=[commercial_staff_id])
    super_event = relationship("SuperEvent", back_populates="events")
    state = relationship("EventState")

    def get_optional_labels(self) -> dict:
        return json.loads(self.optional_field_labels) if self.optional_field_labels else {}

    def set_optional_labels(self, data: dict) -> None:
        self.optional_field_labels = json.dumps(data) if data else None

    def get_categories(self) -> list:
        return json.loads(self.categories) if self.categories else []

    def set_categories(self, data: list) -> None:
        self.categories = json.dumps(data) if data else None

    def get_extra(self) -> dict:
        try:
            value = json.loads(self.extra_json) if self.extra_json else {}
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def set_extra(self, data: dict) -> None:
        self.extra_json = json.dumps(data, ensure_ascii=False) if data else None


class EventTemplate(Base):
    """Plantilla de evento (Fase 2, 0087): qué campos tiene un evento, cuáles pide «Nuevo evento» y cuáles salen en la tarjeta del calendario. UNA por ámbito (`scope`='global' hoy);
    `tenant_id` queda NULL y reservado para un futuro con una plantilla por cuenta. Sin fila = la plantilla de fábrica (app/event_template.py), que reproduce el formulario de siempre.
    `version` sube en cada guardado (bloqueo optimista: dos administradores no se pisan)."""
    __tablename__ = 'event_templates'
    id = Column(Integer, primary_key=True, autoincrement=True)
    scope = Column(String, nullable=False, unique=True, default='global')
    tenant_id = Column(String, ForeignKey('tenants.id'), nullable=True)
    fields_json = Column(Text, nullable=False)
    creation_layout_json = Column(Text, nullable=False)
    calendar_layout_json = Column(Text, nullable=False)
    version = Column(Integer, nullable=False, default=1, server_default='1')
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    updated_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)


class EventTemplateRevision(Base):
    """Historial de la plantilla (auditoría simple): quién guardó qué versión y cuándo, con la plantilla completa de esa versión. Se conservan las últimas 50."""
    __tablename__ = 'event_template_revisions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(Integer, ForeignKey('event_templates.id', ondelete='CASCADE'), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    snapshot_json = Column(Text, nullable=False)
    saved_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    saved_at = Column(DateTime, default=utcnow, nullable=False)


class EventState(Base):
    """Estado de evento CONFIGURABLE (docs/18 §4): el administrador crea los que quiera y a cada uno le adjunta reglas (qué se habilita mientras un evento está en él). `base_status` es el
    estado clásico con el que el sistema sigue decidiendo lo demás (retención biométrica, «registrar solo en proceso»…): creado | en_proceso | finalizado. `rules_json` = {regla: bool}
    (ver app/event_rules.py); una regla ausente toma el valor por defecto de su estado base."""
    __tablename__ = 'event_states'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    base_status = Column(String, nullable=False)
    color = Column(String, nullable=True)
    position = Column(Integer, nullable=False, default=0, server_default='0')
    is_active = Column(Boolean, nullable=False, default=True, server_default='true')
    rules_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def get_rules(self) -> dict:
        return json.loads(self.rules_json) if self.rules_json else {}


class EventStaffAuthorization(Base):
    """Qué staff_user puede operar en qué evento. Obligatorio para digitadores (acceso temporal);
    para coordinador/admin/super_admin no se exige (tienen alcance de tenant/global)."""
    __tablename__ = 'event_staff_authorizations'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    staff_user_id = Column(Integer, ForeignKey('staff_users.id'), nullable=False)
    authorized_by_id = Column(Integer, ForeignKey('staff_users.id'))
    authorized_at = Column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint('event_id', 'staff_user_id', name='uq_event_staff'),)

    event = relationship("Event")
    staff_user = relationship("StaffUser", foreign_keys=[staff_user_id])
    authorized_by = relationship("StaffUser", foreign_keys=[authorized_by_id])


class BadgeTemplate(Base):
    """La plantilla de escarapela ACTIVA de un evento — siempre por evento, uno a uno (Sprint 2,
    Épico 2, decisión de Juan David que reemplaza el borrador de docs/05_MODELO_DATOS.md §3.2:
    'event_id' deja de ser nullable). No es lo mismo que SavedBadgeTemplate (la librería reusable
    por tenant, ver abajo) — importar una plantilla guardada COPIA su diseño acá, no la referencia
    en vivo (editar después una no afecta a la otra)."""
    __tablename__ = 'badge_templates'
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, ForeignKey('tenants.id'), nullable=False)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    category = Column(String, nullable=True)  # NULL = plantilla general; con nombre = la de esa categoría (ítem 14)
    kind = Column(String, nullable=False, default='badge', server_default='badge')  # 'badge' (escarapela) | 'certificate' (plantilla del certificado, ítem 5)
    name = Column(String, nullable=False, default='Escarapela')
    width_mm = Column(Float, nullable=False, default=62.0)
    height_mm = Column(Float, nullable=False, default=100.0)
    orientation = Column(String, nullable=False, default='vertical')  # 'vertical' (pensado para Brother QL-800) | 'horizontal'
    background_type = Column(String, nullable=False, default='color')  # 'color' | 'image'
    background_value = Column(String)  # color hex (#RRGGBB), o el path que devuelve /api/badge-assets al subir una imagen
    elements_json = Column(Text)  # JSON: lista ordenada (por z_index) de elementos — ver CLAUDE.md para el shape de cada tipo
    imported_from_saved_template_id = Column(Integer, ForeignKey('saved_badge_templates.id'), nullable=True)  # solo trazabilidad ("de dónde vino"), no un vínculo vivo
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint('event_id', 'category', 'kind', name='uq_badge_template_event_category_kind'),)

    tenant = relationship("Tenant")
    event = relationship("Event")
    imported_from = relationship("SavedBadgeTemplate", foreign_keys=[imported_from_saved_template_id])

    def get_elements(self) -> list:
        return json.loads(self.elements_json) if self.elements_json else []

    def set_elements(self, data: list) -> None:
        self.elements_json = json.dumps(data) if data else None


# consent = casilla con texto de política debajo (ítem 16); signature = lienzo de firma (ítem 10).
# Ambos solo aplican a campos opcionales (opcional_N).
FIELD_TYPES = ("text_short", "text_long", "select", "boolean", "consent", "signature", "email")
CHART_TYPES = ("bar", "pie", "histogram", "line")


class EventFieldConfig(Base):
    """Parámetros del Evento (Sprint 2.2, 2026-09-16) — cómo debe comportarse UN campo del alta
    manual/edición para ESTE evento: si es obligatorio, qué tipo de control usar (texto
    corto/largo, lista desplegable con sus propias opciones, booleano), y si debe generar
    estadística sola al entrar a Estadísticas (y con qué tipo de gráfico). `field_key` es
    `role`/`entity`/`phone`/`email`/`opt_1` o un `opcional_N` ya rotulado en
    `Event.optional_field_labels` — la identidad (`id`/`first_name`/`last_name`) queda afuera a
    propósito, siempre texto corto obligatorio, no configurable. Sin fila para un campo dado =
    valores por defecto (no obligatorio, texto corto, sin estadística por defecto) — ver
    `app/routers/parametros.py: _field_configs_for_event` para el merge con esos defaults."""
    __tablename__ = 'event_field_configs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    field_key = Column(String, nullable=False)
    required = Column(Boolean, default=False, nullable=False)
    field_type = Column(String, nullable=False, default='text_short')
    options_json = Column(Text)  # solo con sentido si field_type == 'select'
    default_stat_enabled = Column(Boolean, default=False, nullable=False)
    default_chart_type = Column(String, nullable=True)
    label = Column(String, nullable=True)  # nombre a mostrar SOLO en este evento (NULL = el de por defecto) — reunión 2026-09-21, ítem 3a
    sort_order = Column(Integer, nullable=True)  # posición en Registrar/Editar (NULL = orden por defecto) — ítem 4
    help_text = Column(Text, nullable=True)  # texto de política/consentimiento (solo consent/signature) — ítems 16 y 10
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint('event_id', 'field_key', name='uq_event_field_config'),)

    event = relationship("Event")

    def get_options(self) -> list:
        return json.loads(self.options_json) if self.options_json else []

    def set_options(self, data: list) -> None:
        self.options_json = json.dumps(data) if data else None


class SavedBadgeTemplate(Base):
    """Librería de plantillas reusables, por TENANT (no por evento) — para guardar un diseño que
    gustó y poder importarlo como punto de partida en otro evento del mismo cliente. Importar
    COPIA los campos a un BadgeTemplate nuevo/existente; esta fila no se modifica ni se referencia
    después (ver BadgeTemplate.imported_from_saved_template_id, que es solo trazabilidad)."""
    __tablename__ = 'saved_badge_templates'
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, ForeignKey('tenants.id'), nullable=False)
    name = Column(String, nullable=False)
    width_mm = Column(Float, nullable=False)
    height_mm = Column(Float, nullable=False)
    orientation = Column(String, nullable=False, default='vertical')
    background_type = Column(String, nullable=False, default='color')
    background_value = Column(String)
    elements_json = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    tenant = relationship("Tenant")

    def get_elements(self) -> list:
        return json.loads(self.elements_json) if self.elements_json else []

    def set_elements(self, data: list) -> None:
        self.elements_json = json.dumps(data) if data else None

class BulkJob(Base):
    """Carga masiva de una base en segundo plano (Sprint 5): el navegador recibe un `id` de inmediato y consulta
    el avance (`stage`, `done`/`total` en unidades ponderadas: una foto pesa mucho más que una fila) hasta que
    termina. `result_json` guarda la misma respuesta que antes devolvía la petición; `error_*` el error que
    antes habría sido un HTTP 4xx/5xx."""
    __tablename__ = 'bulk_jobs'
    id = Column(String, primary_key=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    staff_user_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    status = Column(String, nullable=False, default='queued')  # queued | running | done | error
    stage = Column(String, nullable=True)
    done = Column(Integer, nullable=False, default=0)
    total = Column(Integer, nullable=False, default=0)
    result_json = Column(Text, nullable=True)
    error_status = Column(Integer, nullable=True)
    error_detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    spec_json = Column(Text, nullable=True)       # carga ejecutada por un Cloud Run Job: qué procesar (ver app/bulk_runner.py)


class WebForm(Base):
    """Formulario web propio de un evento (Sprint 5): reemplaza a Excel/Google Forms como vía de inscripción. Un
    evento puede tener varios. `design_json` = diseño (tema, filas, campos); `settings_json` = seguridad, pre-llenado,
    plantillas de cierre/agradecimiento y cómo se alimenta la base del evento. El estado efectivo sale de
    `manual_status` o, con `use_schedule`, del calendario `schedule_json` (ver app/formlib.py)."""
    __tablename__ = 'web_forms'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    manual_status = Column(String, nullable=False, default='pruebas')  # pruebas | activo | cerrado | finalizado
    use_schedule = Column(Boolean, nullable=False, default=False)
    schedule_json = Column(Text, nullable=True)  # [{"status":"pruebas","from":"2026-10-01T08:00","to":"2026-10-05T23:59"}, ...] hora local
    capacity = Column(Integer, nullable=True)     # cupo de inscripciones (NULL = sin límite); editable en caliente
    design_json = Column(Text, nullable=False)
    settings_json = Column(Text, nullable=True)
    test_key = Column(String, nullable=False)     # clave del enlace de pruebas (?k=...)
    fed_at = Column(DateTime, nullable=True)      # cuándo se cargaron a la base las inscripciones (modo "al cerrar")
    archived_at = Column(DateTime, nullable=True)  # 0091 (Fase 3): NULL = activo; con fecha = archivado (oculto de las listas y cerrado al público; conserva respuestas y pagos)
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint('event_id', 'slug', name='uq_web_form_event_slug'),)


class FormSubmission(Base):
    """Una inscripción. `is_test`: enviada mientras el formulario estaba en `pruebas` (se excluye del reporte y de la
    analítica oficiales sin tener que borrarla a mano)."""
    __tablename__ = 'form_submissions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    form_id = Column(Integer, ForeignKey('web_forms.id'), nullable=False)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    data_json = Column(Text, nullable=False)     # {field_id: valor}; archivos: {"filename","stored","size"}
    is_test = Column(Boolean, nullable=False, default=False)
    person_id = Column(String, nullable=True)    # cédula, si el formulario identifica a la persona
    invite_id = Column(Integer, ForeignKey('form_invites.id'), nullable=True)
    source = Column(String, nullable=True)       # utm_source (instagram, tiktok, whatsapp, ...)
    sid = Column(String, nullable=True)          # sesión del navegador (para medir tiempos y abandono)
    started_at = Column(DateTime, nullable=True)
    fed = Column(Boolean, nullable=False, default=False)   # ya se cargó a la base del evento
    # `confirmed` = inscripción real. `awaiting_payment` = transitoria mientras se espera a Wompi: NUNCA se ve en listas,
    # reportes, analítica ni se carga a la base del evento (solo aparta cupo unos minutos). Ver app/routers/form_payments.py.
    status = Column(String, nullable=False, default='confirmed', server_default='confirmed')
    quota_keys = Column(Text, nullable=True)   # `|firma|firma|` de los cupos por variables que esta inscripción cumple (se cuentan en SQL, sin leer el JSON de todas)
    discount_code_id = Column(Integer, ForeignKey('form_discount_codes.id'), nullable=True)   # código de descuento con el que se inscribió (cuenta como un uso)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class FormDiscountCode(Base):
    """Un código de descuento de un formulario. `discount_id` apunta al descuento (`how: code`) del diseño. Un código compartido
    tiene `max_uses` = N usos; los «N códigos distintos de un solo uso» son N filas con `max_uses` = 1."""
    __tablename__ = 'form_discount_codes'
    __table_args__ = (UniqueConstraint('form_id', 'code', name='uq_form_discount_code'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    form_id = Column(Integer, ForeignKey('web_forms.id'), nullable=False)
    discount_id = Column(String, nullable=False)
    code = Column(String, nullable=False)          # siempre en MAYÚSCULAS y sin espacios
    max_uses = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class FormPayment(Base):
    """Un intento de pago de un formulario con campo «Pago» (Wompi). `reference` codifica evento + formulario +
    inscripción y es única: es la trazabilidad por evento (Wompi no organiza por proyecto). El registro de pago se
    conserva aunque la inscripción no llegue a confirmarse (rechazado/abandonado) — es un registro financiero."""
    __tablename__ = 'form_payments'
    id = Column(Integer, primary_key=True, autoincrement=True)
    form_id = Column(Integer, ForeignKey('web_forms.id'), nullable=False)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    submission_id = Column(Integer, ForeignKey('form_submissions.id'), nullable=True)
    reference = Column(String, nullable=False, unique=True)
    amount_cents = Column(Integer, nullable=False)          # centavos de COP (Wompi los pide en centavos)
    currency = Column(String, nullable=False, default='COP')
    status = Column(String, nullable=False, default='pending')   # pending | approved | declined | error | voided
    is_test = Column(Boolean, nullable=False, default=False)     # hecho con las llaves de pruebas (sandbox) de Wompi
    transaction_id = Column(String, nullable=True)
    payment_method = Column(String, nullable=True)               # CARD | PSE | ...
    breakdown_json = Column(Text, nullable=True)                 # monto base, reglas y descuentos aplicados
    person_id = Column(String, nullable=True)
    payer_email = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    confirmed_at = Column(DateTime, nullable=True)
    refunded_cents = Column(Integer, nullable=False, default=0, server_default='0')   # suma de reembolsos HECHOS (done)
    origin = Column(String(16), nullable=True)   # 0074: 'importado' = registro histórico traído de otro entorno (no es un pago de este)


class FormRefund(Base):
    """Un reembolso de un pago (auditoría completa: quién, cuándo, por qué). `kind`: `void` (anulación de una transacción de
    TARJETA por el valor completo, hecha por la API de Wompi) o `manual` (parcial, o de otro medio — PSE, Nequi…: la
    plata se devolvió por fuera —panel de Wompi o transferencia— y aquí solo se registra). `status`: pending (Wompi la
    aceptó pero aún no confirma) | done | failed."""
    __tablename__ = 'form_refunds'
    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(Integer, ForeignKey('form_payments.id'), nullable=False)
    amount_cents = Column(Integer, nullable=False)
    kind = Column(String, nullable=False)
    status = Column(String, nullable=False, default='pending')
    reason = Column(Text, nullable=False)
    note = Column(Text, nullable=True)                       # manual: cómo/dónde se devolvió (comprobante, banco…)
    cancel_registration = Column(Boolean, nullable=False, default=True)   # al completarse, la inscripción queda cancelada (libera el cupo)
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)   # NULL = lo registró el webhook (anulada desde el panel de Wompi)
    wompi_response = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    done_at = Column(DateTime, nullable=True)


class FormEvent(Base):
    """Marcas de uso de un formulario público para la analítica: `view` (abrió), `start` (empezó a llenar) y `submit`."""
    __tablename__ = 'form_events'
    id = Column(Integer, primary_key=True, autoincrement=True)
    form_id = Column(Integer, ForeignKey('web_forms.id'), nullable=False)
    sid = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    source = Column(String, nullable=True)
    is_test = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class FormClientUser(Base):
    """Acceso de un cliente a las ESTADÍSTICAS de UN formulario (no del evento): enlaza una cuenta de staff con rol 'cliente' con el formulario que puede ver. Esa cuenta no tiene
    EventStaffAuthorization, así que ninguna ruta del evento le abre; solo `/mi-formulario` y `/api/form-client/*` (app/form_client.py). `expires_at` = vencimiento del acceso."""
    __tablename__ = 'form_client_users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    form_id = Column(Integer, ForeignKey('web_forms.id'), nullable=False, index=True)
    staff_user_id = Column(Integer, ForeignKey('staff_users.id'), nullable=False, unique=True)
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=False)

    form = relationship("WebForm")
    staff_user = relationship("StaffUser", foreign_keys=[staff_user_id])


class FormInvite(Base):
    """Enlace personalizado por invitado (`/f/<evento>/<slug>?i=<token>`): ya trae identificada a la persona."""
    __tablename__ = 'form_invites'
    id = Column(Integer, primary_key=True, autoincrement=True)
    form_id = Column(Integer, ForeignKey('web_forms.id'), nullable=False)
    person_id = Column(String, nullable=False)
    token = Column(String, nullable=False, unique=True)
    email = Column(String, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint('form_id', 'person_id', name='uq_form_invite_person'),)


class FormPerson(Base):
    """Base subida aparte solo para pre-llenar UN formulario (no entra a la base del evento)."""
    __tablename__ = 'form_people'
    id = Column(Integer, primary_key=True, autoincrement=True)
    form_id = Column(Integer, ForeignKey('web_forms.id'), nullable=False)
    person_id = Column(String, nullable=False)
    data_json = Column(Text, nullable=False)

    __table_args__ = (UniqueConstraint('form_id', 'person_id', name='uq_form_person'),)


class SavedFormTemplate(Base):
    """Librería de diseños de formulario reutilizables, por cliente (mismo patrón que SavedBadgeTemplate)."""
    __tablename__ = 'saved_form_templates'
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, ForeignKey('tenants.id'), nullable=False)
    name = Column(String, nullable=False)
    design_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class RouletteConfig(Base):
    """Configuración de la Ruleta de un evento (Sprint 5): comportamiento y estilo visual por separado, y el código
    secreto de la pantalla de visualización (/r/<token>)."""
    __tablename__ = 'roulette_configs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False, unique=True)
    behavior_json = Column(Text, nullable=True)
    style_json = Column(Text, nullable=True)
    display_token = Column(String, unique=True, nullable=True)
    authorized_json = Column(Text, nullable=True)   # {"label", "by", "at"}: el operador AUTORIZÓ un giro; el botón de la pantalla pública lo consume
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class RouletteDraw(Base):
    """Un sorteo ejecutado (auditoría): quién ganó, con qué modo, si fue aleatorio real y cuándo."""
    __tablename__ = 'roulette_draws'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    label = Column(String, nullable=True)
    mode = Column(String, nullable=False)
    is_random = Column(Boolean, nullable=False, default=False)
    candidates_count = Column(Integer, nullable=False, default=0)
    filter_json = Column(Text, nullable=True)
    winners_json = Column(Text, nullable=False)
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class RateLimitEvent(Base):
    """Intentos registrados para limitar abuso (Sprint 4): login fallido, solicitud de restablecer contraseña,
    consulta pública de certificados. Vive en Postgres (no en memoria) para que el límite valga aunque haya
    varios procesos/workers y sobreviva a un reinicio. `key` = usuario o token según `kind`."""
    __tablename__ = 'rate_limit_events'
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String, nullable=False)
    key = Column(String, nullable=False)
    ip = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class PasswordResetToken(Base):
    """Enlace de "olvidé mi contraseña" (Sprint 4): de un solo uso y con vencimiento. Solo se guarda el hash
    del token (si alguien lee la base, no puede usar los enlaces)."""
    __tablename__ = 'password_reset_tokens'
    id = Column(Integer, primary_key=True, autoincrement=True)
    staff_user_id = Column(Integer, ForeignKey('staff_users.id'), nullable=False)
    token_hash = Column(String, nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class SavedColor(Base):
    """Librería de colores de pañoleta (2026-09-23): se define una vez ("Rojo Golden" = #C0392B) y se elige
    en cualquier evento. Es global a la organización (no por cliente). El evento guarda su propia copia
    (`bandana_color`/`bandana_color_name`), así que borrar un color no toca los eventos que ya lo usaron."""
    __tablename__ = 'saved_colors'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    hex = Column(String, nullable=False)
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_at = Column(DateTime, default=utcnow)


class EventDocument(Base):
    """Documento general del evento (reunión 2026-09-21, ítem 8): nombre/referencia, descripción y
    un archivo (línea Office o imágenes). El archivo vive en data/<tenant>/event_docs/<evento>/."""
    __tablename__ = 'event_documents'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    original_filename = Column(String, nullable=False)
    stored_path = Column(String, nullable=False)
    mime_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    uploaded_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_at = Column(DateTime, default=utcnow)


class EventExpense(Base):
    """Un gasto legalizado del evento (ítem 7): categoría, responsable, descripción, a quién aplica,
    valor y foto de evidencia (opcional). El reporte Excel suma el total."""
    __tablename__ = 'event_expenses'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    category = Column(String, nullable=False)
    responsible = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    applies_to = Column(String, nullable=True)
    amount = Column(Numeric(14, 2), nullable=False, default=0)
    evidence_path = Column(String, nullable=True)
    evidence_name = Column(String, nullable=True)
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_at = Column(DateTime, default=utcnow)


class SuperEvent(Base):
    """Evento "padre" (reunión 2026-09-21, ítem 19) que agrupa eventos hijos independientes de un
    mismo cliente. Solo agrupa: parámetros, registro y reportes de cada hijo siguen separados."""
    __tablename__ = 'super_events'
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, ForeignKey('tenants.id'), nullable=False)
    name = Column(String, nullable=False)
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    events = relationship("Event", back_populates="super_event")


class EventArea(Base):
    """Zona de un evento (reunión 2026-09-21, ítem 9a: Control de Áreas). `allow_reentry` apagado =
    la persona solo puede entrar UNA vez a esa zona (un segundo intento da alerta roja)."""
    __tablename__ = 'event_areas'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    name = Column(String, nullable=False)
    allow_reentry = Column(Boolean, default=True, server_default='true', nullable=False)
    created_at = Column(DateTime, default=utcnow)


class AreaMovement(Base):
    """Una entrada ('in') o salida ('out') de una persona a una zona, con hora exacta y método."""
    __tablename__ = 'area_movements'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    area_id = Column(Integer, ForeignKey('event_areas.id'), nullable=False)
    user_id = Column(String, nullable=False)
    tenant_id = Column(String, nullable=False)
    direction = Column(String, nullable=False)  # 'in' | 'out'
    method = Column(String, nullable=True)  # 'cedula' | 'qr' | 'facial' | 'manual'
    timestamp = Column(DateTime, default=utcnow)
    registered_by_staff_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)

    __table_args__ = (ForeignKeyConstraint(['user_id', 'tenant_id'], ['users.id', 'users.tenant_id']),)


class InventoryItem(Base):
    """Ítem a repartir en un evento (ítem 9b: Control de Inventario) con su cantidad inicial."""
    __tablename__ = 'inventory_items'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    name = Column(String, nullable=False)
    initial_qty = Column(Integer, nullable=False, default=0)
    allow_multiple = Column(Boolean, default=False, server_default='false', nullable=False)  # ¿se pueden entregar varias unidades de una vez?
    created_at = Column(DateTime, default=utcnow)


class InventoryDelivery(Base):
    """Una línea entregada (ítem + cantidad) a una persona; las de un mismo combo comparten `batch_id`."""
    __tablename__ = 'inventory_deliveries'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    item_id = Column(Integer, ForeignKey('inventory_items.id'), nullable=False)
    batch_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    tenant_id = Column(String, nullable=False)
    qty = Column(Integer, nullable=False, default=1)
    delivered_at = Column(DateTime, default=utcnow)
    delivered_by_staff_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)

    __table_args__ = (ForeignKeyConstraint(['user_id', 'tenant_id'], ['users.id', 'users.tenant_id']),)


class Job(Base):
    """Trabajo en segundo plano (app/jobs.py): tabla en Postgres hoy, Cloud Tasks / Cloud Run Jobs después."""
    __tablename__ = 'jobs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String, nullable=False)
    payload_json = Column(Text, nullable=False)
    dedupe_key = Column(String, nullable=True)
    status = Column(String, nullable=False, default='queued', server_default='queued')   # queued | running | done | failed
    attempts = Column(Integer, nullable=False, default=0, server_default='0')
    max_attempts = Column(Integer, nullable=False, default=5, server_default='5')
    run_at = Column(DateTime, nullable=False, default=utcnow)
    locked_until = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    finished_at = Column(DateTime, nullable=True)


class SystemEvent(Base):
    """Hechos del sistema para «Estado del sistema» (errores 5xx, último webhook de Wompi...). Nunca guarda datos personales."""
    __tablename__ = 'system_events'
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String, nullable=False)
    ref = Column(String, nullable=True)
    detail = Column(Text, nullable=True)
    at = Column(DateTime, nullable=False, default=utcnow)


class PrivacyRequestCounter(Base):
    """Último consecutivo de radicado por año (app/privacy_requests.py: next_radicado)."""
    __tablename__ = 'privacy_request_counters'
    year = Column(Integer, primary_key=True)
    last = Column(Integer, nullable=False, default=0, server_default='0')


class PrivacyRequest(Base):
    """Solicitud de privacidad (consulta o reclamo de habeas data): radicado AÑO-CONSECUTIVO, fecha límite en días hábiles, estado y bandera «reclamo en trámite» (migración 0061). Sin llaves foráneas."""
    __tablename__ = 'privacy_requests'
    id = Column(Integer, primary_key=True, autoincrement=True)
    radicado = Column(String(16), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    channel = Column(String(20), nullable=False)
    holder_name = Column(String, nullable=False)
    cedula = Column(String, nullable=False, index=True)
    tenant_id = Column(String, nullable=True)
    event_id = Column(Integer, nullable=True)
    request_type = Column(String(24), nullable=False)
    due_date = Column(Date, nullable=False)
    status = Column(String(16), nullable=False, default='recibida', server_default='recibida')
    claim_flag = Column(Boolean, nullable=False, default=False, server_default='false')
    claim_flag_due = Column(Date, nullable=True)
    history_json = Column(Text, nullable=True)
    created_by_staff_id = Column(Integer, nullable=True)


class SuppressedPerson(Base):
    """Huella de la cédula de quien pidió la supresión total (L4): evita volver a crearla por error. Sin datos personales."""
    __tablename__ = 'suppressed_people'
    tenant_id = Column(String, primary_key=True)
    cedula_hash = Column(String(64), primary_key=True)
    suppressed_at = Column(DateTime, nullable=False, default=utcnow)


class WebAcceptance(Base):
    """Aceptación hecha desde /aceptar (celular): vale para el reconocimiento facial solo cuando el personal confirma la identidad en puerta (`verified_at`)."""
    __tablename__ = 'web_acceptances'
    tenant_id = Column(String, primary_key=True)
    user_id = Column(String, primary_key=True)
    event_id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    verified_at = Column(DateTime, nullable=True)
    verified_by_staff_id = Column(Integer, nullable=True)
    verified_via = Column(String(12), nullable=True)      # 'staff' (en la puerta) | 'link' (abrió su enlace personal: dueño del correo)


class AuditConsentLog(Base):
    """Prueba inmutable de la autorización biométrica (migración 0054): solo INSERT (disparador + REVOKE al rol de la app), SIN llaves foráneas, 3 años mínimo, ninguna purga la toca.
    Nada en el código la modifica ni la borra; la lectura es solo para super_admin y fuera de la interfaz (ver app/consent.py y scripts/export_consent_logs.py)."""
    __tablename__ = 'audit_consent_logs'
    id = Column(String(36), primary_key=True)       # lo genera el dispositivo: un reintento sin conexión no duplica
    tenant_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    cedula_hash = Column(String(64), nullable=False)
    event_id = Column(Integer, nullable=False)
    consent_timestamp_utc = Column(DateTime(timezone=True), nullable=False)
    consent_version = Column(String(40), nullable=False)
    legal_text_hash = Column(String(64), nullable=False)
    accepted_biometric = Column(Boolean, nullable=False)
    confirmed_adult = Column(Boolean, nullable=False)
    ip_or_device_id = Column(String, nullable=True)
    reason = Column(String(20), nullable=False)
    __table_args__ = (CheckConstraint("reason IN ('consent', 'rejection', 'revocation')", name="ck_audit_consent_reason"),)


class PersonChange(Base):
    """Cambios manuales sobre una persona en un evento, con quién y cuándo (migración 0062): `kind='registration_status'` (valores «Registrado» / «No registrado»; `detail` = cuántos accesos se
    borraron al deshacer) y `kind='birth_date'` (fechas). Sin llaves foráneas. Al suprimir a la persona, los de estado se anonimizan (`user_id` NULL) y los de fecha de nacimiento se borran."""
    __tablename__ = 'person_changes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    at = Column(DateTime, nullable=False, default=utcnow)
    tenant_id = Column(String, nullable=False)
    event_id = Column(Integer, nullable=False)
    user_id = Column(String, nullable=True)
    staff_user_id = Column(Integer, nullable=True)
    kind = Column(String(24), nullable=False)
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)
    detail = Column(String, nullable=True)


class AcceptMailLog(Base):
    """Registro de cada envío del enlace personal de autorización (migración 0065, app/acceptmail.py): quién (cédula), cuándo y con qué resultado. SIN IP ni User-Agent (decisión de la auditora).
    `kind`: bulk (envío masivo) | test (envío de prueba, sin persona) | export (descarga de enlaces) | control (inicio/parada/fin de una tanda). `result`: reserving (reservado, aún sin respuesta)
    | sent | failed | unknown (se reservó y el proceso se cayó: NO se reenvía solo) | start | stop | done. Sin llaves foráneas; al suprimir a la persona `user_id` queda en NULL."""
    __tablename__ = 'accept_mail_log'
    id = Column(Integer, primary_key=True, autoincrement=True)
    at = Column(DateTime, nullable=False, default=utcnow)
    tenant_id = Column(String, nullable=False)
    event_id = Column(Integer, nullable=False)
    user_id = Column(String, nullable=True)
    staff_user_id = Column(Integer, nullable=True)
    kind = Column(String(8), nullable=False)
    result = Column(String(10), nullable=False)
    run_id = Column(String, nullable=True)
    detail = Column(String, nullable=True)


# ------------------------------------------------------------------ relojes de la retención biométrica (app/privacy.py)
@sa_event.listens_for(Event.status, "set", active_history=True)     # active_history: carga el valor anterior aunque la instancia esté expirada
def _stamp_finalized(target, value, oldvalue, initiator):
    """`finalized_at` se estampa al pasar a «finalizado» y se limpia al reabrir (el reloj de los 7 días se reinicia)."""
    if value == oldvalue:
        return
    if value == "finalizado":
        target.finalized_at = utcnow()
    elif oldvalue == "finalizado":
        target.finalized_at = None


@sa_event.listens_for(User.face_encoding, "set")
def _stamp_face_captured(target, value, oldvalue, initiator):
    """`face_captured_at` = cuándo se guardó el rostro (un rostro repetido idéntico no reinicia el reloj del tope)."""
    if value and value == oldvalue:
        return
    target.face_captured_at = utcnow() if value else None


class PrintDevice(Base):
    """Último equipo con el que cada usuario abrió el Registro de un evento con impresión compartida: plataforma, navegador y si tiene la impresora USB
    conectada (lo reporta el propio equipo cada pocos segundos). Sin datos de personas ni direcciones IP."""
    __tablename__ = 'print_devices'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    staff_user_id = Column(Integer, ForeignKey('staff_users.id', ondelete='CASCADE'), nullable=False)
    device_id = Column(String(64), nullable=False)
    platform = Column(String(40), nullable=True)
    browser = Column(String(40), nullable=True)
    printer_connected = Column(Boolean, default=False, server_default='false', nullable=False)
    printer_name = Column(String(80), nullable=True)
    print_mode = Column(String(10), nullable=True)      # 0076: usb | dialog (imprime con la ventana de Chrome, lo declara la persona) | none/NULL (sin impresora); solo usb y dialog pueden ser anfitrión
    last_seen_at = Column(DateTime, nullable=False, default=utcnow)
    __table_args__ = (UniqueConstraint('event_id', 'staff_user_id', name='uq_print_device_event_staff'),)


class PrintRoute(Base):
    """A qué equipo imprime cada usuario en un evento: `printer_staff_id` NULL = en su propio equipo."""
    __tablename__ = 'print_routes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    staff_user_id = Column(Integer, ForeignKey('staff_users.id', ondelete='CASCADE'), nullable=False)
    printer_staff_id = Column(Integer, ForeignKey('staff_users.id', ondelete='CASCADE'), nullable=True)
    __table_args__ = (UniqueConstraint('event_id', 'staff_user_id', name='uq_print_route_event_staff'),)


class PrintJob(Base):
    """Una escarapela por imprimir en el equipo de otro usuario. Estados: queued → sent → printed | failed; lo que no se imprimió en PRINT_JOB_TTL queda
    `expired` (visible para reimprimir, nunca se imprime solo después). `request_id` (lo genera quien pide) evita duplicados por reintentos.
    Solo guarda el id de la inscripción (event_attendees.id), no datos de la persona."""
    __tablename__ = 'print_jobs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    attendee_id = Column(Integer, nullable=False)
    requested_by_staff_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    printer_staff_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    request_id = Column(String(64), nullable=False, unique=True)
    status = Column(String(12), nullable=False, default='queued', server_default='queued')
    error = Column(String(200), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    sent_at = Column(DateTime, nullable=True)
    done_at = Column(DateTime, nullable=True)
    prefs_json = Column(Text, nullable=True)       # 0071: parámetros de impresión del equipo que pidió (cinta, giro, espejo, corte...); NULL = los del evento


class PrintStation(Base):
    """0072: lo de UNA cuenta de puesto en UN evento, guardado en el servidor: «solo lector» y Mostrar/Esconder el menú de impresión (app/routers/print_stations.py). Otras claves que
    hayan quedado de antes se conservan y se ignoran. Sin fila, el puesto funciona como siempre."""
    __tablename__ = 'print_stations'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    staff_user_id = Column(Integer, ForeignKey('staff_users.id', ondelete='CASCADE'), nullable=False)
    settings_json = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow)
    __table_args__ = (UniqueConstraint('event_id', 'staff_user_id', name='uq_print_station_event_staff'),)


class AppSetting(Base):
    """0072: clave/valor de configuración del sistema que un admin cambia desde Configuración (p. ej. «single_session»)."""
    __tablename__ = 'app_settings'
    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow)


class SessionAudit(Base):
    """0072: sesiones cerradas, rechazadas o forzadas. Solo lo necesario (Ley 1581): cuenta, hora, tipo de dispositivo, navegador y resultado; sin IP. Se borra a los 90 días (ops_runner.purge)."""
    __tablename__ = 'session_audit'
    id = Column(Integer, primary_key=True, autoincrement=True)
    staff_user_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)
    device = Column(String(20), nullable=True)
    browser = Column(String(40), nullable=True)
    result = Column(String(20), nullable=False)


class EventTransferLog(Base):
    """0074: bitácora de exportar/importar eventos (docs/18_EXPORTAR_EVENTOS.md). Quién, cuándo, qué evento, conteos y huella del paquete; NUNCA datos personales ni el contenido."""
    __tablename__ = 'event_transfer_log'
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    kind = Column(String(12), nullable=False)               # export | import
    staff_username = Column(String(80), nullable=True)
    event_id = Column(Integer, nullable=True)               # export: el evento de origen; import: el evento NUEVO
    event_code = Column(String(80), nullable=True)
    package_sha256 = Column(String(64), nullable=True)
    status = Column(String(16), nullable=False, default='done', server_default='done')   # done | pending_confirm | confirmed | error
    counts_json = Column(Text, nullable=True)
    options_json = Column(Text, nullable=True)
    state_json = Column(Text, nullable=True)                # importación en espera: el estado original que se aplica al confirmar
    stage = Column(String(60), nullable=True)               # 0075: etapa del trabajo en segundo plano
    progress = Column(Integer, nullable=False, default=0, server_default='0')
    result_json = Column(Text, nullable=True)               # informe final (conteos y avisos, sin datos personales) o el mensaje de error
    file_key = Column(String(300), nullable=True)           # el .zip generado en el almacenamiento (se borra a las 24 h)
    finished_at = Column(DateTime, nullable=True)


class EventImportActor(Base):
    """0074: nombre de usuario (texto) de quien hizo un registro en el entorno de ORIGEN cuando esa cuenta no existe aquí: el enlace queda vacío y el texto se conserva."""
    __tablename__ = 'event_import_actors'
    id = Column(Integer, primary_key=True, autoincrement=True)
    import_id = Column(Integer, ForeignKey('event_transfer_log.id', ondelete='CASCADE'), nullable=False, index=True)
    table_name = Column(String(40), nullable=False)
    row_ref = Column(String(160), nullable=False)
    column_name = Column(String(40), nullable=False)
    username = Column(String(80), nullable=False)


class EventStatusChange(Base):
    """0077: bitácora de los retrocesos de estado de un evento («en curso» -> «creado», `POST /events/{id}/revert-to-created`): quién, cuándo, motivo (opcional) y cuántas personas e ingresos
    tenía en ese momento. Solo INSERT. Sin llaves foráneas (sobrevive al evento y no estorba al borrarlo). Marca además la ventana de 7 días en que los quioscos sin red todavía pueden
    sincronizar lo que registraron ANTES del cambio (`app/status_changes.py`). Nunca guarda datos personales."""
    __tablename__ = 'event_status_changes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    at = Column(DateTime, nullable=False, default=utcnow)
    event_id = Column(Integer, nullable=False, index=True)
    tenant_id = Column(String, nullable=True)
    staff_user_id = Column(Integer, nullable=True)
    staff_username = Column(String(80), nullable=True)
    from_status = Column(String(12), nullable=False)
    to_status = Column(String(12), nullable=False)
    reason = Column(String(500), nullable=True)
    attendees_count = Column(Integer, nullable=False, default=0, server_default='0')
    access_logs_count = Column(Integer, nullable=False, default=0, server_default='0')


class ReprintRequest(Base):
    """Fase 1B (0083): solicitud de permiso para reimprimir la escarapela de alguien que ya se imprimió, en un evento con la reimpresión DESHABILITADA (app/reprint.py).
    Estados: pending → approved | denied | expired; approved → used | expired. Las transiciones son UPDATE atómicos condicionados al estado. `expires_at` es el límite vigente:
    mientras está pendiente, el de la solicitud; al aprobar, el del permiso (REPRINT_APPROVAL_MINUTES)."""
    __tablename__ = 'reprint_requests'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    tenant_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    requested_by_staff_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    approver_staff_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)   # el coordinador del evento al pedirla (NULL = no tenía: decide un admin)
    status = Column(String(12), nullable=False, default='pending', server_default='pending')
    requested_at = Column(DateTime, nullable=False, default=utcnow)
    expires_at = Column(DateTime, nullable=False)
    screen_seen_at = Column(DateTime, nullable=True)      # la pantalla del coordinador la mostró (así se sabe que tiene sesión activa)
    email_sent_at = Column(DateTime, nullable=True)       # se decidió enviar el correo de respaldo (reserva atómica)
    decided_at = Column(DateTime, nullable=True)
    decided_by_staff_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    decided_channel = Column(String(10), nullable=True)   # screen | email
    used_at = Column(DateTime, nullable=True)
    used_channel = Column(String(12), nullable=True)      # shared | local


class ReprintLink(Base):
    """Enlace de correo de UN SOLO USO: solo el hash SHA-256 del token; ligado a una solicitud y a un destinatario."""
    __tablename__ = 'reprint_links'
    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(Integer, ForeignKey('reprint_requests.id', ondelete='CASCADE'), nullable=False)
    staff_id = Column(Integer, ForeignKey('staff_users.id', ondelete='CASCADE'), nullable=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    used_at = Column(DateTime, nullable=True)


class ReprintAudit(Base):
    """Auditoría de la reimpresión: una fila por hecho (requested, screen, email, approved, denied, expired, used). Solo se agregan filas."""
    __tablename__ = 'reprint_audit'
    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(Integer, ForeignKey('reprint_requests.id', ondelete='CASCADE'), nullable=False)
    at = Column(DateTime, nullable=False, default=utcnow)
    kind = Column(String(16), nullable=False)
    staff_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    channel = Column(String(12), nullable=True)


class StatsLink(Base):
    """Enlace de SOLO LECTURA a las estadísticas de un evento o de un formulario: sin usuario ni contraseña, con vencimiento y revocable. Solo se guarda el hash
    SHA-256 del token (nunca el token). Muestra únicamente agregados: no deja descargar nada ni ver personas."""
    __tablename__ = 'stats_links'
    id = Column(Integer, primary_key=True, autoincrement=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    scope = Column(String(6), nullable=False)                 # event | form
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    form_id = Column(Integer, ForeignKey('web_forms.id', ondelete='CASCADE'), nullable=True)
    tenant_id = Column(String, nullable=False)
    label = Column(String(80), nullable=True)
    created_by_staff_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)



class AuditAction(Base):
    """Registro de acciones administrativas (Fase 3, 0088): quién archivó, restauró o borró qué y cuándo. Solo se INSERTA. Sin datos personales: id y nombre de la entidad (p. ej. la
    empresa cliente), nunca contactos, cédulas ni rostros."""
    __tablename__ = 'audit_actions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    at = Column(DateTime, nullable=False, default=utcnow)
    actor_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    actor_role = Column(String(20), nullable=True)
    action = Column(String(40), nullable=False)          # archive | restore | delete | edit …
    entity = Column(String(40), nullable=False)          # tenant | event | …
    entity_id = Column(String(64), nullable=False)
    entity_name = Column(String(200), nullable=True)
    detail = Column(String(500), nullable=True)
