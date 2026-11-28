import json
from sqlalchemy import event as sa_event
from sqlalchemy import BigInteger, CheckConstraint, Column, Integer, String, DateTime, Date, Boolean, Float, Numeric, ForeignKey, Text, ForeignKeyConstraint, UniqueConstraint, Index, text
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

class Organization(Base):
    """0162 (SaaS, pieza 1): la EMPRESA que usa la plataforma (Golden = fila 1). Un nivel por encima de `Tenant` (los clientes de esa empresa). Reglas y planes: app/orgs.py; pantalla: /plataforma."""
    __tablename__ = 'organizations'
    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(60), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    legal_name = Column(String(200), nullable=True)
    nit = Column(String(40), nullable=True)
    contact_email = Column(String(200), nullable=True)
    contact_phone = Column(String(40), nullable=True)
    plan = Column(String(20), default='basico', server_default='basico', nullable=False)  # 'interno' | 'basico' | 'pro' | 'empresa' (app/orgs.PLANS)
    entitlements_json = Column(Text, nullable=True)  # límites propios que pisan los del plan (JSON; clave en null = sin límite). NULL = solo lo del plan
    status = Column(String(12), default='active', server_default='active', nullable=False)  # 'active' | 'suspended'
    created_at = Column(DateTime, default=utcnow)
    notes = Column(Text, nullable=True)


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
    legacy_client_code = Column(String, unique=True, nullable=True)  # 0130 (CRM C1a): el código hexadecimal de antes cuando el cliente pasó al número consecutivo del CRM; alias para paquetes de eventos viejos (app/event_transfer.py). NULL = nunca cambió
    org_id = Column(Integer, nullable=True, default=1, server_default='1', index=True)  # 0162 (SaaS, pieza 1): empresa a la que pertenece el cliente (NULL o 1 = Golden). Sin llave foránea todavía; ver app/orgs.py

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
    code = Column(String(64), nullable=True)  # 0140: código de la persona EN este evento (serial del QR, aparte de la cédula); único por evento sin distinguir mayúsculas; app/person_code.py
    from_peer = Column(Boolean, nullable=True)  # 0160 (servidor local, evento compartido): la persona la dio de alta OTRO servidor; la subida no la devuelve
    last_action_at = Column(DateTime, nullable=True)  # 0082 (cola compartida): hora del SERVIDOR de la última alta/acreditación en ESTE evento; NULL = sin acción desde que existe la columna
    archived_at = Column(DateTime, nullable=True)  # sin uso: reservado (0091). Las personas se BORRAN del evento (decisión 7-nov-2026); lo que se archiva es la base del evento (events.data_archived_at). Nada la lee ni la escribe
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
    from_peer = Column(Boolean, nullable=True)  # 0160 (servidor local, evento compartido): llegó de OTRO servidor vía la nube; la subida no la devuelve
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
    from_peer = Column(Boolean, nullable=True)          # 0160: llegó de otro servidor local (evento compartido); no se vuelve a subir
    kind = Column(String(10), nullable=False, default='normal', server_default='normal')          # 0150: 'normal' | 'pre' (escarapela PREIMPRESA antes de que la persona llegue; módulo Preimpresiones)

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
    extra_roles = Column(String, nullable=True)  # 0103 (8-nov-2026): roles que se SUMAN al principal, separados por coma (p. ej. 'comercial,admin'); la unión de permisos la resuelve auth.effective_roles. secondary_role queda como espejo del primero entre coordinador/comercial (consultas heredadas)
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
    client_temp = Column(Boolean, default=False, server_default='false', nullable=False)  # 0129 (12-nov-2026): cliente temporal del evento = digitador (mismos permisos) con usuario y contraseña aleatorios, sin solicitud de ingreso (app/temp_client.py)
    event_only = Column(Boolean, default=False, server_default='false', nullable=False)  # 0146 (16-nov-2026): coordinador temporal del evento = rol coordinador SOLO sobre los eventos que se le asignan (EventStaffAuthorization), sin las pantallas globales (app/event_only.py)
    archived_at = Column(DateTime, nullable=True)  # 0089 (Fase 3): NULL = normal; con fecha = archivada (no inicia sesión, no sale en listas ni selectores; se restaura). Ver app/routers/staff.py
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    org_id = Column(Integer, nullable=True, default=1, server_default='1', index=True)  # 0162 (SaaS, pieza 1): empresa a la que pertenece la cuenta (NULL o 1 = Golden). Sin llave foránea todavía; ver app/orgs.py

    tenant = relationship("Tenant", foreign_keys=[tenant_id])          # explícitas desde 0088/0089: hay más de una llave entre staff_users y tenants / staff_users y sí misma
    created_by = relationship("StaffUser", remote_side=[id], foreign_keys=[created_by_id])


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
    event_type_id = Column(Integer, ForeignKey('event_types.id'), nullable=True)  # 0128 (Fase 10, C): «Categoría (tipo de evento)»; NULL = «Sin categoría». Lista en Configuración (super_admin)
    super_event_id = Column(Integer, ForeignKey('super_events.id'), nullable=True)  # ítem 19: superevento al que pertenece (NULL = evento suelto)
    certificates_enabled = Column(Boolean, default=False, server_default='false', nullable=False)  # ítem 5: módulo de certificados activado desde Parámetros
    certificates_token = Column(String, unique=True, nullable=True)  # enlace público /c/<token> para que cada persona descargue su certificado (2026-09-23)
    staff_mail_enabled = Column(Boolean, default=True, server_default='true', nullable=False)   # 0100 (Fase 4): al asignar un digitador temporal a este evento se le envía un correo con los datos del evento y el enlace de ingreso (si tiene correo); se apaga desde «Usuarios del evento»
    digital_badge_enabled = Column(Boolean, default=False, server_default='false', nullable=False)  # ítem 17: escarapela digital activada desde Parámetros
    digital_badge_fields = Column(Text, nullable=True)  # 0099: lista JSON de claves de datos de la persona visibles en la escarapela digital pública (app/digital_fields.py); NULL = solo lo que usa la plantilla
    pledge_enabled = Column(Boolean, default=False, server_default='false', nullable=False)  # 0100: el evento exige el compromiso digital del digitador (app/pledge.py); sin firmarlo no entra a la fila de autorización. El enlace público es el formulario web `kind='pledge'` del evento
    areas_enabled = Column(Boolean, default=False, server_default='false', nullable=False)  # ítem 9a: Control de Áreas activado desde Parámetros
    inventory_enabled = Column(Boolean, default=False, server_default='false', nullable=False)  # ítem 9b: Control de Inventario activado desde Parámetros
    areas_dwell_enabled = Column(Boolean, default=False, server_default='false', nullable=False)  # 0122 (Fase 10): contar el tiempo de permanencia en las zonas (entradas y salidas suman)
    dwell_prize_enabled = Column(Boolean, default=False, server_default='false', nullable=False)  # 0122: «premio por porcentaje de estadía» (certificado / entrega solo a quien llegue al porcentaje)
    dwell_reference_minutes = Column(Integer, nullable=True)  # 0122: el 100 % en minutos (lo define el coordinador); NULL = la duración del evento
    dwell_threshold_pct = Column(Integer, nullable=True)  # 0122: porcentaje mínimo para cumplir (NULL = 80)
    areas_autoscan = Column(Boolean, default=False, server_default='false', nullable=False)  # 0122: escanear / Enter registra la entrada o salida sin pulsar «Acreditar»
    code_enabled = Column(Boolean, default=False, server_default='false', nullable=False)  # 0140: el evento usa «código» (serial del QR distinto de la cédula); al escanear se busca primero por ID y luego por código (app/person_code.py)
    code_required = Column(Boolean, default=False, server_default='false', nullable=False)
    code_search_first = Column(Boolean, default=False, server_default='false', nullable=False)
    code_search_only = Column(Boolean, default=False, server_default='false', nullable=False)  # 0168: lo buscado en números solo se compara con el código (nunca con la cédula); excluyente con code_search_first  # 0166: con el código activo, el buscador del registro y el escaneo dan prioridad al código sobre la cédula  # 0140: con el código activo, ¿es obligatorio al registrar?
    # 0169 (26-nov-2026): cómo se busca a la persona EN CADA PANTALLA: 'id_first' | 'code_first' | 'code_only' | 'id_only' (app/person_code.search_mode).
    # Reemplaza a code_search_first / code_search_only (se quedan en la tabla, ya no se leen).
    code_search_registro = Column(String(12), default='id_first', server_default='id_first', nullable=False)
    code_search_inventario = Column(String(12), default='id_first', server_default='id_first', nullable=False)
    code_search_zonas = Column(String(12), default='id_first', server_default='id_first', nullable=False)
    inventory_autoscan = Column(Boolean, default=False, server_default='false', nullable=False)  # 0122: escanear / Enter entrega lo marcado sin pulsar «Entregar»
    inventory_mode = Column(String(10), nullable=True)  # 0161: NULL/'choose' = la persona elige (lo de siempre) | 'assigned' = la base lo define (app/inv_assign.py)
    inventory_assign_json = Column(Text, nullable=True)  # 0161: columnas que mandan en el modo 'assigned' {holder_product, holder_qty, dep_product, dep_qty}
    areas_config_locked = Column(Boolean, default=False, server_default='false', nullable=False)  # 0161: la tableta del digitador queda fija en la zona y el movimiento elegidos (app/config_lock.py)
    inventory_config_locked = Column(Boolean, default=False, server_default='false', nullable=False)  # 0161: la tableta del digitador queda fija en lo marcado para entregar
    config_unlock_hash = Column(String, nullable=True)  # 0161: contraseña de desbloqueo de la configuración del digitador (hash, nunca el texto)
    dependents_badge = Column(Boolean, default=False, server_default='false', nullable=False)  # 0161: imprimir escarapela también a los dependientes (app/dependents.py)
    archived_at = Column(DateTime, nullable=True)      # 0090 (Fase 3): NULL = activo; con fecha = archivado (solo eventos finalizados; oculto de listas y selectores, sin registro ni formularios, NADA se borra; se restaura). Ver app/event_archive.py
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)      # quién lo archivó; NULL con archived_at = archivado por el Job (L7, 90 días)
    data_archived_at = Column(DateTime, nullable=True)      # 0090 (L7): la BASE DE DATOS del evento (personas y respuestas) quedó archivada a los 90 días de cerrado; el evento SIGUE en las listas. Solo un super_admin la desarchiva. Ver app/event_archive.py
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
    brand_color = Column(String, nullable=True)  # 0098: color de marca del evento '#rrggbb' (NULL = el dorado general de Golden); app/brandcolor.py
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
    each_accepts = Column(Boolean, default=False, server_default='false', nullable=False)   # 0165: tercer origen «cada quien acepta» (formulario/QR): escáner sin cédula, con «Acepto» y solo reconoce a quienes ya aceptaron
    precalculo_autorizado = Column(Boolean, default=False, server_default='false', nullable=False)   # regla A: solo super_admin, solo evento de tercero, con la referencia y fecha del anexo firmado
    precalculo_anexo_ref = Column(String, nullable=True)
    precalculo_anexo_fecha = Column(Date, nullable=True)
    review_detail = Column(Boolean, default=False, server_default='false', nullable=False)  # 0143: «Revisar el detalle»: la comercial lo marca para que el equipo lea las observaciones; en el calendario sale un triángulo rojo con «!»
    auto_register = Column(Boolean, default=False, nullable=False)  # 2026-09-16 (Sprint 2.2, Fase B): mismo criterio que auto_print_badge, pero para el registro en sí. Apagado por default: un match (facial o cédula, cualquier método) NO acredita solo — solo deja el match "pendiente" (result=MATCH_PENDING) hasta que el digitador confirme con "Guardar y autorizar acceso". Prendido, un match acredita de una, como se comportaba todo antes de este cambio.
    selfreg_enabled = Column(Boolean, default=False, server_default='false', nullable=False)      # 0115 (Fase 8): «Autorregistro sin base de datos»: pantalla de kiosco para que la persona se cree sola (app/selfreg.py). APAGADO por defecto
    face_door_enabled = Column(Boolean, default=False, server_default='false', nullable=False)
    accept_verify_photo = Column(Boolean, default=True, server_default='true', nullable=False)   # 0164 (revisión de seguridad 22-nov, hallazgo 5): en /aceptar, si quien envía la selfie NO está verificada y ya hay foto de registro, la selfie queda «pendiente» y solo sustituye a la vigente al verificarse; apagado = la selfie reemplaza la foto como antes
    accept_no_birth_mode = Column(String, default='any', server_default='any', nullable=False)   # 0096 (D5): con la base SIN fecha de nacimiento, /aceptar acepta 'any' (cualquier fecha adulta, como antes) o 'require_personal_link' (solo con el enlace personal del correo); los eventos nuevos nacen con el segundo
    idle_minutes = Column(Integer, nullable=True)   # 0081: minutos de inactividad antes de cerrar la sesión del personal que trabaja en este evento (5-60), SOLO mientras está en proceso; NULL = el general (SESSION_IDLE_MINUTES, 10). app/idle.py
    face_door_liveness = Column(Boolean, default=True, server_default='true', nullable=False)   # 0068: prueba de movimiento en la entrada con rostro (app/liveness.py); encendida por defecto
    badge_bio_photo_allowed = Column(Boolean, default=False, server_default='false', nullable=False)   # A1 (0067): imprimir la foto BIOMÉTRICA en la escarapela; apagado = no se imprime (recuadro gris). Solo super_admin   # B1 (0066): pantalla de autoservicio «Entrar con mi rostro» (app/routers/door.py); apagada por defecto
    extra_json = Column(Text, nullable=True)   # 0087 (Fase 2): valores de los campos PERSONALIZADOS de la plantilla de evento {clave: valor} (app/event_template.py). Los campos base y los interruptores siguen en sus columnas
    billed_at = Column(DateTime, nullable=True)      # 0105 (Fase 5): cuándo se puso el evento en un estado de facturación («Facturado», regla client_delivery); NULL si no lo está. El historial completo queda en audit_actions
    billed_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)      # quién lo puso (comercial o admin)
    final_db_key = Column(String, nullable=True)      # 0105 (Fase 5): «base de datos final» procesada por humanos (xlsx/csv), clave en app/storage.py; NO es la base de estadísticas
    final_db_name = Column(String, nullable=True)      # nombre original del archivo (solo para mostrarlo)
    final_db_uploaded_at = Column(DateTime, nullable=True)
    final_db_uploaded_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    public_slug = Column(String, nullable=True)      # 0113 (D2.5k): nombre del enlace limpio de inscripciones (/<evento>/<formulario>); ÚNICO en todo el sistema (índice en minúsculas). app/public_slug.py
    local_node_name = Column(String, nullable=True)      # 0111 (Fase 6): nombre del servidor local que TIENE el evento (arrendamiento: un solo escritor). NULL = el evento vive en la nube. Mientras esté puesto, la nube lo muestra en solo lectura
    local_since = Column(DateTime, nullable=True)        # desde cuándo está en ese servidor local
    local_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)      # quién lo puso en local
    queue_enabled = Column(Boolean, default=False, server_default='false', nullable=False)      # 0116 (Fase 8): «Turnos y filas» activado desde Parámetros (app/queue_turns.py)
    queue_config_json = Column(Text, nullable=True)      # configuración de los turnos: orden, filas (letras), mostrar nombre… (queue_turns.clean_config); NULL = la de fábrica
    local_last_upload_at = Column(DateTime, nullable=True)      # última vez que el servidor local subió lo suyo a la nube
    local_mode = Column(String(10), nullable=True)      # 0160: «Usará servidores locales» — cloud | peer | hub (app/event_lease.MODES); solo cloud funciona hoy y enciende local_shared
    local_shared = Column(Boolean, default=False, server_default='false', nullable=False)      # 0160: el evento acepta VARIOS servidores locales a la vez (nube como puente; docs/23_EVENTO_COMPARTIDO_NUBE.md). En el servidor local: esta copia es compartida
    peer_cursor = Column(Text, nullable=True)      # 0160 (servidor local): hasta dónde bajó los cambios de los otros servidores (JSON {a, l, p, c, at}: últimos ids de la nube)
    # --- Lado del SERVIDOR LOCAL (0112, Fase 6): solo se usan cuando este evento es una copia bajada de la nube (LOCAL_SERVER=1); en la nube quedan NULL ---
    cloud_event_id = Column(Integer, nullable=True)      # id que tiene este evento en la nube (lo fija «Descargar a local»); NULL = no es una copia de la nube, no se sube
    sync_log_id = Column(Integer, nullable=True)         # marca de agua: último AccessLog.id local ya CONFIRMADO por la nube
    sync_persons_at = Column(DateTime, nullable=True)    # marca de agua: último alta local (EventAttendee.created_at) ya confirmada por la nube
    sync_print_id = Column(Integer, nullable=True)       # 0157: marca de agua: último PrintLog.id local ya CONFIRMADO por la nube
    sync_change_id = Column(Integer, nullable=True)      # 0157: marca de agua: último PersonChange.id local ya CONFIRMADO por la nube
    sync_package_at = Column(DateTime, nullable=True)    # cuándo se bajó el paquete del evento desde la nube
    sync_edit_id = Column(Integer, nullable=True)        # 0160: último PersonChangeLog.id local (ediciones de datos) ya CONFIRMADO por la nube
    sync_area_id = Column(Integer, nullable=True)        # 0160: último AreaMovement.id local ya confirmado
    sync_delivery_id = Column(Integer, nullable=True)    # 0160: último InventoryDelivery.id local ya confirmado
    sync_turn_id = Column(Integer, nullable=True)        # 0160: último QueueTurn.id local ya confirmado
    sync_call_id = Column(Integer, nullable=True)        # 0160: último QueueCall.id local ya confirmado
    sync_turn_at = Column(DateTime, nullable=True)       # 0160: hasta cuándo subió el ESTADO (llamado/atendido) de los turnos ya enviados
    sync_roulette_id = Column(Integer, nullable=True)    # 0160: último RouletteDraw.id local ya confirmado
    sync_lead_id = Column(Integer, nullable=True)        # 0160: último ExhibitorLead.id local ya confirmado
    sync_accept_at = Column(DateTime, nullable=True)     # 0160: hasta cuándo subieron las aceptaciones/firmas (creadas o verificadas)
    sync_consent_at = Column(DateTime, nullable=True)    # 0160: hasta cuándo subieron las autorizaciones de datos (audit_consent_logs)
    sync_attempt_at = Column(DateTime, nullable=True)    # último intento de subida (bien o mal)
    sync_error = Column(String(300), nullable=True)      # motivo del último fallo (sin datos personales); NULL = el último intento salió bien

    tenant = relationship("Tenant")
    created_by = relationship("StaffUser", foreign_keys=[created_by_id])
    coordinator = relationship("StaffUser", foreign_keys=[coordinator_staff_id])
    commercial = relationship("StaffUser", foreign_keys=[commercial_staff_id])
    billed_by = relationship("StaffUser", foreign_keys=[billed_by_id])
    local_by = relationship("StaffUser", foreign_keys=[local_by_id])
    final_db_uploaded_by = relationship("StaffUser", foreign_keys=[final_db_uploaded_by_id])
    super_event = relationship("SuperEvent", back_populates="events")
    state = relationship("EventState")
    event_type = relationship("EventType")
    shared_nodes = relationship("EventLocalNode", cascade="all, delete-orphan", order_by="EventLocalNode.joined_at")          # 0160: servidores locales de un evento compartido (solo se lee si local_shared)

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
    archived_at = Column(DateTime, nullable=True)          # 0094 (Fase 3): NULL = activo; archivado = fuera de listas y selectores, se restaura. Sin relationship a StaffUser: no hay ambigüedad de llaves.
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)

    def get_rules(self) -> dict:
        return json.loads(self.rules_json) if self.rules_json else {}


