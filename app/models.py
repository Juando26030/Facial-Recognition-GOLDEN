import json
from sqlalchemy import Column, Integer, String, DateTime, Date, Boolean, ForeignKey, Text, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

# Roles de staff. "cliente" NO es parte de la jerarquía de permisos habitual (no puede
# registrar/reconocer aunque esté "debajo" de digitador aquí) — ver la nota en
# app/auth.get_event_for_staff y app/routers/staff.py sobre quién puede crear cada rol.
STAFF_ROLES = ("cliente", "digitador", "coordinador", "admin", "super_admin")

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


class StaffUser(Base):
    """Cuenta de staff interno (no la persona biométrica registrada, eso es `User`)."""
    __tablename__ = 'staff_users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False)  # para digitadores, la cédula
    password_hash = Column(String, nullable=False)
    full_name = Column(String)
    role = Column(String, nullable=False)  # uno de STAFF_ROLES
    tenant_id = Column(String, ForeignKey('tenants.id'), nullable=True)  # null = alcance global (super_admin)
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
    created_by_id = Column(Integer, ForeignKey('staff_users.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    optional_field_labels = Column(Text)  # JSON {"opcional_1": "Talla de camisa", ...} — nombres que el cliente le dio a las columnas "opcional_N" de SU roster (2026-09-20, ver bulk_register)
    facial_enabled = Column(Boolean, default=False, nullable=False)  # 2026-09-21: se enciende solo (nunca se apaga solo) la primera vez que se sube un roster con zip de fotos para este evento — ver bulk_register. Decide si /kiosk/{id}/registro muestra el escáner de cámara o se comporta como cédula tradicional.
    roster_uploaded = Column(Boolean, default=False, nullable=False)  # 2026-09-21: true desde la primera vez que bulk_register cargó al menos una fila para este evento. Sirve para bloquear un RE-upload accidental mientras el evento ya está en_proceso (ver bulk_register) — evita pisar registros que ya se hicieron en vivo.

    tenant = relationship("Tenant")
    created_by = relationship("StaffUser", foreign_keys=[created_by_id])
    coordinator = relationship("StaffUser", foreign_keys=[coordinator_staff_id])

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