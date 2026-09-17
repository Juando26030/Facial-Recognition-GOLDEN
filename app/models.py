import json
from sqlalchemy import Column, Integer, String, DateTime, Date, Boolean, Float, ForeignKey, Text, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

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

    users = relationship("User", back_populates="tenant", cascade="all, delete", overlaps="tenant,users,logs")
    logs = relationship("AccessLog", back_populates="tenant", cascade="all, delete", overlaps="tenant,users,logs")

class User(Base):
    __tablename__ = 'users'
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey('tenants.id'), primary_key=True)
    first_name = Column(String)
    last_name = Column(String)
    role = Column(String)
    company = Column(String)
    phone = Column(String)
    email = Column(String)
    opt_1 = Column(String)  # "Tipo de asistente" (2026-09-20; antes "tipo de empresa") — único campo opcional fijo, el resto son extra_fields
    opt_2 = Column(String)  # deprecado (2026-09-20, era "cantidad de empl") — ya no se escribe, reemplazado por extra_fields. Se deja la columna para no perder datos históricos.
    extra_fields = Column(Text)  # JSON {"opcional_1": "valor", ...} — hasta 30 campos dinámicos definidos por el cliente, ver bulk_register en routers/api.py y CLAUDE.md
    face_encoding = Column(Text)

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
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        ForeignKeyConstraint(['user_id', 'tenant_id'], ['users.id', 'users.tenant_id']),
        UniqueConstraint('event_id', 'user_id', name='uq_event_attendee'),
    )

    event = relationship("Event")


class AccessLog(Base):
    __tablename__ = 'access_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, ForeignKey('tenants.id'))
    user_id = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    record_type = Column(String)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=True)
    registered_by_staff_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    registration_method = Column(String, nullable=True)  # Sprint 2.4 Fase 16 (2026-09-17, pedido explícito): 'tradicional' | 'autoregistro' | 'biometrico' | 'qr' — para el reporte, que siempre debe decir CÓMO se registró cada persona (ver reports.py y routers/api.py)

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
    printed_at = Column(DateTime, default=datetime.utcnow)
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
    created_at = Column(DateTime, default=datetime.utcnow)

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
    phone = Column(String, nullable=True, unique=True)  # Sprint 2.4, 2026-09-16: WhatsApp; Fase 4: obligatorio+único salvo cliente/digitador (ver routers/staff.py, routers/events.py)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by_id = Column(Integer, ForeignKey('staff_users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)
    optional_field_labels = Column(Text)  # JSON {"opcional_1": "Talla de camisa", ...} — nombres que el cliente le dio a las columnas "opcional_N" de SU roster (2026-09-20, ver bulk_register)
    facial_enabled = Column(Boolean, default=False, nullable=False)  # 2026-09-21: se enciende solo (nunca se apaga solo) la primera vez que se sube un roster con zip de fotos para este evento — ver bulk_register. Decide si /kiosk/{id}/registro muestra el escáner de cámara o se comporta como cédula tradicional.
    roster_uploaded = Column(Boolean, default=False, nullable=False)  # 2026-09-21: true desde la primera vez que bulk_register cargó al menos una fila para este evento. Sirve para bloquear un RE-upload accidental mientras el evento ya está en_proceso (ver bulk_register) — evita pisar registros que ya se hicieron en vivo.
    auto_print_badge = Column(Boolean, default=False, nullable=False)  # 2026-09-15 (Sprint 2, Historia 2.2): si está prendido, guardar un registro exitoso (cualquier método) dispara la impresión de la escarapela sola, sin que el digitador toque el botón. Apagado por default a propósito — el brief es explícito en que la impresión NO es automática salvo que se active este switch.
    auto_register = Column(Boolean, default=False, nullable=False)  # 2026-09-16 (Sprint 2.2, Fase B): mismo criterio que auto_print_badge, pero para el registro en sí. Apagado por default: un match (facial o cédula, cualquier método) NO acredita solo — solo deja el match "pendiente" (result=MATCH_PENDING) hasta que el digitador confirme con "Guardar y autorizar acceso". Prendido, un match acredita de una, como se comportaba todo antes de este cambio.

    tenant = relationship("Tenant")
    created_by = relationship("StaffUser", foreign_keys=[created_by_id])
    coordinator = relationship("StaffUser", foreign_keys=[coordinator_staff_id])
    commercial = relationship("StaffUser", foreign_keys=[commercial_staff_id])

    def get_optional_labels(self) -> dict:
        return json.loads(self.optional_field_labels) if self.optional_field_labels else {}

    def set_optional_labels(self, data: dict) -> None:
        self.optional_field_labels = json.dumps(data) if data else None


class EventStaffAuthorization(Base):
    """Qué staff_user puede operar en qué evento. Obligatorio para digitadores (acceso temporal);
    para coordinador/admin/super_admin no se exige (tienen alcance de tenant/global)."""
    __tablename__ = 'event_staff_authorizations'
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False)
    staff_user_id = Column(Integer, ForeignKey('staff_users.id'), nullable=False)
    authorized_by_id = Column(Integer, ForeignKey('staff_users.id'))
    authorized_at = Column(DateTime, default=datetime.utcnow)

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
    event_id = Column(Integer, ForeignKey('events.id'), nullable=False, unique=True)
    name = Column(String, nullable=False, default='Escarapela')
    width_mm = Column(Float, nullable=False, default=62.0)
    height_mm = Column(Float, nullable=False, default=100.0)
    orientation = Column(String, nullable=False, default='vertical')  # 'vertical' (pensado para Brother QL-800) | 'horizontal'
    background_type = Column(String, nullable=False, default='color')  # 'color' | 'image'
    background_value = Column(String)  # color hex (#RRGGBB), o el path que devuelve /api/badge-assets al subir una imagen
    elements_json = Column(Text)  # JSON: lista ordenada (por z_index) de elementos — ver CLAUDE.md para el shape de cada tipo
    imported_from_saved_template_id = Column(Integer, ForeignKey('saved_badge_templates.id'), nullable=True)  # solo trazabilidad ("de dónde vino"), no un vínculo vivo
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant")
    event = relationship("Event")
    imported_from = relationship("SavedBadgeTemplate", foreign_keys=[imported_from_saved_template_id])

    def get_elements(self) -> list:
        return json.loads(self.elements_json) if self.elements_json else []

    def set_elements(self, data: list) -> None:
        self.elements_json = json.dumps(data) if data else None


FIELD_TYPES = ("text_short", "text_long", "select", "boolean")
CHART_TYPES = ("bar", "pie", "histogram", "line")


class EventFieldConfig(Base):
    """Parámetros del Evento (Sprint 2.2, 2026-09-16) — cómo debe comportarse UN campo del alta
    manual/edición para ESTE evento: si es obligatorio, qué tipo de control usar (texto
    corto/largo, lista desplegable con sus propias opciones, booleano), y si debe generar
    estadística sola al entrar a Estadísticas (y con qué tipo de gráfico). `field_key` es
    `role`/`company`/`phone`/`email`/`opt_1` o un `opcional_N` ya rotulado en
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant")

    def get_elements(self) -> list:
        return json.loads(self.elements_json) if self.elements_json else []

    def set_elements(self, data: list) -> None:
        self.elements_json = json.dumps(data) if data else None