class EventType(Base):
    """Tipo de evento (Feria, Congreso…): la categoría con la que el calendario filtra. La lista la administra el super_admin (agregar, renombrar, archivar, color opcional); archivar NO toca los eventos
    que ya la tienen (siguen mostrándola), solo deja de ofrecerla al crear o editar."""
    __tablename__ = 'event_types'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False, unique=True)
    color = Column(String(9), nullable=True)
    position = Column(Integer, nullable=False, default=0, server_default='0')
    created_at = Column(DateTime, default=utcnow)
    archived_at = Column(DateTime, nullable=True)
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)


class EventContact(Base):
    """Contacto del CLIENTE en UN evento (16-nov-2026): quién es y para qué (`note`, p. ej. «Quien aprueba» o «Logística en sitio»). Puede venir de un contacto del CRM (`crm_contact_id`, copia de sus datos
    al elegirlo) o escribirse a mano (nombre + teléfono). El PRINCIPAL (uno solo por evento) recibe el informe final y la encuesta. DATOS PERSONALES (Ley 1581): al suprimir el contacto en el CRM
    se borran estas filas (app/crm/erase.py). No viaja en el paquete de exportar/importar; «Duplicar evento» sí los copia."""
    __tablename__ = 'event_contacts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    crm_contact_id = Column(Integer, ForeignKey('crm_contacts.id', ondelete='SET NULL'), nullable=True)
    name = Column(String(200), nullable=False)
    phone = Column(String(60), nullable=True)
    email = Column(String(200), nullable=True)
    note = Column(String(200), nullable=True)
    is_primary = Column(Boolean, nullable=False, default=False, server_default=text('false'))
    position = Column(Integer, nullable=False, default=0, server_default='0')
    created_at = Column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (Index('ix_event_contacts_event', 'event_id'), Index('uq_event_contacts_primary', 'event_id', unique=True, postgresql_where=text('is_primary')))


class EventStaffAuthorization(Base):
    """Qué staff_user puede operar en qué evento. Obligatorio para digitadores (acceso temporal);
    para coordinador/admin/super_admin no se exige (tienen alcance de tenant/global)."""
    __tablename__ = 'event_staff_authorizations'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    staff_user_id = Column(Integer, ForeignKey('staff_users.id'), nullable=False)
    authorized_by_id = Column(Integer, ForeignKey('staff_users.id'))
    authorized_at = Column(DateTime, default=utcnow)
    login_approved_at = Column(DateTime, nullable=True)  # 0167: el coordinador ya autorizó UNA vez el ingreso de este digitador en este evento (app/login_control.py)

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
FIELD_TYPES = ("text_short", "text_long", "select", "boolean", "consent", "signature", "email", "number")          # "number" (21-nov-2026): solo acepta números
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
    show_in_card = Column(Boolean, nullable=True)  # 0161: se ve en la tarjeta de la persona en Registro sin abrir «Editar»; NULL = de fábrica (cédula, nombres y apellidos sí; lo demás no)
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
    archived_at = Column(DateTime, nullable=True)  # 0092 (Fase 3): NULL = activo; con fecha = archivado (oculto, se restaura, conserva historial)
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)

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
    payment_account_id = Column(Integer, ForeignKey('payment_accounts.id', ondelete='SET NULL'), nullable=True)      # 0118 (Fase 8): con qué cuenta de cobro de Wompi cobra este formulario; NULL = la de Golden
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
    is_primary = Column(Boolean, nullable=False, default=False, server_default='false')  # 0113: el formulario que abre /<evento> (sin nombre de formulario); uno por evento (si ninguno, el único abierto)
    kind = Column(String(20), nullable=False, default='registration', server_default='registration')  # 0100: 'registration' (inscripción, de siempre) | 'pledge' (compromiso digital del digitador, app/pledge.py: no alimenta la base del evento ni sale en la lista de formularios)
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
    sensitive_json = deferred(Column(EncryptedText, nullable=True))   # 0100 (deferred: no se carga ni descifra al listar inscripciones): respuestas de campos marcados `sensitive` (salud, contacto de emergencia), CIFRADAS con app/crypto.py y fuera de data_json; se borran por retención (formsvc.purge_sensitive)
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


