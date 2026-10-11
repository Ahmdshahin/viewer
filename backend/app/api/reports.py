"""Admin-only reporting endpoints for the request ledgers and users.

Reports aggregate either the company ``requests`` ledger or the ``mudryia_requests``
ledger (they are full mirrors of the same record shape, sharing the
governorate/center lookups and the read-only geometry tables).  Endpoints are
exposed exclusively to administrators.  Reports share a common filter set
(ledger, entry date range, governorate, center, status, survey status, company,
surveyor, office) and can be exported as CSV or XLSX.
"""

import csv
import io
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import deps
from app.db.models import User

router = APIRouter()


# --- Ledger selection -------------------------------------------------------

# Which request ledger a report aggregates, and which read-only geometry tables
# count as "this request has geometry" for that ledger. mudryia requests are
# served by the `mudryia` point layer; cadastral requests by the parcel layers.
LEDGER_GEOM = {
    "company": ("requests", ("lands", "eshghalat", "points")),
    "mudryia": ("mudryia_requests", ("mudryia",)),
}
DEFAULT_LEDGER = "company"


def _ledger_name(ledger: Optional[str]) -> str:
    return ledger if ledger in LEDGER_GEOM else DEFAULT_LEDGER


def _TBL(f: dict) -> str:
    """Quoted ledger table name for the report SQL (alias stays `r`)."""
    return '"' + LEDGER_GEOM[_ledger_name(f.get("ledger"))][0] + '"'


def _geom_cte(f: dict) -> str:
    """CTE of request numbers that have geometry, scoped to the chosen ledger."""
    tables = LEDGER_GEOM[_ledger_name(f.get("ledger"))][1]
    parts = [
        'SELECT DISTINCT "Req_Number" AS rn FROM "%s" WHERE "Req_Number" IS NOT NULL' % t
        for t in tables
    ]
    return "WITH geom AS (" + " UNION ".join(parts) + ") "


# --- SQL fragments ---------------------------------------------------------

_AREA_SQM = (
    "(CASE au.code WHEN 'feddan' THEN 4200.83 WHEN 'kirat' THEN 175.035 "
    "WHEN 'share' THEN 7.2934 ELSE 1 END * COALESCE(r.\"Area_Value\", 0))"
)

# Request statuses that are considered "final".
_FINAL_STATUSES = ("مقبول", "مرفوض")


# --- Filter handling -------------------------------------------------------

def report_filters(
    ledger: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    governorate_id: Optional[int] = Query(None),
    center_id: Optional[int] = Query(None),
    request_status: Optional[str] = Query(None),
    survey_status: Optional[str] = Query(None),
    company: Optional[str] = Query(None),
    surveyor: Optional[str] = Query(None),
    office: Optional[str] = Query(None),
) -> dict:
    return {
        "ledger": _ledger_name(ledger),
        "date_from": date_from,
        "date_to": date_to,
        "governorate_id": governorate_id,
        "center_id": center_id,
        "request_status": request_status,
        "survey_status": survey_status,
        "company": company,
        "surveyor": surveyor,
        "office": office,
    }


