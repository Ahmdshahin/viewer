"""SQLAlchemy and GeoAlchemy2 ORM models for GeoPortal."""

from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Boolean, ForeignKey, func, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from geoalchemy2 import Geometry
from app.db.session import Base


class LandParcel(Base):
    """Cadastral land parcels layer."""
    __tablename__ = "lands"

    id = Column(Integer, primary_key=True, autoincrement=True)
    req_number = Column("Req_Number", String, nullable=True, index=True)
    owner_name = Column("Owner_Name", String, nullable=True, index=True)
    layer_type = Column("Layer_Type", String, nullable=True)
    area_sqm = Column("Area_SQM", Float, nullable=True)
    area_feddan = Column("Area_Feddan", Float, nullable=True)
    x = Column("X", Float, nullable=True)
    y = Column("Y", Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=True)
    created_by = Column(String(100), nullable=True, index=True)
    geom = Column("geometry", Geometry(geometry_type="MULTIPOLYGON", srid=32636, spatial_index=True))


class Eshghalat(Base):
    """Occupations and encroachments layer."""
    __tablename__ = "eshghalat"

    id = Column(Integer, primary_key=True, autoincrement=True)
    req_number = Column("Req_Number", String, nullable=True, index=True)
    owner_name = Column("Owner_Name", String, nullable=True, index=True)
    layer_type = Column("Layer_Type", String, nullable=True)
    area_sqm = Column("Area_SQM", Float, nullable=True)
    area_feddan = Column("Area_Feddan", Float, nullable=True)
    x = Column("X", Float, nullable=True)
    y = Column("Y", Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=True)
    created_by = Column(String(100), nullable=True, index=True)
    geom = Column("geometry", Geometry(geometry_type="MULTIPOLYGON", srid=32636, spatial_index=True))


class Point(Base):
    """Survey points layer."""
    __tablename__ = "points"

    id = Column(Integer, primary_key=True, autoincrement=True)
    req_number = Column("Req_Number", String, nullable=True, index=True)
    owner_name = Column("Owner_Name", String, nullable=True, index=True)
    layer_type = Column("Layer_Type", String, nullable=True)
    area_sqm = Column("Area_SQM", Float, nullable=True)
    area_feddan = Column("Area_Feddan", Float, nullable=True)
    x = Column("X", Float, nullable=True)
    y = Column("Y", Float, nullable=True)
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