class PaymentAccount(Base):
    """Cuenta de cobro de Wompi de un TERCERO (Fase 8, 0118): alguien nos presta su comercio de Wompi y un formulario cobra con SUS llaves; el dinero entra a SU cuenta. La de Golden NO está aquí: sigue en
    variables de entorno. `public_key` es pública (pub_…); la privada, el secreto de integridad y el de eventos van CIFRADOS (Fernet, PAYMENT_KEYS_ENCRYPTION_KEY: app/payment_accounts.py) y nunca salen por la API.
    `ref` = identificador opaco para la URL de eventos de ESA cuenta (/webhooks/wompi/<ref>)."""
    __tablename__ = 'payment_accounts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    ref = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    holder = Column(String, nullable=True)                 # quién es el titular del comercio (solo texto, para reconocerla)
    public_key = Column(String, nullable=False)
    private_enc = Column(Text, nullable=True)
    integrity_enc = Column(Text, nullable=False)
    events_enc = Column(Text, nullable=False)
    active = Column(Boolean, nullable=False, default=True, server_default='true')
    note = Column(Text, nullable=True)
    # 0124 (Fase 10 B): a qué pertenece la cuenta. «general» = cualquier formulario; «evento» = formularios de ese evento (varias cuentas por evento); «formulario» = solo ese; «panelista» = cuenta de un
    # panelista/expositor (texto libre en panelist_ref; event_id opcional). Solo limita las asignaciones NUEVAS: nada se asigna solo.
    scope = Column(String(12), nullable=False, default='general', server_default='general')
    event_id = Column(Integer, ForeignKey('events.id', ondelete='SET NULL'), nullable=True, index=True)
    form_id = Column(Integer, nullable=True)          # sin FK a propósito: web_forms ya apunta a payment_accounts y una llave en el otro sentido haría un ciclo al crear las tablas
    panelist_ref = Column(String(120), nullable=True)
    created_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


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
    account_id = Column(Integer, ForeignKey('payment_accounts.id', ondelete='SET NULL'), nullable=True)      # 0118 (Fase 8): cuenta de cobro de Wompi con la que se cobró; NULL = la de Golden (variables de entorno)


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
    archived_at = Column(DateTime, nullable=True)          # 0094 (Fase 3): archivar = fuera de la librería (se restaura)
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)


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
    from_peer = Column(Boolean, nullable=True)          # 0160: llegó de otro servidor local (evento compartido); no se vuelve a subir
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
    archived_at = Column(DateTime, nullable=True)  # 0092 (Fase 3): NULL = activo; con fecha = archivado (oculto, se restaura, conserva historial)
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)


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
    archived_at = Column(DateTime, nullable=True)  # 0093 (Fase 3): NULL = activo; con fecha = archivado (oculto, conserva el archivo, se restaura)
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)


class EventAct(Base):
    """Acta de novedades del evento (Fase 10, 0126; app/routers/event_acts.py): lo ocurrido en el evento, en texto o lista, con la firma dibujada del coordinador y la del cliente (PNG en
    el almacenamiento, por app/storage.py). Varias por evento. Queda «firmada» cuando están las dos firmas; entonces el texto ya no cambia (`content_hash` = SHA-256 del texto al firmar)."""
    __tablename__ = 'event_acts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    title = Column(String(160), nullable=False)
    format = Column(String(10), nullable=False, default='text', server_default='text')          # text (párrafo) | list (un punto por línea)
    body = Column(Text, nullable=False, default='', server_default='')
    coordinator_sig_key = Column(String(300), nullable=True)
    coordinator_name = Column(String(160), nullable=True)
    coordinator_signed_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    coordinator_signed_at = Column(DateTime, nullable=True)
    client_sig_key = Column(String(300), nullable=True)
    client_name = Column(String(160), nullable=True)
    client_signed_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    client_signed_at = Column(DateTime, nullable=True)
    content_hash = Column(String(64), nullable=True)
    pdf_key = Column(String(300), nullable=True)          # PDF generado al quedar firmada (reportlab); NULL = aún no / falló: se puede regenerar
    pdf_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow)
    __table_args__ = (Index('ix_event_acts_event', 'event_id', 'created_at'),)


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
    archived_at = Column(DateTime, nullable=True)  # 0093 (Fase 3)
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    # 0147 (legalizaciones en el formato oficial de Golden, 14-nov-2026). Todo opcional: los gastos viejos quedan como kind='otro'.
    # `category`/`responsible` siguen siendo obligatorias: en un gasto nuevo `category` lleva el nombre del rubro y `responsible` al coordinador.
    # `amount` es SIEMPRE el valor total de la línea (en alimentación, la suma de las comidas).
    kind = Column(String(20), nullable=False, default='otro', server_default='otro')   # EXPENSE_KINDS
    expense_date = Column(Date, nullable=True)
    tax_id = Column(String, nullable=True)        # NIT o cédula de quien cobra
    vendor_name = Column(String, nullable=True)   # establecimiento, taxista, hotel, digitador(a)…
    address = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    origin = Column(String, nullable=True)        # desde / hasta (pasajes y taxis)
    destination = Column(String, nullable=True)
    concept = Column(String, nullable=True)       # concepto (en «otros gastos»: el detalle)
    plate = Column(String, nullable=True)
    vehicle = Column(String(10), nullable=True)   # taxis en la ciudad: 'taxi' | 'otro'
    iva = Column(Numeric(14, 2), nullable=True)
    has_support = Column(Boolean, nullable=True)  # SOPORTE (S/N): tiene recibo o factura
    breakfast = Column(Numeric(14, 2), nullable=True)
    lunch = Column(Numeric(14, 2), nullable=True)
    dinner = Column(Numeric(14, 2), nullable=True)
    snack = Column(Numeric(14, 2), nullable=True)
    unit_value = Column(Numeric(14, 2), nullable=True)
    observation = Column(Text, nullable=True)
    approved = Column(Boolean, nullable=True)     # APROBADO: NULL = pendiente de revisar
    position = Column(Integer, nullable=True)     # 0156: orden dentro del rubro (arrastrar y soltar); NULL = anterior al orden manual
    approved_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    __table_args__ = (Index('ix_event_expenses_event_kind', 'event_id', 'kind'),)


# Tipos de gasto de una legalización: cada uno cae en una hoja/tabla del Excel (app/legalization_xlsx.py).
EXPENSE_KINDS = ("hospedaje", "pasaje", "taxi_terminal", "taxi_ciudad", "alimentacion", "digitador", "otro")
# Ciclo de una legalización: el coordinador la arma (borrador), la envía, el director la aprueba o la devuelve para corregir.
LEGALIZATION_STATUSES = ("borrador", "enviada", "aprobada", "devuelta")


class EventLegalization(Base):
    """Encabezado de la legalización de un evento (una por evento): quién responde, el anticipo en pesos que se le
    entregó y en qué etapa va. El consecutivo, el CE final y las observaciones contables los escribe el área
    administrativa en el Excel, por eso no están aquí."""
    __tablename__ = 'event_legalizations'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False, unique=True)
    responsible_name = Column(String, nullable=True)
    responsible_cc = Column(String, nullable=True)
    advance_amount = Column(Numeric(14, 2), nullable=True)      # «CE. # (Anticipo)»: valor en pesos entregado al coordinador
    legalization_date = Column(Date, nullable=True)
    status = Column(String(12), nullable=False, default='borrador', server_default='borrador')
    submitted_at = Column(DateTime, nullable=True)
    submitted_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    review_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow)


class SuperEvent(Base):
    """Evento "padre" (reunión 2026-09-21, ítem 19) que agrupa eventos hijos independientes de un
    mismo cliente. Solo agrupa: parámetros, registro y reportes de cada hijo siguen separados."""
    __tablename__ = 'super_events'
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, ForeignKey('tenants.id'), nullable=False)
    name = Column(String, nullable=False)
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    archived_at = Column(DateTime, nullable=True)  # 0095 (Fase 3): NULL = activo; con fecha = archivado (fuera de listas y selectores, se restaura; sus eventos no se tocan)
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)

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
    archived_at = Column(DateTime, nullable=True)  # 0092 (Fase 3): NULL = activo; con fecha = archivado (oculto, se restaura, conserva historial)
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    parent_id = Column(Integer, ForeignKey('event_areas.id'), nullable=True)  # 0140: subcategoría (p. ej. «Entrada A» dentro de «Salón A»); NULL = zona principal
    stats_enabled = Column(Boolean, default=True, server_default='true', nullable=False)  # 0140: genera estadísticas en la sección de Estadísticas
    max_per_person = Column(Integer, nullable=True)  # 0140: entradas permitidas por persona (en un grupo cuentan todas sus subcategorías y manda sobre ellas); NULL = sin límite


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
    from_peer = Column(Boolean, nullable=True)          # 0160: llegó de otro servidor local (evento compartido); no se vuelve a subir
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
    allow_repeat_delivery = Column(Boolean, default=True, server_default='true', nullable=False)  # 0096 (D7): ¿se puede entregar de nuevo a la MISMA persona? Los existentes sí; el alta por la API nace en false
    requires_dwell = Column(Boolean, default=False, server_default='false', nullable=False)  # 0123 (Fase 10): solo se entrega a quien llegó al porcentaje de estadía del evento
    created_at = Column(DateTime, default=utcnow)
    archived_at = Column(DateTime, nullable=True)  # 0092 (Fase 3): NULL = activo; con fecha = archivado (oculto, se restaura, conserva historial)
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    parent_id = Column(Integer, ForeignKey('inventory_items.id'), nullable=True)  # 0140: subcategoría (p. ej. «Perro» dentro de «Comida»); NULL = ítem o categoría principal
    stats_enabled = Column(Boolean, default=True, server_default='true', nullable=False)  # 0140: genera estadísticas en la sección de Estadísticas
    max_per_person = Column(Integer, nullable=True)  # 0140: unidades por persona (en un grupo cuentan todas sus subcategorías y manda sobre ellas); NULL = sin límite
    source_value = Column(String, nullable=True)  # 0161: valor de la base (normalizado, app/inv_assign_core.norm) que creó este producto en el modo «la base lo define»; el nombre visible se puede cambiar


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
    from_peer = Column(Boolean, nullable=True)          # 0160: llegó de otro servidor local (evento compartido); no se vuelve a subir
    delivered_at = Column(DateTime, default=utcnow)
    delivered_by_staff_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    assignment_key = Column(String(40), nullable=True)  # 0161: qué asignación se entregó en el modo «la base lo define»: 'h' (la del titular) o 'd<uid>' (fila de event_dependents); NULL = entrega elegida

    __table_args__ = (ForeignKeyConstraint(['user_id', 'tenant_id'], ['users.id', 'users.tenant_id']),)


