import json
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

# Roles de staff, de menor a mayor privilegio. Ver app/auth.py (ROLE_HIERARCHY).
STAFF_ROLES = ("digitador", "coordinador", "admin", "super_admin")

class Tenant(Base):
    """Un cliente de Golden (la empresa para la que se hacen los eventos), no un usuario de staff."""
    __tablename__ = 'tenants'
    id = Column(String, primary_key=True)
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
    opt_1 = Column(String)
    opt_2 = Column(String)
    face_encoding = Column(Text)
    
    tenant = relationship("Tenant", back_populates="users", overlaps="tenant,users,logs")
    logs = relationship("AccessLog", back_populates="user", cascade="all, delete", overlaps="tenant,users,logs")
    
    def get_encoding(self):
        return json.loads(self.face_encoding) if self.face_encoding else None

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
    event_code = Column(String)  # código interno, libre (no es la PK)
    name = Column(String, nullable=False)
    location = Column(String)  # nombre del lugar/venue
    address = Column(String)
    country = Column(String)
    city = Column(String)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    setup_date = Column(DateTime)  # fecha de montaje
    event_schedule = Column(String)  # horario del evento, texto libre (ej. "8:00am - 6:00pm")
    setup_schedule = Column(String)  # horario de montaje
    notes = Column(Text)
    status = Column(String, default='activo', nullable=False)  # activo | cerrado
    created_by_id = Column(Integer, ForeignKey('staff_users.id'))
    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant")
    created_by = relationship("StaffUser")


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