class Governorate(Base):
    """Governorates lookup (admin managed, not tied to one region)."""
    __tablename__ = "governorates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=True, unique=True, index=True)
    name = Column(String(120), nullable=False, unique=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class LookupValue(Base):
    """Admin-managed value lists (request/survey/raw statuses).

    Unlike the FK lookups above, ledger rows store these as plain text, so
    renaming/merging here re-points matching row text in both ledgers.
    """
    __tablename__ = "lookup_values"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(40), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


Index("ux_lookup_value_kind_name", LookupValue.kind, LookupValue.name, unique=True)


class Center(Base):
    """Centers lookup, optionally carrying the numeric code embedded in Req_Number."""
    __tablename__ = "centers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    governorate_id = Column(Integer, ForeignKey("governorates.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(20), nullable=True, index=True)
    name = Column(String(120), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


# Unique center name per governorate
Index("ux_center_gov_name", Center.governorate_id, Center.name, unique=True)


class Village(Base):
    """Villages lookup, nested under a center."""
    __tablename__ = "villages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    center_id = Column(Integer, ForeignKey("centers.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


Index("ux_village_center_name", Village.center_id, Village.name, unique=True)


class AreaUnit(Base):
    """Area units lookup (متر مربع / قيراط / سهم / فدان)."""
    __tablename__ = "area_units"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False, unique=True)
    name = Column(String(60), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


# Stable statuses used across the workflow (kept in code for clarity).
#
# Each tuple is the set of values the app ACCEPTS, and it has to stay a superset
# of two things: the values docs/template.xlsx offers, and the values that
# already exist in the ledgers. Existing rows carry spellings like
# "تم الرفع ع المنظومة" and "تم الرفع وجارى المراجعه" that a five-value list
# would not contain, and a strict check would then make those rows impossible
# to transition. The template itself still offers only the user's own short
# list (see app.api.import_template); these tuples are the wider safety net.
REQUEST_STATUSES = (
    "جديد",
    "قيد المعاينة",
    "بالمراجعة الفنية",
    "تم الارسال",
    "لم يتم الارسال",
    "تم الرفع ع المنظومة",
    "لم يتم الرفع ع المنظومة",
    "جاري العمل عليه",
    # Legacy intake exports (docs/1.csv..3.csv) use these two spellings.
    "لم يتم العمل عليه",
    "مكتمل ولم يرسل",
    "مقبول",
    "مرفوض",
)
SURVEY_STATUSES = (
    "لم يتم المعاينه",
    "تم المعاينه",
    "تمت المعاينة",
    "لم تتم المعاينة",
    "تعذر الرفع",
    "اعاده معاينه",
    "إعادة المعاينة",
    "تم الرفع وجارى المراجعه",
    "مرفوض مكتب فني",
    "طلب متوقف",
    "ملف غير مكتمل",
    "غير موجود بالمنظومة",
    "غير موجود بالمنظومه",
)

# One spelling per meaning — the list the app writes and offers as a choice
# (imports snap onto it via _snap_status's loose fold, the edit form and the
# status filters show exactly these). The ledgers used to carry both
# "تم المعاينة" and "تم المعاينه" for the same state, which split every count
# and put both variants in one dropdown. SURVEY_STATUSES above stays the wider
# acceptance superset for values that still exist in old rows.
CANONICAL_SURVEY_STATUSES = (
    "لم يتم المعاينه",
    "تم المعاينه",
    "تعذر الرفع",
    "اعاده معاينه",
    "تم الرفع وجارى المراجعه",
    "مرفوض مكتب فني",
    "طلب متوقف",
    "ملف غير مكتمل",
    "غير موجود بالمنظومه",
)

# Phrasing variants of the same state that the loose fold cannot catch, because
# they differ by a whole word (the definite article "ال" or "تم" vs "تمت")
# rather than by letter shape. Checked before the fold on every status that
# enters the app.
SURVEY_STATUS_ALIASES = {
    "تمت المعاينة": "تم المعاينه",
    "لم تتم المعاينة": "لم يتم المعاينه",
    "إعادة المعاينة": "اعاده معاينه",
}

# Unit-type spellings the ledgers should hold; a legacy export wrote "ارض"
# without the hamza. Anything not listed here passes through untouched.
UNIT_TYPE_ALIASES = {"ارض": "أرض"}


class CadastralRequest(Base):
    """Requests ledger (طلبات التقنين) — Req_Number is the primary business key.

    رقم التقنين (reqra_number) is deliberately just an optional attribute of the
    request and is never used as the key.
    """
    __tablename__ = "requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    req_number = Column("Req_Number", String(64), nullable=False, unique=True, index=True)
    applicant = Column("Applicant", String(255), nullable=True, index=True)
    phone = Column("Phone", String(60), nullable=True)
    address = Column("Address", Text, nullable=True)
    area_value = Column("Area_Value", Float, nullable=True)
    area_unit_id = Column("Area_Unit_Id", Integer, ForeignKey("area_units.id", ondelete="SET NULL"), nullable=True)
    unit_type = Column("Unit_Type", String(40), nullable=True)
    company = Column("Company", String(120), nullable=True)
    governorate_id = Column("Governorate_Id", Integer, ForeignKey("governorates.id", ondelete="SET NULL"), nullable=True, index=True)
    center_id = Column("Center_Id", Integer, ForeignKey("centers.id", ondelete="SET NULL"), nullable=True, index=True)
    village_id = Column("Village_Id", Integer, ForeignKey("villages.id", ondelete="SET NULL"), nullable=True)

    surveyor_name = Column("Surveyor_Name", String(120), nullable=True)
    office_name = Column("Office_Name", String(120), nullable=True)
    assigned_surveyor_id = Column("Assigned_Surveyor_Id", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_office_id = Column("Assigned_Office_Id", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    survey_status = Column("Survey_Status", String(60), nullable=True)
    survey_comment = Column("Survey_Comment", Text, nullable=True)
    office_comment = Column("Office_Comment", Text, nullable=True)
    request_status = Column("Request_Status", String(60), nullable=True, default="جديد", index=True)
    reqra_number = Column("Reqra_Number", String(64), nullable=True)

    entry_date = Column("Entry_Date", Date, nullable=True, index=True)
    # Date the cadastral survey was carried out / uploaded. Added because the
    # mudryia intake sheet carries a survey date next to the entry date.
    survey_date = Column("Survey_Date", Date, nullable=True, index=True)
    # Columns carried only by the user's legacy intake exports (docs/1.csv etc.).
    # The shared template does not offer them, but an old sheet must import
    # without dropping its data, so both ledgers keep a place for them.
    landmarks = Column("Landmarks", Text, nullable=True)
    field_team = Column("Field_Team", String(120), nullable=True)
    distribution_date = Column("Distribution_Date", Date, nullable=True)
    geodesy_date = Column("Geodesy_Date", Date, nullable=True)
    directorate_date = Column("Directorate_Date", Date, nullable=True)
    raw_files = Column("Raw_Files", String(200), nullable=True)
    # Legacy company export (8888.csv): a second survey-upload date spelled one
    # letter differently from Survey_Date, carrying a *different* date in 96%
    # of rows, plus the source-system shapefile flag. Neither has any other home.
    alt_survey_date = Column("Alt_Survey_Date", Date, nullable=True)
    base_map = Column("Base_Map", String(50), nullable=True)
    status_updated_at = Column("Status_Updated_At", DateTime, nullable=True, index=True)
    imported_by_id = Column("Imported_By_Id", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by = Column("Created_By", String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    @property
    def status(self):
        return self.request_status


Index("idx_requests_status_updated", CadastralRequest.request_status, CadastralRequest.status_updated_at)


class MudryiaRequest(Base):
    """Mudryia request ledger (طلبات المديرية) — the point-processing counterpart
    of :class:`CadastralRequest`.

    Deliberately an exact column-for-column mirror of ``requests`` so the two
    ledgers stay comparable and the shared lookups (governorate / center /
    village / area unit) can be resolved by the same helpers. The ``mudryia``
    points table links to this ledger by ``Req_Number`` (many points to one
    request) instead of to ``requests``.
    """
    __tablename__ = "mudryia_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    req_number = Column("Req_Number", String(64), nullable=False, unique=True, index=True)
    applicant = Column("Applicant", String(255), nullable=True, index=True)
    phone = Column("Phone", String(60), nullable=True)
    address = Column("Address", Text, nullable=True)
    area_value = Column("Area_Value", Float, nullable=True)
    area_unit_id = Column("Area_Unit_Id", Integer, ForeignKey("area_units.id", ondelete="SET NULL"), nullable=True)
    unit_type = Column("Unit_Type", String(40), nullable=True)
    company = Column("Company", String(120), nullable=True)
    governorate_id = Column("Governorate_Id", Integer, ForeignKey("governorates.id", ondelete="SET NULL"), nullable=True, index=True)
    center_id = Column("Center_Id", Integer, ForeignKey("centers.id", ondelete="SET NULL"), nullable=True, index=True)
    village_id = Column("Village_Id", Integer, ForeignKey("villages.id", ondelete="SET NULL"), nullable=True)

    surveyor_name = Column("Surveyor_Name", String(120), nullable=True)
    office_name = Column("Office_Name", String(120), nullable=True)
    assigned_surveyor_id = Column("Assigned_Surveyor_Id", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_office_id = Column("Assigned_Office_Id", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    survey_status = Column("Survey_Status", String(60), nullable=True)
    survey_comment = Column("Survey_Comment", Text, nullable=True)
    office_comment = Column("Office_Comment", Text, nullable=True)
    request_status = Column("Request_Status", String(60), nullable=True, default="جديد", index=True)
    reqra_number = Column("Reqra_Number", String(64), nullable=True)

    entry_date = Column("Entry_Date", Date, nullable=True, index=True)
    # Date the cadastral survey was carried out / uploaded. Added because the
    # mudryia intake sheet carries a survey date next to the entry date.
    survey_date = Column("Survey_Date", Date, nullable=True, index=True)
    # Columns carried only by the user's legacy intake exports (docs/1.csv etc.).
    # The shared template does not offer them, but an old sheet must import
    # without dropping its data, so both ledgers keep a place for them.
    landmarks = Column("Landmarks", Text, nullable=True)
    field_team = Column("Field_Team", String(120), nullable=True)
    distribution_date = Column("Distribution_Date", Date, nullable=True)
    geodesy_date = Column("Geodesy_Date", Date, nullable=True)
    directorate_date = Column("Directorate_Date", Date, nullable=True)
    raw_files = Column("Raw_Files", String(200), nullable=True)
    # Mirror of the company ledger's legacy-export columns; the mudryia sheets
    # simply leave them NULL.
    alt_survey_date = Column("Alt_Survey_Date", Date, nullable=True)
    base_map = Column("Base_Map", String(50), nullable=True)
    status_updated_at = Column("Status_Updated_At", DateTime, nullable=True, index=True)
    imported_by_id = Column("Imported_By_Id", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by = Column("Created_By", String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    @property
    def status(self):
        return self.request_status


Index("idx_mudryia_requests_status_updated", MudryiaRequest.request_status, MudryiaRequest.status_updated_at)


class Notification(Base):
    """Per-user notifications (import events, acceptance/rejection results)."""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(30), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    link_req = Column(String(64), nullable=True)
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