class EventDependent(Base):
    """0161: una fila del archivo de DEPENDIENTES de un evento (hijos, acompañantes…): la persona asociada a un titular (`holder_id` = cédula del titular en la base del evento),
    con sus columnas tal cual (`data_json` {título: valor}). Varias filas del mismo dependiente (mismo `person_key`) son varios productos. No es una persona del evento:
    no tiene rostro, no cuenta como registrada y no entra a la ruleta (app/dependents.py)."""
    __tablename__ = 'event_dependents'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    tenant_id = Column(String, nullable=False)
    uid = Column(String(32), nullable=False)  # identificador ESTABLE de la fila (no cambia al copiar el evento a un servidor local): la entrega guarda 'd<uid>'
    holder_id = Column(String, nullable=False)
    person_key = Column(String, nullable=False)  # quién es el dependiente dentro del titular: su documento, su nombre o, si no trae ninguno, la fila (app/inv_assign_core.person_key)
    name = Column(String, nullable=True)
    doc_id = Column(String, nullable=True)
    data_json = Column(Text, nullable=True)
    row_num = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def get_data(self) -> dict:
        try:
            return json.loads(self.data_json) if self.data_json else {}
        except ValueError:
            return {}


class InventoryCategory(Base):
    """Categoría del CATÁLOGO de inventario (Fase 5, 0107): la define el Super Admin en Configuración. Archivable (conserva historial); no se repite el nombre (sin distinguir mayúsculas, lo valida app/inventory.py)."""
    __tablename__ = 'inventory_categories'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    position = Column(Integer, nullable=False, default=0, server_default='0')
    created_at = Column(DateTime, default=utcnow)
    archived_at = Column(DateTime, nullable=True)
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)


class InventoryProduct(Base):
    """Producto del catálogo de inventario (Fase 5, 0107): unidad de medida, SKU opcional y `fields_json` = campos propios que pide ese producto en cada evento ([{key,label,kind:'text'|'number'}]).
    `category_id` puede ser NULL (sin categorizar): se permite con el evento en «creado» y NO para pasarlo a «en proceso» (app/inventory.py, regla de cuadre). Archivado = fuera del catálogo nuevo, las líneas viejas se conservan."""
    __tablename__ = 'inventory_products'
    id = Column(Integer, primary_key=True, autoincrement=True)
    category_id = Column(Integer, ForeignKey('inventory_categories.id'), nullable=True)
    name = Column(String, nullable=False)
    unit = Column(String, nullable=False, default='unidad', server_default='unidad')
    sku = Column(String, nullable=True)
    fields_json = Column(Text, nullable=True)
    qty_total = Column(Integer, nullable=True)      # 0110: existencias de Golden (NULL = no se controla); con ellas se avisa cuando lo asignado a eventos que se cruzan en fechas las supera (app/inventory_alerts.py)
    tracking = Column(String(10), nullable=False, default='cantidad', server_default='cantidad')          # 0148 (almacén): 'serial' (QR por equipo) | 'modelo' (QR por modelo) | 'cantidad' (QR por tipo); app/almacen.py
    checklist_row = Column(String(40), nullable=True)          # 0148: clave de la fila del checklist GEYL a la que suma (app/almacen.py CHECKLIST_ROWS); NULL = no sale en el checklist
    is_consumable = Column(Boolean, nullable=False, default=False, server_default='false')          # 0148: se gasta y no vuelve (almacén lo repone y lo cuenta a mano)
    qr_code = Column(String(12), nullable=True, unique=True)          # 0148: código del QR del producto (solo 'modelo' y 'cantidad'; los 'serial' llevan el QR en cada unidad)
    photo_key = Column(String(200), nullable=True)          # 0149: foto del elemento (almacenamiento: app/storage.py, clave almacen/elementos/…)
    position = Column(Integer, nullable=False, default=0, server_default='0')
    created_at = Column(DateTime, default=utcnow)
    archived_at = Column(DateTime, nullable=True)
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)

    category = relationship('InventoryCategory')


class InventoryUnit(Base):
    """Un equipo con serial del almacén (0148, Pieza 1): su propio número visible (`number`, único por producto, nunca se reutiliza) y su propio QR (`code`: «GW» + 6 caracteres, solo mayúsculas y números).
    `status`: disponible | en_evento | novedad (la novedad y el bloqueo: tabla `inventory_novelties`, Pieza 3). Archivar no borra: la unidad deja de ofrecerse y conserva su número."""
    __tablename__ = 'inventory_units'
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey('inventory_products.id'), nullable=False)
    number = Column(Integer, nullable=False)
    code = Column(String(32), nullable=False, unique=True)          # = el serial (0153: un solo dato; antes «GW»+6 y un serial aparte)
    serial = Column(String(80), nullable=True)          # copia de `code` (se conserva por compatibilidad)
    status = Column(String(20), nullable=False, default='disponible', server_default='disponible')
    created_at = Column(DateTime, default=utcnow)
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    archived_at = Column(DateTime, nullable=True)
    archived_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=True)          # 0149: en qué evento está hoy (vacío = en bodega)

    product = relationship('InventoryProduct')
    event = relationship('Event')
    __table_args__ = (UniqueConstraint('product_id', 'number', name='uq_inventory_unit_number'), Index('ix_inventory_units_product', 'product_id'))


class InventoryMovement(Base):
    """Salida o entrada de almacén por lectura de QR (0149, Pieza 2). Solo se agrega: anular marca `voided_*`, nunca se borra. `unit_id` = equipo con serial (null en los controlados por modelo o cantidad).
    `extra` = cuánto de la salida excede lo asignado al evento (se justifica con `reason` o `is_plan_b`; sube `qty_assigned` pero no cuenta como NECESARIO)."""
    __tablename__ = 'inventory_movements'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    product_id = Column(Integer, ForeignKey('inventory_products.id'), nullable=False)
    unit_id = Column(Integer, ForeignKey('inventory_units.id'), nullable=True)
    kind = Column(String(10), nullable=False)          # salida | entrada
    qty = Column(Integer, nullable=False, default=1, server_default='1')
    extra = Column(Integer, nullable=False, default=0, server_default='0')
    reason = Column(String(300), nullable=True)
    is_plan_b = Column(Boolean, nullable=False, default=False, server_default=text('false'))
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    voided_at = Column(DateTime, nullable=True)
    voided_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)

    product = relationship('InventoryProduct')
    unit = relationship('InventoryUnit')
    __table_args__ = (Index('ix_inventory_movements_event', 'event_id', 'product_id'), Index('ix_inventory_movements_unit', 'unit_id'))


class InventoryNovelty(Base):
    """Novedad de almacén (0152, Pieza 3): un daño o problema de un elemento. `unit_id` = el equipo con serial (null en los controlados por modelo o cantidad, que llevan `qty` piezas).
    Abierta mientras `resolved_at` sea nulo: el equipo queda «En novedad» y no se puede sacar a un evento hasta que almacén la resuelve (`resolution` = qué se hizo). Nada se borra.
    `event_id` = el evento donde se detectó (si fue al devolver), `movement_id` = la entrada con la que se reportó, `photo_key` = foto del daño (almacén/novedades/<uuid>.jpg)."""
    __tablename__ = 'inventory_novelties'
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey('inventory_products.id'), nullable=False)
    unit_id = Column(Integer, ForeignKey('inventory_units.id'), nullable=True)
    qty = Column(Integer, nullable=False, default=1, server_default='1')
    description = Column(Text, nullable=False)
    photo_key = Column(String(200), nullable=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=True)
    movement_id = Column(Integer, ForeignKey('inventory_movements.id'), nullable=True)
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    resolution = Column(Text, nullable=True)

    product = relationship('InventoryProduct')
    unit = relationship('InventoryUnit')
    event = relationship('Event')
    __table_args__ = (Index('ix_inventory_novelties_product', 'product_id', 'resolved_at'), Index('ix_inventory_novelties_unit', 'unit_id'))


class InventoryNoveltyFile(Base):
    """Archivo adjunto de una novedad (0153): evidencia al reportarla (`kind='reporte'`) o al resolverla (`'resolucion'`). Foto (JPEG re-codificado), PDF o video corto. Nada se borra."""
    __tablename__ = 'inventory_novelty_files'
    id = Column(Integer, primary_key=True, autoincrement=True)
    novelty_id = Column(Integer, ForeignKey('inventory_novelties.id'), nullable=False)
    kind = Column(String(12), nullable=False)
    file_key = Column(String(200), nullable=False)
    filename = Column(String(120), nullable=False)
    content_type = Column(String(60), nullable=False)
    size = Column(Integer, nullable=False, default=0, server_default='0')
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    novelty = relationship('InventoryNovelty', backref='files')
    __table_args__ = (Index('ix_inventory_novelty_files_novelty', 'novelty_id'),)


class EventChecklistRow(Base):
    """Casilla «OK S/N» (alistado) y observación de UNA fila del checklist GEYL en un evento (0149, Pieza 2). `row_key` = clave de app/almacen.py CHECKLIST_ROWS (incluye las 5 de verificación manual)."""
    __tablename__ = 'event_checklist_rows'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    row_key = Column(String(40), nullable=False)
    done = Column(Boolean, nullable=False, default=False, server_default=text('false'))
    notes = Column(String(300), nullable=True)
    updated_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint('event_id', 'row_key', name='uq_event_checklist_row'),)


class EventLocalNode(Base):
    """0160: servidores locales que tienen un evento COMPARTIDO (docs/23_EVENTO_COMPARTIDO_NUBE.md). El primero también queda en `events.local_node_name` (principal) para todo lo que ya lo lee."""
    __tablename__ = 'event_local_nodes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    node_name = Column(String(60), nullable=False)
    joined_at = Column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (UniqueConstraint('event_id', 'node_name', name='uq_event_local_node'),)


class LocalNode(Base):
    """Servidor local autorizado a subir datos a la nube (0112, Fase 6). El token (`gwn_…`) se muestra UNA sola vez al crearlo y aquí solo queda su hash SHA-256; revocar = poner `revoked_at`.
    `created_by_id` es la cuenta de admin/super_admin que lo creó: con su alcance (cliente/empresa) se aplican los lotes que sube el nodo. Sin datos personales."""
    __tablename__ = 'local_nodes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(60), nullable=False, unique=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    created_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    last_version = Column(String(80), nullable=True)      # commit/esquema que reportó la última vez
    disabled_at = Column(DateTime, nullable=True)          # 0159: su llave fue DESHABILITADA (queda aquí aunque la llave se elimine de la lista: el servidor sigue recibiendo «deshabilitado»)
    tenant_id = Column(String, nullable=True)              # 0163: «solo eventos de este cliente». NULL = sin restricción (todo lo instalado antes de 0163). Lo hereda de su llave al vincularse

    created_by = relationship("StaffUser", foreign_keys=[created_by_id])


class LocalServerKey(Base):
    """Llave de producto de un servidor local (0158, 20-nov-2026; lógica en app/server_keys.py). La crea un administrador; es de UN solo uso: la reclama el instalador (queda atada a esa instalación,
    `installation_id`), se activa al vincular el servidor (`node_id`) y desde entonces es su identificador (serial). Una sin usar vence a los 7 días (`expires_at`). Deshabilitarla (`disabled_at`) revoca
    el nodo asociado. El código se guarda tal cual (el administrador necesita verlo en la lista; una vez usada deja de ser un secreto). Sin datos personales."""
    __tablename__ = 'local_server_keys'
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False, unique=True)
    label = Column(String(60), nullable=True)                       # para quién o para qué equipo es (opcional)
    created_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    claimed_at = Column(DateTime, nullable=True)
    installation_id = Column(String(64), nullable=True)
    activated_at = Column(DateTime, nullable=True)
    node_id = Column(Integer, ForeignKey('local_nodes.id', ondelete='SET NULL'), nullable=True)
    disabled_at = Column(DateTime, nullable=True)
    disabled_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    tenant_id = Column(String, nullable=True)                       # 0163: cliente elegido al crear la llave (opcional); pasa al servidor (`local_nodes.tenant_id`) al vincularse

    created_by = relationship("StaffUser", foreign_keys=[created_by_id])
    node = relationship("LocalNode", foreign_keys=[node_id])


