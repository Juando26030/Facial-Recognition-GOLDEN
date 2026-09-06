import json
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, ForeignKeyConstraint
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class Tenant(Base):
    __tablename__ = 'tenants'
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    
    users = relationship("User", back_populates="tenant", cascade="all, delete", overlaps="tenant,users,logs")
    logs = relationship("AccessLog", back_populates="tenant", cascade="all, delete", overlaps="tenant,users,logs")

class User(Base):
    __tablename__ = 'users'
    id = Column(String, primary_key=True) 
    tenant_id = Column(String, ForeignKey('tenants.id'), primary_key=True)
    name = Column(String)
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
    
    __table_args__ = (
        ForeignKeyConstraint(
            ['user_id', 'tenant_id'],
            ['users.id', 'users.tenant_id']
        ),
    )
    
    tenant = relationship("Tenant", back_populates="logs", overlaps="tenant,users,logs")
    user = relationship("User", back_populates="logs", overlaps="tenant,users,logs")