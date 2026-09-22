"""SQLAlchemy and GeoAlchemy2 ORM models for GeoPortal."""

from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, func, Index
from sqlalchemy.dialects.postgresql import JSONB
from geoalchemy2 import Geometry
from app.db.session import Base


class LandParcel(Base):
    """Cadastral land parcels layer."""
    __tablename__ = "land"

    id = Column(Integer, primary_key=True, autoincrement=True)
    req_number = Column("Req_Number", String, nullable=True, index=True)
    owner_name = Column("Owner_Name", String, nullable=True, index=True)
    layer_type = Column("Layer_Type", String, nullable=True)
    area_sqm = Column("Area_SQM", String, nullable=True)
    area_feddan = Column("Area_Feddan", String, nullable=True)
    x = Column("X", String, nullable=True)
    y = Column("Y", String, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=True)
    created_by = Column(String(100), nullable=True, index=True)
    geom = Column("geometry", Geometry(geometry_type="POLYGON", srid=32636, spatial_index=True))


class Eshghalat(Base):
    """Occupations and encroachments layer."""
    __tablename__ = "eshghalat"

    id = Column(Integer, primary_key=True, autoincrement=True)
    req_number = Column("Req_Number", String, nullable=True, index=True)
    owner_name = Column("Owner_Name", String, nullable=True, index=True)
    layer_type = Column("Layer_Type", String, nullable=True)
    area_sqm = Column("Area_SQM", String, nullable=True)
    area_feddan = Column("Area_Feddan", String, nullable=True)
    x = Column("X", String, nullable=True)
    y = Column("Y", String, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=True)
    created_by = Column(String(100), nullable=True, index=True)
    geom = Column("geometry", Geometry(geometry_type="POLYGON", srid=32636, spatial_index=True))


class Point(Base):
    """Survey points layer."""
    __tablename__ = "point"

    id = Column(Integer, primary_key=True, autoincrement=True)
    req_number = Column("Req_Number", String, nullable=True, index=True)
    owner_name = Column("Owner_Name", String, nullable=True, index=True)
    layer_type = Column("Layer_Type", String, nullable=True)
    area_sqm = Column("Area_SQM", String, nullable=True)
    area_feddan = Column("Area_Feddan", String, nullable=True)
    x = Column("X", String, nullable=True)
    y = Column("Y", String, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=True)
    created_by = Column(String(100), nullable=True, index=True)
    geom = Column("geometry", Geometry(geometry_type="POINT", srid=32636, spatial_index=True))


class User(Base):
    """System user accounts and role-based permissions."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    full_name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="viewer")
    permissions = Column(JSONB, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class AuditTrail(Base):
    """Immutable audit trail recording every cadastral migration, insert, update, and delete."""
    __tablename__ = "audit_trail"

    id = Column(Integer, primary_key=True, autoincrement=True)
    table_name = Column(String(100), nullable=False, index=True)
    record_id = Column(Integer, nullable=True, index=True)
    action = Column(String(50), nullable=False, index=True)
    old_values = Column(JSONB, nullable=True)
    new_values = Column(JSONB, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    username = Column(String(100), nullable=False, default="system")
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    timestamp = Column(DateTime, server_default=func.now(), nullable=False, index=True)

    @property
    def old_data(self):
        """Compatibility alias for old_values."""
        return self.old_values

    @property
    def new_data(self):
        """Compatibility alias for new_values."""
        return self.new_values


# Composite index for querying audit records by table and record
Index("idx_audit_trail_table_record", AuditTrail.table_name, AuditTrail.record_id)