class Notification(Base):
    """Notificación dentro de la aplicación para UNA cuenta del personal (Fase 5, 0110): se ve en la campana y, además, sale por correo (app/notifications.py). `dedupe_key` evita repetir el mismo aviso a la
    misma cuenta. No lleva datos personales de asistentes: solo texto del aviso, el evento y un enlace."""
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True, autoincrement=True)
    staff_user_id = Column(Integer, ForeignKey('staff_users.id', ondelete='CASCADE'), nullable=False)
    kind = Column(String, nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    url = Column(String, nullable=True)
    event_id = Column(Integer, nullable=True)
    dedupe_key = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    read_at = Column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint('staff_user_id', 'dedupe_key', name='uq_notification_dedupe'), Index('ix_notifications_user_unread', 'staff_user_id', 'read_at'))


class EventInventoryItem(Base):
    """Un producto del catálogo en un evento (Fase 5, 0107): cantidad asignada (lo que pide el evento) y lo que mueve el almacén: salió, volvió, se consumió. Regla de cuadre: app/inventory.py.
    Distinta de `InventoryItem` (insumos que el quiosco reparte a las personas del evento). `attrs_json` = valores de los campos propios del producto."""
    __tablename__ = 'event_inventory_items'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    product_id = Column(Integer, ForeignKey('inventory_products.id'), nullable=False)
    qty_assigned = Column(Integer, nullable=False, default=0, server_default='0')
    qty_out = Column(Integer, nullable=False, default=0, server_default='0')
    qty_returned = Column(Integer, nullable=False, default=0, server_default='0')
    qty_consumed = Column(Integer, nullable=False, default=0, server_default='0')
    notes = Column(String, nullable=True)
    attrs_json = Column(Text, nullable=True)
    updated_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    product = relationship('InventoryProduct')
    __table_args__ = (UniqueConstraint('event_id', 'product_id', name='uq_event_inventory_product'),)


class CrmProductCategory(Base):
    """Lo que IMPLICA un producto del CRM en CATEGORÍAS de Almacén (0154; antes, 0153, eran elementos sueltos): «Registro bidimensional» = 1 Portátiles + 1 Lectores. `checklist_key` es la fila del checklist GEYL (app/almacen.py); no descuenta existencias: Almacén elige después los equipos concretos de cada categoría."""
    __tablename__ = 'crm_product_categories'
    id = Column(Integer, primary_key=True, autoincrement=True)
    crm_product_id = Column(Integer, ForeignKey('crm_products.id', ondelete='CASCADE'), nullable=False)
    checklist_key = Column(String(40), nullable=False)
    qty_per_unit = Column(Integer, nullable=False, default=1, server_default='1')
    __table_args__ = (UniqueConstraint('crm_product_id', 'checklist_key', name='uq_crm_product_category'),)


class EventCrmProduct(Base):
    """Productos del CRM que lleva un evento (0153). `origin` 'crm' = vienen de la última cotización al ganar la oportunidad (o de aplicar una alerta); 'manual' = los agregó una persona en el inventario del evento. `name` es copia del nombre al guardar."""
    __tablename__ = 'event_crm_products'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    crm_product_id = Column(Integer, ForeignKey('crm_products.id', ondelete='SET NULL'), nullable=True)
    name = Column(String(200), nullable=False)
    qty = Column(Integer, nullable=False, default=1, server_default='1')
    origin = Column(String(10), nullable=False, default='crm', server_default='crm')
    quote_id = Column(Integer, ForeignKey('crm_quotes.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    __table_args__ = (Index('ix_event_crm_products_event', 'event_id'),)


class EventCrmSync(Base):
    """Estado de la sincronización CRM → inventario de un evento (0153): cotización de origen y lo que se sumó al «asignado» la última vez (`implied_json` {id de elemento: cantidad}), para poder restar lo anterior y sumar lo nuevo sin pisar lo manual antiguo."""
    __tablename__ = 'event_crm_sync'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False, unique=True)
    source_quote_id = Column(Integer, ForeignKey('crm_quotes.id', ondelete='SET NULL'), nullable=True)
    implied_json = Column(Text, nullable=True)
    synced_at = Column(DateTime, default=utcnow)


class EventInventoryAlert(Base):
    """Alerta en el inventario de un evento cuando el CRM ya no coincide con lo que el evento tiene (0153). `status`: open | applied | dismissed | obsolete. `snapshot_json` = lista [{crm_product_id, name, qty}] propuesta; `diff_json` = lo que difiere; `snap_hash` evita repetir una alerta descartada."""
    __tablename__ = 'event_inventory_alerts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    quote_id = Column(Integer, ForeignKey('crm_quotes.id', ondelete='SET NULL'), nullable=True)
    status = Column(String(10), nullable=False, default='open', server_default='open')
    snapshot_json = Column(Text, nullable=False)
    diff_json = Column(Text, nullable=False)
    snap_hash = Column(String(40), nullable=False)
    created_at = Column(DateTime, default=utcnow)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    __table_args__ = (Index('ix_event_inventory_alerts_event', 'event_id', 'status'),)


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
    from_peer = Column(Boolean, nullable=True)          # 0160: llegó de otro servidor local (evento compartido); no se vuelve a subir
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
    from_peer = Column(Boolean, nullable=True)          # 0160: llegó de otro servidor local (evento compartido); no se vuelve a subir
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
    from_peer = Column(Boolean, nullable=True)          # 0160: llegó de otro servidor local (evento compartido); no se vuelve a subir


class PersonChangeLog(Base):
    """Historial de datos modificados por persona (migración 0127, app/person_history.py): una fila por campo cambiado (campo, valor anterior, valor nuevo, quién y cuándo). Solo datos de texto de la
    persona (nunca rostro, foto ni vector). Sin llaves foráneas, como `person_changes`: se borra con la persona (supresión, eliminarla del evento) y con el evento. `changed_by_id` NULL = lo hizo
    la propia persona o un proceso (formulario público, autorregistro). `source`: edit | outbox | bulk | form | register | autoregistro."""
    __tablename__ = 'person_change_log'
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, nullable=False)
    event_id = Column(Integer, nullable=True)
    user_id = Column(String, nullable=False)
    field_key = Column(String(64), nullable=False)
    old_value = Column(String(500), nullable=True)
    new_value = Column(String(500), nullable=True)
    changed_by_id = Column(Integer, nullable=True)
    source = Column(String(16), nullable=False, default='edit')
    from_peer = Column(Boolean, nullable=True)          # 0160: llegó de otro servidor local (evento compartido); no se vuelve a subir
    changed_at = Column(DateTime, nullable=False, default=utcnow)
    __table_args__ = (Index('ix_person_change_log_person', 'tenant_id', 'user_id'), Index('ix_person_change_log_event', 'event_id'))


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


class InfraCost(Base):
    """0121 (Fase 9C): gasto de infraestructura de un mes (Google, Neon, Microsoft, Cloudflare, dominio…). Solo admin/super_admin (app/infra_costs.py). `amount_cop` ya viene en pesos con la TRM del
    día guardada en `trm`, así el histórico no cambia si el dólar se mueve. `source_key` único = importación automática de Google idempotente."""
    __tablename__ = 'infra_costs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    month = Column(String(7), nullable=False, index=True)             # AAAA-MM
    provider = Column(String(20), nullable=False)
    concept = Column(String(160), nullable=False)
    kind = Column(String(10), nullable=False, default='variable')      # fixed | variable
    currency = Column(String(3), nullable=False, default='COP')
    amount = Column(Numeric(14, 2), nullable=False)
    trm = Column(Numeric(12, 2), nullable=True)
    amount_cop = Column(Numeric(14, 2), nullable=False)
    source = Column(String(12), nullable=False, default='manual')      # manual | gcp_export
    source_key = Column(String(160), nullable=True, unique=True)
    note = Column(String(300), nullable=True)
    attachment_key = Column(String(300), nullable=True)
    attachment_name = Column(String(160), nullable=True)
    created_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
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


class EventChangeLog(Base):
    """Fase 5 (0108): historial de cambios del EVENTO por campo (quién, cuándo, valor anterior y nuevo). Solo campos del evento: nunca datos de asistentes. Los valores sensibles
    (p. ej. el contacto del evento) se guardan ocultos y los textos se recortan (`app/event_history.py`). `source`: edit | state | switch | import."""
    __tablename__ = 'event_change_log'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False, index=True)
    field_key = Column(String(64), nullable=False)
    field_label = Column(String(120), nullable=False)
    old_value = Column(String(500), nullable=True)
    new_value = Column(String(500), nullable=True)
    changed_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    changed_at = Column(DateTime, nullable=False, default=utcnow)
    source = Column(String(16), nullable=False, default='edit', server_default='edit')


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


class EventStaffPledge(Base):
    """Evidencia del compromiso digital del digitador POR EVENTO (0100, app/pledge.py). La escribe el motor de formularios al recibir el envío del formulario `kind='pledge'`; las respuestas viven en
    `form_submissions` (lo sensible, cifrado en `sensitive_json`) y aquí queda la prueba: huella SHA-256 del texto aceptado + respuestas, versión del texto, firma y documento en el almacenamiento.
    Solo se INSERTA; las únicas marcas que cambian después son `resign_allowed_at` (el coordinador permite firmar de nuevo), `superseded_at` (una firma nueva la reemplazó; queda como historial) y
    `health_purged_at` (se borró lo sensible por retención). Las columnas booleanas son avisos sin detalle."""
    __tablename__ = 'event_staff_pledges'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    staff_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)      # 0102: NULL cuando la cuenta se elimina (la evidencia queda en el evento)
    submission_id = Column(Integer, ForeignKey('form_submissions.id'), nullable=False)
    signed_at = Column(DateTime, nullable=False, default=utcnow)
    source = Column(String(10), nullable=False, default='link')      # link (enlace público) | session (al ingresar con la cédula)
    text_version = Column(String(40), nullable=False)
    sensitive_auth_version = Column(String(60), nullable=True)      # versión del texto de datos sensibles aceptado (NULL = no se pidieron datos sensibles)
    content_hash = Column(String(64), nullable=False)      # SHA-256 del texto aceptado + las respuestas
    signature_key = Column(String(300), nullable=False)
    doc_key = Column(String(300), nullable=True)      # documento firmado (HTML imprimible; no hay librería de PDF instalada)
    attendance_confirmed = Column(Boolean, nullable=False, default=False)
    understands_terms = Column(Boolean, nullable=False, default=False)
    has_health_info = Column(Boolean, nullable=False, default=False)
    health_flags = Column(String(30), nullable=True)      # 0104: cuáles de med,drug,support respondió «Sí» (solo para la alerta del coordinador; se borra con la purga de lo sensible)
    ip_masked = Column(String(64), nullable=True)
    resign_allowed_at = Column(DateTime, nullable=True)
    superseded_at = Column(DateTime, nullable=True)
    health_purged_at = Column(DateTime, nullable=True)

    __table_args__ = (Index('uq_pledge_active', 'event_id', 'staff_id', unique=True, postgresql_where=text("superseded_at IS NULL")),)