def _where(f: dict):
    clauses = []
    params = {}
    if f.get("date_from"):
        clauses.append('r."Entry_Date" >= :date_from')
        params["date_from"] = f["date_from"]
    if f.get("date_to"):
        clauses.append('r."Entry_Date" <= :date_to')
        params["date_to"] = f["date_to"]
    if f.get("governorate_id"):
        clauses.append('r."Governorate_Id" = :gov')
        params["gov"] = f["governorate_id"]
    if f.get("center_id"):
        clauses.append('r."Center_Id" = :center')
        params["center"] = f["center_id"]
    if f.get("request_status"):
        clauses.append('r."Request_Status" = :rstatus')
        params["rstatus"] = f["request_status"]
    if f.get("survey_status"):
        clauses.append('r."Survey_Status" = :sstatus')
        params["sstatus"] = f["survey_status"]
    if f.get("company"):
        clauses.append('r."Company" = :company')
        params["company"] = f["company"]
    if f.get("surveyor"):
        clauses.append('r."Surveyor_Name" = :surveyor')
        params["surveyor"] = f["surveyor"]
    if f.get("office"):
        clauses.append('r."Office_Name" = :office')
        params["office"] = f["office"]
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _fmt(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if isinstance(d, date) else d


def _run(db: Session, sql: str, params: dict):
    return [dict(row._mapping) for row in db.execute(text(sql), params).fetchall()]


def _totals(columns: list, rows: list) -> dict:
    totals = {}
    for col in columns:
        if col["type"] in ("int", "float") and not col["key"].endswith("_pct"):
            s = 0
            for r in rows:
                v = r.get(col["key"])
                if v is not None:
                    s += float(v)
            totals[col["key"]] = round(s) if col["type"] == "int" else round(s, 2)
    return totals


# --- Report definitions ----------------------------------------------------

def _r_by_governorate(db, f):
    where, params = _where(f)
    sql = (
        _geom_cte(f) +
        'SELECT COALESCE(g.name, \'—\') AS name,'
        ' count(*) AS total,'
        ' count(*) FILTER (WHERE r."Request_Status" = \'مقبول\') AS accepted,'
        ' count(*) FILTER (WHERE r."Request_Status" = \'مرفوض\') AS rejected,'
        ' count(*) FILTER (WHERE r."Request_Status" NOT IN (\'مقبول\', \'مرفوض\')) AS in_progress,'
        ' count(geom.rn) AS with_geometry,'
        ' CAST(round(COALESCE(sum(' + _AREA_SQM + '), 0)) AS bigint) AS area_sqm'
        f' FROM {_TBL(f)} r'
        ' LEFT JOIN governorates g ON g.id = r."Governorate_Id"'
        ' LEFT JOIN area_units au ON au.id = r."Area_Unit_Id"'
        ' LEFT JOIN geom ON geom.rn = r."Req_Number"' +
        where +
        ' GROUP BY 1 ORDER BY total DESC'
    )
    columns = [
        {"key": "name", "label": "المحافظة", "type": "text"},
        {"key": "total", "label": "إجمالي", "type": "int"},
        {"key": "accepted", "label": "مقبول", "type": "int"},
        {"key": "rejected", "label": "مرفوض", "type": "int"},
        {"key": "in_progress", "label": "قيد الإجراء", "type": "int"},
        {"key": "with_geometry", "label": "له هندسة", "type": "int"},
        {"key": "area_sqm", "label": "المساحة (م²)", "type": "int"},
    ]
    rows = _run(db, sql, params)
    return {"key": "by_governorate", "title": "ملخص حسب المحافظة", "columns": columns, "rows": rows}


def _r_by_center(db, f):
    where, params = _where(f)
    sql = (
        'SELECT COALESCE(g.name, \'—\') AS governorate, COALESCE(c.name, \'—\') AS name,'
        ' count(*) AS total,'
        ' count(*) FILTER (WHERE r."Request_Status" = \'مقبول\') AS accepted,'
        ' count(*) FILTER (WHERE r."Request_Status" = \'مرفوض\') AS rejected,'
        ' count(*) FILTER (WHERE r."Request_Status" NOT IN (\'مقبول\', \'مرفوض\')) AS in_progress,'
        ' CAST(round(COALESCE(sum(' + _AREA_SQM + '), 0)) AS bigint) AS area_sqm'
        f' FROM {_TBL(f)} r'
        ' LEFT JOIN centers c ON c.id = r."Center_Id"'
        ' LEFT JOIN governorates g ON g.id = r."Governorate_Id"'
        ' LEFT JOIN area_units au ON au.id = r."Area_Unit_Id"' +
        where +
        ' GROUP BY 1, 2 ORDER BY total DESC'
    )
    columns = [
        {"key": "governorate", "label": "المحافظة", "type": "text"},
        {"key": "name", "label": "المركز", "type": "text"},
        {"key": "total", "label": "إجمالي", "type": "int"},
        {"key": "accepted", "label": "مقبول", "type": "int"},
        {"key": "rejected", "label": "مرفوض", "type": "int"},
        {"key": "in_progress", "label": "قيد الإجراء", "type": "int"},
        {"key": "area_sqm", "label": "المساحة (م²)", "type": "int"},
    ]
    rows = _run(db, sql, params)
    return {"key": "by_center", "title": "ملخص حسب المركز", "columns": columns, "rows": rows}


def _r_by_status(db, f):
    where, params = _where(f)
    sql = (
        'SELECT COALESCE(r."Request_Status", \'—\') AS name, count(*) AS total,'
        ' CAST(round(COALESCE(sum(' + _AREA_SQM + '), 0)) AS bigint) AS area_sqm'
        f' FROM {_TBL(f)} r'
        ' LEFT JOIN area_units au ON au.id = r."Area_Unit_Id"' +
        where +
        ' GROUP BY 1 ORDER BY total DESC'
    )
    columns = [
        {"key": "name", "label": "الحالة", "type": "text"},
        {"key": "total", "label": "العدد", "type": "int"},
        {"key": "area_sqm", "label": "المساحة (م²)", "type": "int"},
    ]
    rows = _run(db, sql, params)
    return {"key": "by_status", "title": "الطلبات حسب الحالة", "columns": columns, "rows": rows}


def _r_by_survey(db, f):
    where, params = _where(f)
    sql = (
        'SELECT COALESCE(r."Survey_Status", \'—\') AS name, count(*) AS total,'
        ' CAST(round(COALESCE(sum(' + _AREA_SQM + '), 0)) AS bigint) AS area_sqm'
        f' FROM {_TBL(f)} r'
        ' LEFT JOIN area_units au ON au.id = r."Area_Unit_Id"' +
        where +
        ' GROUP BY 1 ORDER BY total DESC'
    )
    columns = [
        {"key": "name", "label": "حالة الرفع المساحي", "type": "text"},
        {"key": "total", "label": "العدد", "type": "int"},
        {"key": "area_sqm", "label": "المساحة (م²)", "type": "int"},
    ]
    rows = _run(db, sql, params)
    return {"key": "by_survey", "title": "الطلبات حسب حالة الرفع المساحي", "columns": columns, "rows": rows}


def _r_by_company(db, f):
    where, params = _where(f)
    sql = (
        'SELECT COALESCE(NULLIF(r."Company", \'\'), \'—\') AS name,'
        ' count(*) AS total,'
        ' count(*) FILTER (WHERE r."Request_Status" = \'مقبول\') AS accepted,'
        ' count(*) FILTER (WHERE r."Request_Status" = \'مرفوض\') AS rejected,'
        ' CAST(round(COALESCE(sum(' + _AREA_SQM + '), 0)) AS bigint) AS area_sqm'
        f' FROM {_TBL(f)} r'
        ' LEFT JOIN area_units au ON au.id = r."Area_Unit_Id"' +
        where +
        ' GROUP BY 1 ORDER BY total DESC'
    )
    columns = [
        {"key": "name", "label": "الشركة", "type": "text"},
        {"key": "total", "label": "إجمالي", "type": "int"},
        {"key": "accepted", "label": "مقبول", "type": "int"},
        {"key": "rejected", "label": "مرفوض", "type": "int"},
        {"key": "area_sqm", "label": "المساحة (م²)", "type": "int"},
    ]
    rows = _run(db, sql, params)
    return {"key": "by_company", "title": "ملخص حسب الشركة", "columns": columns, "rows": rows}


def _r_by_surveyor(db, f):
    where, params = _where(f)
    sql = (
        _geom_cte(f) +
        'SELECT COALESCE(NULLIF(r."Surveyor_Name", \'\'), \'—\') AS name,'
        ' count(*) AS total,'
        ' count(*) FILTER (WHERE r."Survey_Status" LIKE \'تم%\') AS surveyed,'
        ' count(*) FILTER (WHERE r."Request_Status" = \'مقبول\') AS accepted,'
        ' count(*) FILTER (WHERE r."Request_Status" = \'مرفوض\') AS rejected,'
        ' count(geom.rn) AS with_geometry,'
        ' CAST(round(COALESCE(sum(' + _AREA_SQM + '), 0)) AS bigint) AS area_sqm'
        f' FROM {_TBL(f)} r'
        ' LEFT JOIN area_units au ON au.id = r."Area_Unit_Id"'
        ' LEFT JOIN geom ON geom.rn = r."Req_Number"' +
        where +
        ' GROUP BY 1 ORDER BY total DESC'
    )
    columns = [
        {"key": "name", "label": "المساح", "type": "text"},
        {"key": "total", "label": "إجمالي", "type": "int"},
        {"key": "surveyed", "label": "تم الرفع", "type": "int"},
        {"key": "accepted", "label": "مقبول", "type": "int"},
        {"key": "rejected", "label": "مرفوض", "type": "int"},
        {"key": "with_geometry", "label": "له هندسة", "type": "int"},
        {"key": "area_sqm", "label": "المساحة (م²)", "type": "int"},
    ]
    rows = _run(db, sql, params)
    return {"key": "by_surveyor", "title": "أداء المساحين", "columns": columns, "rows": rows}


def _r_by_office(db, f):
    where, params = _where(f)
    sql = (
        _geom_cte(f) +
        'SELECT COALESCE(NULLIF(r."Office_Name", \'\'), \'—\') AS name,'
        ' count(*) AS total,'
        ' count(*) FILTER (WHERE r."Request_Status" = \'مقبول\') AS accepted,'
        ' count(*) FILTER (WHERE r."Request_Status" = \'مرفوض\') AS rejected,'
        ' count(geom.rn) AS with_geometry,'
        ' CAST(round(COALESCE(sum(' + _AREA_SQM + '), 0)) AS bigint) AS area_sqm'
        f' FROM {_TBL(f)} r'
        ' LEFT JOIN area_units au ON au.id = r."Area_Unit_Id"'
        ' LEFT JOIN geom ON geom.rn = r."Req_Number"' +
        where +
        ' GROUP BY 1 ORDER BY total DESC'
    )
    columns = [
        {"key": "name", "label": "المكتب الفني", "type": "text"},
        {"key": "total", "label": "إجمالي", "type": "int"},
        {"key": "accepted", "label": "مقبول", "type": "int"},
        {"key": "rejected", "label": "مرفوض", "type": "int"},
        {"key": "with_geometry", "label": "له هندسة", "type": "int"},
        {"key": "area_sqm", "label": "المساحة (م²)", "type": "int"},
    ]
    rows = _run(db, sql, params)
    return {"key": "by_office", "title": "أداء المكاتب الفنية", "columns": columns, "rows": rows}


def _r_daily(db, f):
    where, params = _where(f)
    sql = (
        'SELECT r."Entry_Date" AS day,'
        ' count(*) AS total,'
        ' count(*) FILTER (WHERE r."Request_Status" = \'مقبول\') AS accepted,'
        ' count(*) FILTER (WHERE r."Request_Status" = \'مرفوض\') AS rejected'
        f' FROM {_TBL(f)} r' +
        where +
        ' GROUP BY 1 ORDER BY 1'
    )
    columns = [
        {"key": "day", "label": "التاريخ", "type": "date"},
        {"key": "total", "label": "الوارد", "type": "int"},
        {"key": "accepted", "label": "مقبول", "type": "int"},
        {"key": "rejected", "label": "مرفوض", "type": "int"},
    ]
    rows = _run(db, sql, params)
    for r in rows:
        r["day"] = _fmt(r.get("day")) or "بدون تاريخ"
    return {"key": "daily", "title": "التقرير اليومي (حسب تاريخ الإدخال)", "columns": columns, "rows": rows}


def _r_users(db, f):
    sql = (
        'SELECT u.username, u.full_name, u.role, u.is_active, u.created_at,'
        ' (SELECT count(*) FROM audit_trail a WHERE a.username = u.username) AS actions,'
        ' (SELECT count(*) FROM audit_trail a WHERE a.username = u.username AND a.action = \'IMPORT\') AS imports,'
        ' (SELECT count(*) FROM audit_trail a WHERE a.username = u.username AND a.action IN (\'CREATE\', \'UPDATE\', \'IMPORT_RESULT\')) AS edits,'
        f' (SELECT count(*) FROM {_TBL(f)} r WHERE r."Created_By" = u.username) AS created_requests'
        ' FROM users u ORDER BY actions DESC, u.username'
    )
    columns = [
        {"key": "username", "label": "المستخدم", "type": "text"},
        {"key": "full_name", "label": "الاسم", "type": "text"},
        {"key": "role", "label": "الدور", "type": "text"},
        {"key": "is_active", "label": "نشط", "type": "bool"},
        {"key": "actions", "label": "إجمالي العمليات", "type": "int"},
        {"key": "imports", "label": "استيراد", "type": "int"},
        {"key": "edits", "label": "تعديل/نقل", "type": "int"},
        {"key": "created_requests", "label": "طلبات أنشأها", "type": "int"},
    ]
    rows = _run(db, sql, {})
    for r in rows:
        r["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
    return {"key": "users", "title": "نشاط المستخدمين", "columns": columns, "rows": rows}


def _r_geometry_coverage(db, f):
    where, params = _where(f)
    sql = (
        _geom_cte(f) +
        'SELECT COALESCE(g.name, \'—\') AS name,'
        ' count(*) AS total,'
        ' count(geom.rn) AS with_geometry,'
        ' count(*) FILTER (WHERE geom.rn IS NULL) AS without_geometry'
        f' FROM {_TBL(f)} r'
        ' LEFT JOIN governorates g ON g.id = r."Governorate_Id"'
        ' LEFT JOIN geom ON geom.rn = r."Req_Number"' +
        where +
        ' GROUP BY 1 ORDER BY total DESC'
    )
    columns = [
        {"key": "name", "label": "المحافظة", "type": "text"},
        {"key": "total", "label": "إجمالي", "type": "int"},
        {"key": "with_geometry", "label": "له هندسة", "type": "int"},
        {"key": "without_geometry", "label": "بدون هندسة", "type": "int"},
    ]
    rows = _run(db, sql, params)
    for r in rows:
        r["coverage_pct"] = round((r["with_geometry"] / r["total"] * 100), 1) if r["total"] else 0
    return {"key": "geometry_coverage", "title": "تغطية الهندسة بالمحافظة", "columns": columns, "rows": rows,
            "extra_columns": [{"key": "coverage_pct", "label": "التغطية %", "type": "float"}]}


def _r_no_geometry(db, f):
    where, params = _where(f)
    extra = (" AND " if where else " WHERE ") + 'geom.rn IS NULL'
    sql = (
        _geom_cte(f) +
        'SELECT r."Req_Number" AS req_number, r."Applicant" AS applicant,'
        ' COALESCE(g.name, \'—\') AS governorate, COALESCE(c.name, \'—\') AS center,'
        ' r."Request_Status" AS status, r."Surveyor_Name" AS surveyor,'
        ' r."Entry_Date" AS entry_date'
        f' FROM {_TBL(f)} r'
        ' LEFT JOIN governorates g ON g.id = r."Governorate_Id"'
        ' LEFT JOIN centers c ON c.id = r."Center_Id"'
        ' LEFT JOIN geom ON geom.rn = r."Req_Number"' +
        where + extra +
        ' ORDER BY r."Entry_Date" NULLS LAST LIMIT 500'
    )
    columns = [
        {"key": "req_number", "label": "رقم الطلب", "type": "text"},
        {"key": "applicant", "label": "مقدم الطلب", "type": "text"},
        {"key": "governorate", "label": "المحافظة", "type": "text"},
        {"key": "center", "label": "المركز", "type": "text"},
        {"key": "status", "label": "الحالة", "type": "text"},
        {"key": "surveyor", "label": "المساح", "type": "text"},
        {"key": "entry_date", "label": "تاريخ الإدخال", "type": "date"},
    ]
    rows = _run(db, sql, params)
    for r in rows:
        r["entry_date"] = _fmt(r.get("entry_date"))
    return {"key": "no_geometry", "title": "طلبات بدون هندسة على الخريطة", "columns": columns, "rows": rows}


def _r_stalled(db, f):
    where, params = _where(f)
    extra = (" AND " if where else " WHERE ") + 'r."Request_Status" NOT IN (\'مقبول\', \'مرفوض\')'
    sql = (
        'SELECT r."Req_Number" AS req_number, r."Applicant" AS applicant,'
        ' COALESCE(g.name, \'—\') AS governorate, COALESCE(c.name, \'—\') AS center,'
        ' r."Request_Status" AS status, r."Survey_Status" AS survey_status,'
        ' r."Surveyor_Name" AS surveyor, r."Entry_Date" AS entry_date,'
        ' r."Status_Updated_At" AS status_updated_at'
        f' FROM {_TBL(f)} r'
        ' LEFT JOIN governorates g ON g.id = r."Governorate_Id"'
        ' LEFT JOIN centers c ON c.id = r."Center_Id"' +
        where + extra +
        ' ORDER BY r."Status_Updated_At" NULLS FIRST LIMIT 500'
    )
    columns = [
        {"key": "req_number", "label": "رقم الطلب", "type": "text"},
        {"key": "applicant", "label": "مقدم الطلب", "type": "text"},
        {"key": "governorate", "label": "المحافظة", "type": "text"},
        {"key": "center", "label": "المركز", "type": "text"},
        {"key": "status", "label": "الحالة", "type": "text"},
        {"key": "survey_status", "label": "حالة الرفع", "type": "text"},
        {"key": "surveyor", "label": "المساح", "type": "text"},
        {"key": "entry_date", "label": "تاريخ الإدخال", "type": "date"},
        {"key": "status_updated_at", "label": "آخر تحديث", "type": "date"},
    ]
    rows = _run(db, sql, params)
    for r in rows:
        r["entry_date"] = _fmt(r.get("entry_date"))
        r["status_updated_at"] = r["status_updated_at"].isoformat(sep=" ", timespec="minutes") if r.get("status_updated_at") else None
    return {"key": "stalled", "title": "الطلبات المتوقفة (غير منتهية)", "columns": columns, "rows": rows}


_REPORTS = {
    "by_governorate": _r_by_governorate,
    "by_center": _r_by_center,
    "by_status": _r_by_status,
    "by_survey": _r_by_survey,
    "by_company": _r_by_company,
    "by_surveyor": _r_by_surveyor,
    "by_office": _r_by_office,
    "daily": _r_daily,
    "users": _r_users,
    "geometry_coverage": _r_geometry_coverage,
    "no_geometry": _r_no_geometry,
    "stalled": _r_stalled,
}


def _build(db: Session, key: str, filters: dict) -> dict:
    fn = _REPORTS.get(key)
    if not fn:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Unknown report")
    report = fn(db, filters)
    all_cols = list(report["columns"]) + list(report.get("extra_columns", []))
    report["totals"] = _totals(all_cols, report["rows"])
    # Stamp the ledger on the payload so the UI and the exported file cannot be
    # mistaken for the other ledger's figures.
    report["ledger"] = _ledger_name(filters.get("ledger"))
    report["ledger_label"] = "طلبات المديرية" if report["ledger"] == "mudryia" else "طلبات الشركة"
    return report


# --- Endpoints -------------------------------------------------------------

@router.get("/list")
def list_reports(current_user: User = Depends(deps.get_current_active_admin)):
    return [{"key": k} for k in _REPORTS.keys()]


@router.get("/filters")
def filters_meta(ledger: Optional[str] = Query(None),
                 db: Session = Depends(deps.get_db),
                 current_user: User = Depends(deps.get_current_active_admin)):
    # Distinct filter values must come from the ledger actually being reported
    # on, otherwise the status dropdown offers company values that match no
    # mudryia row.
    tbl = '"' + LEDGER_GEOM[_ledger_name(ledger)][0] + '"'

    def col(sql):
        return [r[0] for r in db.execute(text(sql)).fetchall() if r[0]]

    return {
        "ledger": _ledger_name(ledger),
        "companies": col('SELECT DISTINCT "Company" FROM %s WHERE "Company" IS NOT NULL ORDER BY 1' % tbl),
        "surveyors": col('SELECT DISTINCT "Surveyor_Name" FROM %s WHERE "Surveyor_Name" IS NOT NULL ORDER BY 1' % tbl),
        "offices": col('SELECT DISTINCT "Office_Name" FROM %s WHERE "Office_Name" IS NOT NULL ORDER BY 1' % tbl),
        "statuses": col('SELECT DISTINCT "Request_Status" FROM %s WHERE "Request_Status" IS NOT NULL ORDER BY 1' % tbl),
        "survey_statuses": col('SELECT DISTINCT "Survey_Status" FROM %s WHERE "Survey_Status" IS NOT NULL ORDER BY 1' % tbl),
        "governorates": [dict(r._mapping) for r in db.execute(text("SELECT id, name FROM governorates ORDER BY name")).fetchall()],
        "centers": [dict(r._mapping) for r in db.execute(text("SELECT id, name, governorate_id FROM centers ORDER BY name")).fetchall()],
        "date_min": _fmt(db.execute(text('SELECT min("Entry_Date") FROM %s' % tbl)).scalar()),
        "date_max": _fmt(db.execute(text('SELECT max("Entry_Date") FROM %s' % tbl)).scalar()),
    }


@router.get("/{key}")
def get_report(key: str, filters: dict = Depends(report_filters),
               db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_admin)):
    return _build(db, key, filters)


@router.get("/{key}/export")
def export_report(key: str, fmt: str = Query("csv", pattern="^(csv|xlsx)$"),
                  filters: dict = Depends(report_filters),
                  db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_admin)):
    report = _build(db, key, filters)
    columns = report["columns"] + report.get("extra_columns", [])
    rows = report["rows"]
    stamp = datetime.now().strftime("%Y%m%d_%H%M")

    def cell(v):
        if v is None:
            return ""
        if isinstance(v, bool):
            return "نعم" if v else "لا"
        return v

    if fmt == "xlsx":
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = report["key"][:31]
        ws.append([c["label"] for c in columns])
        for r in rows:
            ws.append([cell(r.get(c["key"])) for c in columns])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        headers = {"Content-Disposition": f'attachment; filename="report_{key}_{stamp}.xlsx"'}
        return StreamingResponse(buf, headers=headers,
                                 media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([c["label"] for c in columns])
    for r in rows:
        writer.writerow([cell(r.get(c["key"])) for c in columns])
    data = ("\ufeff" + buf.getvalue()).encode("utf-8")
    headers = {"Content-Disposition": f'attachment; filename="report_{key}_{stamp}.csv"'}
    return StreamingResponse(io.BytesIO(data), headers=headers, media_type="text/csv; charset=utf-8")