class EventDeliveryLink(Base):
    """Enlace de ENTREGA al cliente de un evento Facturado (Fase 5, 0106; app/delivery.py): /entrega/<token>. El token se DERIVA (HMAC con SECRET_KEY) de `nonce`, así el personal puede volver a ver el
    enlace sin guardar el token; en la base solo queda su SHA-256 (`token_hash`) para buscarlo. Sin vencimiento corto: vale hasta que se revoque o se regenere (regenerar revoca el anterior)."""
    __tablename__ = 'event_delivery_links'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    nonce = Column(String(32), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    created_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    last_opened_at = Column(DateTime, nullable=True)


class SurveyResponse(Base):
    """Una encuesta de satisfacción contestada (Fase 5, 0106), guardada APARTE de los formularios (`form_submissions`) y SIN purga biométrica: es la base de la analítica de gerencia (promedios por
    mes, evento, cliente y pregunta). Sin datos personales de quien responde. Una por evento (índice único). El detalle por pregunta está en `survey_answers`. Ver docs/FASE_5_ENTREGA_ENCUESTA.md."""
    __tablename__ = 'survey_responses'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    tenant_id = Column(String, nullable=False)
    survey_version = Column(Integer, nullable=False)
    submitted_at = Column(DateTime, nullable=False, default=utcnow)
    nps_score = Column(Integer, nullable=True)            # 0-10
    avg_score = Column(Float, nullable=True)              # promedio 1-3 de las preguntas de calidad contestadas
    delivery_link_id = Column(Integer, ForeignKey('event_delivery_links.id', ondelete='SET NULL'), nullable=True)
    comment_count = Column(Integer, nullable=False, default=0, server_default='0')
    ip_hash = Column(String(16), nullable=True)           # solo antiabuso: SHA-256 TRUNCADO de la IP con SECRET_KEY (no es la IP)

    answers = relationship("SurveyAnswer", cascade="all, delete-orphan", passive_deletes=True)
    __table_args__ = (Index('uq_survey_responses_event', 'event_id', unique=True), Index('ix_survey_responses_tenant_at', 'tenant_id', 'submitted_at'))


class SurveyAnswer(Base):
    """Una fila por pregunta contestada (normalizado para analítica). `score` numérico (calidad 1-3, recomendación 0-10) o NULL (sin puntaje / «No aplica»). event_id, tenant_id y submitted_at se
    repiten de la respuesta a propósito: así promediar por mes/evento/cliente/pregunta no necesita unir tablas."""
    __tablename__ = 'survey_answers'
    id = Column(Integer, primary_key=True, autoincrement=True)
    response_id = Column(Integer, ForeignKey('survey_responses.id', ondelete='CASCADE'), nullable=False, index=True)
    event_id = Column(Integer, nullable=False)
    tenant_id = Column(String, nullable=False)
    submitted_at = Column(DateTime, nullable=False)
    survey_version = Column(Integer, nullable=False)
    question_id = Column(String(40), nullable=False)
    score = Column(Integer, nullable=True)
    choice_text = Column(String(60), nullable=True)
    comment = Column(Text, nullable=True)

    __table_args__ = (Index('ix_survey_answers_question', 'question_id', 'submitted_at'), Index('ix_survey_answers_event', 'event_id'), Index('ix_survey_answers_tenant_at', 'tenant_id', 'submitted_at'))


class SlugHistory(Base):
    """Nombres de enlace viejos de un evento (0113): responden 301 al nuevo y no se reasignan a otro evento hasta `hold_until` (12 meses). Ver app/public_slug.py."""
    __tablename__ = 'slug_history'
    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String, nullable=False, index=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    hold_until = Column(DateTime, nullable=False)


class QueueTurn(Base):
    """Un turno de «Turnos y filas» (Fase 8, 0116): una persona, una fila (letra) y un número. `rank` ordena la fila (menor se llama primero; «saltar»/«volver a la fila» solo lo cambian).
    `token` es el enlace secreto de la persona (/turno/<evento>/<token>): solo muestra SU turno. Sin cédulas en lo que se muestra a otros."""
    __tablename__ = 'queue_turns'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    user_id = Column(String, nullable=False)
    lane = Column(String(1), nullable=False)
    number = Column(Integer, nullable=False)
    rank = Column(Integer, nullable=False)
    token = Column(String, nullable=False, unique=True)
    status = Column(String(10), nullable=False, default='waiting', server_default='waiting')      # waiting | called | done | skipped
    desk = Column(String(40), nullable=True)        # puesto que lo llamó («Caja 2»)
    called_seq = Column(Integer, nullable=True)     # orden global del último llamado (para saber cuál es «el que están llamando»)
    called_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    called_at = Column(DateTime, nullable=True)
    done_at = Column(DateTime, nullable=True)
    source = Column(String(10), nullable=False, default='arrival', server_default='arrival')      # arrival | form | alpha | manual
    from_peer = Column(Boolean, nullable=True)          # 0160: llegó de otro servidor local (evento compartido); no se vuelve a subir
    created_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint('event_id', 'lane', 'number', name='uq_queue_turn_number'), UniqueConstraint('event_id', 'user_id', name='uq_queue_turn_user'),
                      Index('ix_queue_turn_event_status', 'event_id', 'status'))


class QueueCall(Base):
    """Cada vez que se llama un turno (solo se INSERTA): la pantalla de TV muestra los últimos."""
    __tablename__ = 'queue_calls'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    turn_id = Column(Integer, ForeignKey('queue_turns.id', ondelete='CASCADE'), nullable=False)
    lane = Column(String(1), nullable=False)
    number = Column(Integer, nullable=False)
    desk = Column(String(40), nullable=True)
    called_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    from_peer = Column(Boolean, nullable=True)          # 0160: llegó de otro servidor local (evento compartido); no se vuelve a subir
    called_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (Index('ix_queue_call_event', 'event_id', 'id'),)


class ContactCard(Base):
    """Tarjeta de contacto de UNA persona en UN evento (Fase 8, 0114): `token` = enlace PRIVADO donde la persona decide si comparte sus datos con expositores; `share_token` = lo que lleva el QR/NFC que ve el expositor.
    Los dos son aleatorios (nada de cédulas en la URL: las direcciones quedan en los registros del proveedor). Sin datos personales aquí: solo quién (llave de la persona) y los tokens."""
    __tablename__ = 'contact_cards'
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, nullable=False)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(String, nullable=False)
    token = Column(String, nullable=False, unique=True)
    share_token = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint('event_id', 'tenant_id', 'user_id', name='uq_contact_card_person'),)


class AuditContactShare(Base):
    """Constancia INMUTABLE (solo INSERT) de que una persona aceptó o retiró compartir sus datos de contacto con los expositores (Ley 1581: autorización previa, expresa e informada). Vigente = el ÚLTIMO registro
    de la persona en el evento. Guarda la versión y la huella del texto exacto que vio; la cédula solo como huella (HMAC)."""
    __tablename__ = 'audit_contact_shares'
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(String, nullable=False)
    cedula_hash = Column(String, nullable=False)
    at = Column(DateTime, default=utcnow, nullable=False)
    version = Column(String, nullable=False)
    text_hash = Column(String, nullable=False)
    shared = Column(Boolean, nullable=False)
    adult_confirmed = Column(Boolean, nullable=False, default=False)
    reason = Column(String, nullable=False)          # consent | revocation
    __table_args__ = (Index('ix_contact_share_person', 'event_id', 'tenant_id', 'user_id', 'at'),)


class EventExhibitor(Base):
    """Un expositor del evento (Fase 8, 0114). `token` = su enlace PRIVADO (escanear asistentes y ver su lista); `card_token` = su tarjeta pública (QR/NFC que escanean los asistentes para guardarlo). Los datos de la tarjeta
    los pone el organizador con el expositor (son datos del expositor, publicados por él)."""
    __tablename__ = 'event_exhibitors'
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, nullable=False)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    name = Column(String, nullable=False)          # empresa / stand
    contact_name = Column(String, nullable=True)
    title = Column(String, nullable=True)          # cargo
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    token = Column(String, nullable=False, unique=True)
    card_token = Column(String, nullable=False, unique=True)
    active = Column(Boolean, nullable=False, default=True)
    created_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (Index('ix_exhibitor_event', 'event_id'),)


class ExhibitorLead(Base):
    """Persona escaneada por un expositor (Fase 8, 0114). Solo la llave de la persona: lo que se muestra se lee en el momento y SOLO si la persona sigue compartiendo (retirar la autorización oculta el contacto)."""
    __tablename__ = 'exhibitor_leads'
    id = Column(Integer, primary_key=True, autoincrement=True)
    exhibitor_id = Column(Integer, ForeignKey('event_exhibitors.id', ondelete='CASCADE'), nullable=False)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    tenant_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    from_peer = Column(Boolean, nullable=True)          # 0160: llegó de otro servidor local (evento compartido); no se vuelve a subir
    scanned_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint('exhibitor_id', 'tenant_id', 'user_id', name='uq_exhibitor_lead'),)


class AlertRecipient(Base):
    """0119 (Fase 9-A): quién recibe las alertas del sistema (borrado masivo). `kind='email'` = correo externo; `kind='staff'` = cuenta de la plataforma (campana + su correo registrado)."""
    __tablename__ = 'alert_recipients'
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(10), nullable=False)
    email = Column(String(200), nullable=True)
    staff_user_id = Column(Integer, ForeignKey('staff_users.id', ondelete='CASCADE'), nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class SystemAlert(Base):
    """0119: historial de alertas del sistema ya disparadas (sin datos personales de asistentes)."""
    __tablename__ = 'system_alerts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(40), nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    event_id = Column(Integer, nullable=True)
    actor_id = Column(Integer, nullable=True)
    actor_label = Column(String(120), nullable=True)
    dedupe_key = Column(String(160), nullable=True, unique=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class MassDeleteLog(Base):
    """0119: cuántas filas borró cada acción grande (≥10) y quién; sirve para la regla «≥N en M minutos». Se limpia sola (solo se consulta la última hora)."""
    __tablename__ = 'mass_delete_log'
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)
    actor_id = Column(Integer, nullable=True)
    label = Column(String(40), nullable=False)
    rows = Column(Integer, nullable=False)
    event_id = Column(Integer, nullable=True)


# ------------------------------------------------------------------------------------------------ CRM (módulo de Orum; docs/crm/, migración 0130)
class CrmCounter(Base):
    """Contadores de los códigos consecutivos del CRM (`name`: account | event). `value` es el último número entregado; `ready` es falso hasta que alguien fije el número inicial
    (scripts/crm_set_counter.py) y mientras tanto app/crm/codes.next_code se niega a entregar números."""
    __tablename__ = 'crm_counters'
    name = Column(String(32), primary_key=True)
    value = Column(BigInteger, nullable=False, default=0, server_default='0')
    ready = Column(Boolean, nullable=False, default=False, server_default=text('false'))
    updated_at = Column(DateTime, nullable=False, default=utcnow)


class CrmAccount(Base):
    """Cuenta del CRM (la empresa cliente o prospecto). `code` es el número consecutivo (el mismo que `tenants.client_code` cuando la cuenta ya es cliente de la plataforma). El estado
    (`status`) se valida en el código (app/crm/__init__.py: ACCOUNT_STATUSES), no con CHECK: la lista se ajusta cuando se vea la exportación de SuiteCRM."""
    __tablename__ = 'crm_accounts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(BigInteger, nullable=False)
    tenant_id = Column(String, ForeignKey('tenants.id', ondelete='SET NULL'), nullable=True)
    name = Column(String(200), nullable=False)
    name_norm = Column(String(200), nullable=False)
    status = Column(String(12), nullable=False, default='activo', server_default='activo')
    nit = Column(String(40))
    email = Column(String(200))
    phone = Column(String(60))
    billing_address = Column(String(300))
    billing_city = Column(String(120))
    billing_state = Column(String(120))
    billing_country = Column(String(120))
    shipping_address = Column(String(300))
    shipping_city = Column(String(120))
    shipping_country = Column(String(120))
    billing_contact_name = Column(String(200))
    billing_contact_phone = Column(String(60))
    payment_term = Column(String(60))
    payment_days = Column(Integer)
    billing_close = Column(String(60))
    agency_percent = Column(Numeric(5, 2))
    owner_staff_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    description = Column(Text)
    category = Column(String(40))          # 0142: categoría de cliente de SuiteCRM (ClienteVIP, ClienteA…)
    account_type = Column(String(40))          # 0142: tipo de cuenta (Agencias, BTL, OPC, Asociaciones…)
    industry = Column(String(60))
    website = Column(String(300))
    legacy_json = Column(Text)          # 0142: lo de SuiteCRM que no tiene columna, con su nombre original (solo lectura)
    legacy_sugar_id = Column(String(40))
    source_created_at = Column(DateTime)
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    created_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    contacts = relationship("CrmContact", back_populates="account", cascade="all, delete-orphan", passive_deletes=True)
    __table_args__ = (
        UniqueConstraint('code', name='uq_crm_accounts_code'),
        Index('uq_crm_accounts_tenant', 'tenant_id', unique=True, postgresql_where=text('tenant_id IS NOT NULL')),
        Index('uq_crm_accounts_legacy', 'legacy_sugar_id', unique=True, postgresql_where=text('legacy_sugar_id IS NOT NULL')),
        Index('ix_crm_accounts_status', 'status'),
        Index('ix_crm_accounts_owner', 'owner_staff_id'),
        Index('ix_crm_accounts_city', 'billing_city'),
        Index('ix_crm_accounts_name_norm', 'name_norm', postgresql_ops={'name_norm': 'text_pattern_ops'}),
    )


class CrmContact(Base):
    """Contacto de una cuenta del CRM (datos personales: Ley 1581; ver docs/crm/README.md, supresión). Un solo contacto principal por cuenta."""
    __tablename__ = 'crm_contacts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('crm_accounts.id', ondelete='CASCADE'), nullable=False)
    first_name = Column(String(120))
    last_name = Column(String(120))
    full_name_norm = Column(String(240), nullable=False, default='')
    job_title = Column(String(120))
    email = Column(String(200))
    email_norm = Column(String(200))
    phone = Column(String(60))
    mobile = Column(String(60))
    is_primary = Column(Boolean, nullable=False, default=False, server_default=text('false'))
    notes = Column(Text)
    legacy_json = Column(Text)          # 0142: datos originales de SuiteCRM sin columna propia (solo lectura)
    legacy_sugar_id = Column(String(40))
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    created_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    account = relationship("CrmAccount", back_populates="contacts")
    __table_args__ = (
        Index('uq_crm_contacts_primary', 'account_id', unique=True, postgresql_where=text('is_primary')),
        Index('uq_crm_contacts_legacy', 'legacy_sugar_id', unique=True, postgresql_where=text('legacy_sugar_id IS NOT NULL')),
        Index('ix_crm_contacts_account', 'account_id'),
        Index('ix_crm_contacts_email_norm', 'email_norm'),
        Index('ix_crm_contacts_name_norm', 'full_name_norm', postgresql_ops={'full_name_norm': 'text_pattern_ops'}),
    )


class CrmNote(Base):
    """Línea de tiempo de una cuenta: notas escritas por el personal (`kind` note) o del sistema (`system`). Si habla de un contacto, `contact_id` lo señala y se borra con él."""
    __tablename__ = 'crm_notes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('crm_accounts.id', ondelete='CASCADE'), nullable=False)
    contact_id = Column(Integer, ForeignKey('crm_contacts.id', ondelete='CASCADE'), nullable=True)
    kind = Column(String(16), nullable=False, default='note', server_default='note')
    body = Column(Text, nullable=False)
    created_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    legacy_sugar_id = Column(String(40))
    __table_args__ = (Index('ix_crm_notes_account_created', 'account_id', 'created_at'), Index('ix_crm_notes_contact', 'contact_id'))


class CrmChangeLog(Base):
    """Registro de cambios del CRM, con la forma de `person_change_log` (app/person_history.py): una fila por campo cambiado (campo, valor anterior, valor nuevo, quién y cuándo).
    `entity`: account | contact. Sin llaves foráneas (como el original): se borra desde el código junto con su cuenta/contacto (app/crm/erase.py). `source`: edit | import | system."""
    __tablename__ = 'crm_change_log'
    id = Column(Integer, primary_key=True, autoincrement=True)
    entity = Column(String(16), nullable=False)
    entity_id = Column(Integer, nullable=False)
    field_key = Column(String(64), nullable=False)
    old_value = Column(String(500), nullable=True)
    new_value = Column(String(500), nullable=True)
    changed_by_id = Column(Integer, nullable=True)
    source = Column(String(16), nullable=False, default='edit', server_default='edit')
    changed_at = Column(DateTime, nullable=False, default=utcnow)
    __table_args__ = (Index('ix_crm_change_log_entity', 'entity', 'entity_id', 'changed_at'),)


# ------------------------------------------------------------------ CRM etapa C1c–C4 (docs/crm/ETAPA_C1C_C4_DISENO.md). Migraciones 0131 (embudos, oportunidades, leads, actividades) y 0132 (importador).
class CrmPipeline(Base):
    """Embudo de ventas (p. ej. «Eventos»). Las etapas viven en `crm_stages`. Uno solo es el predeterminado."""
    __tablename__ = 'crm_pipelines'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    position = Column(Integer, nullable=False, default=0, server_default='0')
    is_default = Column(Boolean, nullable=False, default=False, server_default=text('false'))
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    __table_args__ = (UniqueConstraint('name', name='uq_crm_pipelines_name'),)


class CrmStage(Base):
    """Etapa de un embudo. `kind`: open | won | lost (la ganada y la perdida cierran la oportunidad). `probability` 0–100 (la oportunidad puede traer la suya)."""
    __tablename__ = 'crm_stages'
    id = Column(Integer, primary_key=True, autoincrement=True)
    pipeline_id = Column(Integer, ForeignKey('crm_pipelines.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(80), nullable=False)
    position = Column(Integer, nullable=False, default=0, server_default='0')
    probability = Column(Integer, nullable=False, default=0, server_default='0')
    kind = Column(String(8), nullable=False, default='open', server_default='open')
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    __table_args__ = (UniqueConstraint('pipeline_id', 'name', name='uq_crm_stages_pipeline_name'), Index('ix_crm_stages_pipeline_pos', 'pipeline_id', 'position'))


class CrmLead(Base):
    """Cliente potencial. DATOS PERSONALES (Ley 1581): nombre, correo y teléfono; se suprimen con el mismo criterio que un contacto (app/crm/erase.py). `description` es texto libre:
    el historial no guarda su contenido (history.FREE_TEXT). `status`: nuevo | contactado | calificado | convertido | descartado."""
    __tablename__ = 'crm_leads'
    id = Column(Integer, primary_key=True, autoincrement=True)
    first_name = Column(String(120))
    last_name = Column(String(120))
    full_name_norm = Column(String(240), nullable=False, default='', server_default='')
    company_name = Column(String(200))
    job_title = Column(String(120))
    email = Column(String(200))
    email_norm = Column(String(200))
    phone = Column(String(60))
    source = Column(String(60))
    status = Column(String(16), nullable=False, default='nuevo', server_default='nuevo')
    owner_staff_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    description = Column(Text)
    converted_at = Column(DateTime, nullable=True)
    converted_account_id = Column(Integer, ForeignKey('crm_accounts.id', ondelete='SET NULL'), nullable=True)
    converted_contact_id = Column(Integer, ForeignKey('crm_contacts.id', ondelete='SET NULL'), nullable=True)
    converted_opportunity_id = Column(Integer, nullable=True)          # sin llave foránea: la oportunidad se crea después que la tabla y se puede borrar sin tocar al lead
    legacy_json = Column(Text)          # 0142: datos originales de SuiteCRM sin columna propia (solo lectura)
    legacy_sugar_id = Column(String(40))
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    created_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    __table_args__ = (
        Index('uq_crm_leads_legacy', 'legacy_sugar_id', unique=True, postgresql_where=text('legacy_sugar_id IS NOT NULL')),
        Index('ix_crm_leads_status', 'status'),
        Index('ix_crm_leads_owner', 'owner_staff_id'),
        Index('ix_crm_leads_email_norm', 'email_norm'),
        Index('ix_crm_leads_name_norm', 'full_name_norm', postgresql_ops={'full_name_norm': 'text_pattern_ops'}),
    )


class CrmOpportunity(Base):
    """Oportunidad = un posible evento. `code` sale del contador `event` al CREARLA y es el mismo número que tendrá el evento si se gana (regla de códigos, docs/crm/ETAPA_C1C_C4_DISENO.md §4).
    `outcome`: open | won | lost (lo fija la etapa). `next_activity_at` es una copia (la mantiene app/crm/activities.py) para marcar las que no tienen próxima actividad sin consultar otra tabla."""
    __tablename__ = 'crm_opportunities'
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(BigInteger, nullable=False)
    account_id = Column(Integer, ForeignKey('crm_accounts.id', ondelete='CASCADE'), nullable=False)
    pipeline_id = Column(Integer, ForeignKey('crm_pipelines.id', ondelete='RESTRICT'), nullable=False)
    stage_id = Column(Integer, ForeignKey('crm_stages.id', ondelete='RESTRICT'), nullable=False)
    name = Column(String(200), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False, default=0, server_default='0')
    currency = Column(String(3), nullable=False, default='COP', server_default='COP')
    probability = Column(Integer, nullable=True)
    expected_close = Column(Date, nullable=True)
    opp_type = Column(String(60))
    source = Column(String(60))
    next_step = Column(String(200))
    description = Column(Text)
    owner_staff_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    primary_contact_id = Column(Integer, ForeignKey('crm_contacts.id', ondelete='SET NULL'), nullable=True)
    event_start = Column(Date, nullable=True)
    city = Column(String(120))
    outcome = Column(String(8), nullable=False, default='open', server_default='open')
    closed_at = Column(DateTime, nullable=True)
    lost_reason = Column(String(200))
    event_id = Column(Integer, ForeignKey('events.id', ondelete='SET NULL'), nullable=True)
    next_activity_at = Column(DateTime, nullable=True)
    stage_entered_at = Column(DateTime, nullable=False, default=utcnow)
    legacy_json = Column(Text)          # 0142: datos originales de SuiteCRM sin columna propia (solo lectura)
    legacy_sugar_id = Column(String(40))
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    created_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    __table_args__ = (
        UniqueConstraint('code', name='uq_crm_opportunities_code'),
        Index('uq_crm_opportunities_event', 'event_id', unique=True, postgresql_where=text('event_id IS NOT NULL')),
        Index('uq_crm_opportunities_legacy', 'legacy_sugar_id', unique=True, postgresql_where=text('legacy_sugar_id IS NOT NULL')),
        Index('ix_crm_opps_board', 'pipeline_id', 'stage_id', 'stage_entered_at'),
        Index('ix_crm_opps_account', 'account_id'),
        Index('ix_crm_opps_owner', 'owner_staff_id'),
        Index('ix_crm_opps_close', 'expected_close'),
        Index('ix_crm_opps_outcome', 'outcome'),
    )


class CrmActivity(Base):
    """Llamada, tarea, reunión o nota con fecha. Cuelga de una cuenta, un contacto, un lead o una oportunidad (al menos uno; lo exige el código). Si habla de un contacto o un lead, se borra con él.
    `result` es una lista cerrada corta (portafolio enviado, cotización enviada, orden de compra pendiente, sin respuesta…) para el seguimiento por contacto. `subject` y `description` son texto libre."""
    __tablename__ = 'crm_activities'
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(8), nullable=False)
    status = Column(String(10), nullable=False, default='planned', server_default='planned')
    subject = Column(String(200), nullable=False)
    description = Column(Text)
    due_at = Column(DateTime, nullable=True)
    remind_at = Column(DateTime, nullable=True)
    done_at = Column(DateTime, nullable=True)
    result = Column(String(24))
    account_id = Column(Integer, ForeignKey('crm_accounts.id', ondelete='CASCADE'), nullable=True)
    contact_id = Column(Integer, ForeignKey('crm_contacts.id', ondelete='CASCADE'), nullable=True)
    lead_id = Column(Integer, ForeignKey('crm_leads.id', ondelete='CASCADE'), nullable=True)
    opportunity_id = Column(Integer, ForeignKey('crm_opportunities.id', ondelete='CASCADE'), nullable=True)
    owner_staff_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    created_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    legacy_json = Column(Text)          # 0142: datos originales de SuiteCRM sin columna propia (solo lectura)
    legacy_sugar_id = Column(String(40))
    __table_args__ = (
        Index('uq_crm_activities_legacy', 'legacy_sugar_id', unique=True, postgresql_where=text('legacy_sugar_id IS NOT NULL')),
        Index('ix_crm_act_owner_due', 'owner_staff_id', 'status', 'due_at'),
        Index('ix_crm_act_account', 'account_id', 'created_at'),
        Index('ix_crm_act_contact', 'contact_id'),
        Index('ix_crm_act_lead', 'lead_id'),
        Index('ix_crm_act_opp', 'opportunity_id', 'created_at'),
    )


class CrmImportRun(Base):
    """Una corrida del importador (C1c). `mode`: sample (20 filas por archivo, nada se guarda) | dry_run (todo el archivo, nada se guarda) | apply (guarda). `status`: queued | running | done | failed | cancelled.
    Los archivos subidos viven en el almacenamiento con prefijo `crm/imports/<id>/` y se borran al terminar. `counts_json`, `cursor_json` y el informe NO llevan datos personales: solo conteos, números de fila y motivos."""
    __tablename__ = 'crm_import_runs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(16), nullable=False, default='suitecrm', server_default='suitecrm')
    mode = Column(String(8), nullable=False, default='sample', server_default='sample')
    status = Column(String(10), nullable=False, default='queued', server_default='queued')
    files_json = Column(Text)
    options_json = Column(Text)
    counts_json = Column(Text)
    cursor_json = Column(Text)
    report_key = Column(String(300))
    error = Column(String(500))
    started_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    __table_args__ = (Index('ix_crm_import_runs_created', 'created_at'),)


class CrmImportPair(Base):
    """Informe de emparejamiento: un cliente de la plataforma (hexadecimal) frente a una cuenta de SuiteCRM. `bucket`: seguro | dudoso | sin_pareja. `decision`: pending | approved | rejected | applied.
    Solo nombres de EMPRESAS (no de personas). Aplicar una pareja aprobada pasa el `client_code` del cliente al número de SuiteCRM y guarda el hexadecimal en `legacy_client_code`."""
    __tablename__ = 'crm_import_pairs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey('crm_import_runs.id', ondelete='CASCADE'), nullable=False)
    tenant_id = Column(String, ForeignKey('tenants.id', ondelete='CASCADE'), nullable=True)
    tenant_name = Column(String(200))
    suitecrm_legacy_id = Column(String(40))
    suitecrm_code = Column(BigInteger, nullable=True)
    suitecrm_name = Column(String(200))
    score = Column(Integer, nullable=False, default=0, server_default='0')
    bucket = Column(String(12), nullable=False)
    decision = Column(String(10), nullable=False, default='pending', server_default='pending')
    decided_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    __table_args__ = (Index('ix_crm_import_pairs_run', 'run_id', 'bucket'),)



class CrmProduct(Base):
    """Producto o servicio del catálogo del CRM (C3). Sin datos personales."""
    __tablename__ = 'crm_products'
    id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String(60))
    name = Column(String(200), nullable=False)
    name_norm = Column(String(200), nullable=False)
    description = Column(Text)
    category = Column(String(80))
    cost = Column(Numeric(16, 2), nullable=False, default=0, server_default='0')
    price = Column(Numeric(16, 2), nullable=False, default=0, server_default='0')
    currency = Column(String(3), nullable=False, default='COP', server_default='COP')
    tax_percent = Column(Numeric(5, 2), nullable=False, default=19, server_default='19')
    active = Column(Boolean, nullable=False, default=True, server_default=text('true'))
    image_key = Column(String(300))          # 0144: foto del producto; sale en la cotización si el diseño del PDF tiene la columna «Foto»
    legacy_json = Column(Text)          # 0142: datos originales de SuiteCRM sin columna propia (solo lectura)
    legacy_sugar_id = Column(String(40))
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow)
    __table_args__ = (Index('ix_crm_products_name', 'name_norm'),
                      Index('uq_crm_products_sku', 'sku', unique=True, postgresql_where=text('sku IS NOT NULL')),
                      Index('uq_crm_products_legacy', 'legacy_sugar_id', unique=True, postgresql_where=text('legacy_sugar_id IS NOT NULL')))


class CrmTerm(Base):
    """Condición comercial elegible en una cotización (contado, 50-50, 30 días…)."""
    __tablename__ = 'crm_terms'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False)
    body = Column(Text, nullable=False)
    position = Column(Integer, nullable=False, default=0, server_default='0')
    archived_at = Column(DateTime, nullable=True)


class CrmDocTemplate(Base):
    """Plantilla de texto del PDF de cotización o proforma (`kind` quote | proforma)."""
    __tablename__ = 'crm_doc_templates'
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(10), nullable=False)
    name = Column(String(80), nullable=False)
    header_text = Column(Text)
    greeting_text = Column(Text)
    footer_text = Column(Text)
    logo_key = Column(String(300))
    layout_json = Column(Text)          # 0144: diseño por bloques (app/crm/quote_layout.py); NULL = la plantilla sencilla de siempre (encabezado, saludo y pie)
    is_default = Column(Boolean, nullable=False, default=False, server_default=text('false'))
    archived_at = Column(DateTime, nullable=True)
    __table_args__ = (Index('uq_crm_doc_templates_default', 'kind', unique=True, postgresql_where=text('is_default AND archived_at IS NULL')),)


class CrmQuote(Base):
    """Cotización (C3). `number` es el consecutivo (contador `quote`); cada versión nueva repite el número con `version` + 1. `contact_id` pasa a NULL si se suprime al contacto (Ley 1581)."""
    __tablename__ = 'crm_quotes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    number = Column(BigInteger, nullable=False)
    version = Column(Integer, nullable=False, default=1, server_default='1')
    parent_quote_id = Column(Integer, ForeignKey('crm_quotes.id', ondelete='SET NULL'), nullable=True)
    account_id = Column(Integer, ForeignKey('crm_accounts.id', ondelete='CASCADE'), nullable=False)
    contact_id = Column(Integer, ForeignKey('crm_contacts.id', ondelete='SET NULL'), nullable=True)
    opportunity_id = Column(Integer, ForeignKey('crm_opportunities.id', ondelete='SET NULL'), nullable=True)
    title = Column(String(200), nullable=False)
    stage = Column(String(12), nullable=False, default='borrador', server_default='borrador')
    approval_status = Column(String(12), nullable=False, default='pendiente', server_default='pendiente')
    invoice_status = Column(String(12), nullable=False, default='no_facturada', server_default='no_facturada')
    currency = Column(String(3), nullable=False, default='COP', server_default='COP')
    valid_until = Column(Date, nullable=True)
    event_start = Column(Date, nullable=True)
    terms_id = Column(Integer, ForeignKey('crm_terms.id', ondelete='SET NULL'), nullable=True)
    terms_text = Column(Text)
    meeting_notes = Column(Text)
    template_id = Column(Integer, ForeignKey('crm_doc_templates.id', ondelete='SET NULL'), nullable=True)
    subtotal = Column(Numeric(16, 2), nullable=False, default=0, server_default='0')
    discount_total = Column(Numeric(16, 2), nullable=False, default=0, server_default='0')
    tax_total = Column(Numeric(16, 2), nullable=False, default=0, server_default='0')
    total = Column(Numeric(16, 2), nullable=False, default=0, server_default='0')
    pdf_key = Column(String(300))
    pdf_generated_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    owner_staff_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    created_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    legacy_json = Column(Text)          # 0142: datos originales de SuiteCRM sin columna propia (solo lectura)
    legacy_sugar_id = Column(String(40))
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow)
    archived_at = Column(DateTime, nullable=True)
    __table_args__ = (Index('uq_crm_quotes_number_version', 'number', 'version', unique=True), Index('ix_crm_quotes_account', 'account_id'), Index('ix_crm_quotes_opportunity', 'opportunity_id'),
                      Index('ix_crm_quotes_stage', 'stage', 'updated_at'),
                      Index('uq_crm_quotes_legacy', 'legacy_sugar_id', unique=True, postgresql_where=text('legacy_sugar_id IS NOT NULL')))


class CrmQuoteLine(Base):
    __tablename__ = 'crm_quote_lines'
    id = Column(Integer, primary_key=True, autoincrement=True)
    quote_id = Column(Integer, ForeignKey('crm_quotes.id', ondelete='CASCADE'), nullable=False)
    position = Column(Integer, nullable=False, default=0, server_default='0')
    product_id = Column(Integer, ForeignKey('crm_products.id', ondelete='SET NULL'), nullable=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    qty = Column(Numeric(12, 2), nullable=False, default=1, server_default='1')
    unit_price = Column(Numeric(16, 2), nullable=False, default=0, server_default='0')
    discount_percent = Column(Numeric(5, 2), nullable=False, default=0, server_default='0')
    tax_percent = Column(Numeric(5, 2), nullable=False, default=19, server_default='19')
    line_total = Column(Numeric(16, 2), nullable=False, default=0, server_default='0')
    __table_args__ = (Index('ix_crm_quote_lines_quote', 'quote_id', 'position'),)


class CrmProforma(Base):
    """Proforma (C3): documento de cobro anticipado, con su propio consecutivo (contador `proforma`)."""
    __tablename__ = 'crm_proformas'
    id = Column(Integer, primary_key=True, autoincrement=True)
    number = Column(BigInteger, nullable=False)
    quote_id = Column(Integer, ForeignKey('crm_quotes.id', ondelete='SET NULL'), nullable=True)
    account_id = Column(Integer, ForeignKey('crm_accounts.id', ondelete='CASCADE'), nullable=False)
    issued_at = Column(Date, nullable=False)
    due_at = Column(Date, nullable=True)
    status = Column(String(10), nullable=False, default='no_pagado', server_default='no_pagado')
    event_name = Column(String(200))
    city = Column(String(120))
    currency = Column(String(3), nullable=False, default='COP', server_default='COP')
    total = Column(Numeric(16, 2), nullable=False, default=0, server_default='0')
    pdf_key = Column(String(300))
    created_by_id = Column(Integer, ForeignKey('staff_users.id', ondelete='SET NULL'), nullable=True)
    legacy_json = Column(Text)          # 0142: datos originales de SuiteCRM sin columna propia (solo lectura)
    legacy_sugar_id = Column(String(40))
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow)
    __table_args__ = (Index('uq_crm_proformas_number', 'number', unique=True), Index('ix_crm_proformas_account', 'account_id'),
                      Index('uq_crm_proformas_legacy', 'legacy_sugar_id', unique=True, postgresql_where=text('legacy_sugar_id IS NOT NULL')))


class CrmSavedFilter(Base):
    """Filtro guardado de una lista del CRM. `filters_json` guarda SOLO filtros estructurados: el texto de búsqueda libre no se guarda (podría ser el nombre de una persona)."""
    __tablename__ = 'crm_saved_filters'
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_staff_id = Column(Integer, ForeignKey('staff_users.id', ondelete='CASCADE'), nullable=False)
    scope = Column(String(14), nullable=False)
    name = Column(String(80), nullable=False)
    filters_json = Column(Text, nullable=False)
    shared = Column(Boolean, nullable=False, default=False, server_default=text('false'))
    created_at = Column(DateTime, nullable=False, default=utcnow)
    __table_args__ = (Index('ix_crm_saved_filters_owner', 'owner_staff_id', 'scope'),)
