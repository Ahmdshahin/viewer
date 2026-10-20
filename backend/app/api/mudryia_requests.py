"""Mudryia request ledger (طلبات المديرية) endpoints.

This is the point-processing counterpart of app.api.requests: the ``mudryia``
points table links here by Req_Number (many points to one request) instead of to
the company ``requests`` ledger.

Deliberately shares the parsing, lookup-resolution and serialisation helpers from
app.api.requests so both ledgers read identically and resolve governorate /
center / village / area-unit through the same lookup tables. Only the model,
the audit table name and the geometry table differ.
"""

import json
from datetime import datetime, date
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from app.api import deps
from app.api.requests import (
    ACCEPTED_SURVEY_STATUSES,
    BulkAssignIn,
    BulkTransitionIn,
    RequestCreate,
    _allowed_request_statuses,
    RequestUpdate,
    TransitionIn,
    _apply_list_filters,
    _assignee_name,
    _attach_names,
    _bulk_geometry,
    _bulk_geometry_counts,
    _bulk_geometry_from_all,
    _claim_if_unassigned,
    _csv_attachment,
    _export_table,
    _find_gov_by_code,
    _fill_request_from_sheet_row,
    _notify_all,
    _notify_user,
    _require_acceptable,
    _require_date_order,
    _require_staff,
    _parse_date,
    _parse_number,
    _parse_req_codes,
    _request_out,
    _request_row_values,
    _resolve_area_unit,
    _reject_unmapped_sheet,
    _resolve_person,
    _sheet_coverage,
    _snap_status,
    _to_ascii_digits,
    BASEMAP_WITH_GEOM,
    BASEMAP_WITHOUT_GEOM,
    get_or_create_center,
    get_or_create_governorate,
    get_or_create_village,
    parse_sheet,
    sync_base_map_bulk,
)
from app.db.models import (
    AuditTrail,
    MudryiaRequest,
    REQUEST_STATUSES,
    SURVEY_STATUSES,
    User,
)

router = APIRouter()

# The mudryia ledger is linked to this geometry table, not to the company layers.
GEOM_TABLES = ("mudryia",)
# Audit trail discriminator, so mudryia edits are distinguishable in history.
AUDIT_TABLE = "mudryia_requests"


def _audit(db: Session, current_user: User, record_id: int, action: str,
           old: dict = None, new: dict = None):
    db.add(AuditTrail(
        table_name=AUDIT_TABLE,
        record_id=record_id,
        action=action,
        old_values=json.dumps(old, ensure_ascii=False) if old else None,
        new_values=json.dumps(new, ensure_ascii=False) if new else None,
        user_id=current_user.id,
        username=current_user.username,
    ))


def _sheet_row_values(db: Session, row: dict, req_number: str, current_user: User,
                      created_out: Optional[dict] = None) -> dict:
    """Compute the column values one parsed sheet row maps to.

    Shared with the company ledger via app.api.requests so both ledgers apply
    identical coercion and lookup resolution; lookups may create a missing
    governorate/center/village (recorded in ``created_out`` when given).
    """
    return _request_row_values(db, row, req_number, current_user, created_out=created_out)


def _build_from_sheet_row(db: Session, row: dict, req_number: str, current_user: User,
                          created_out: Optional[dict] = None) -> MudryiaRequest:
    """Turn one parsed sheet row into an unsaved MudryiaRequest, resolving lookups."""
    values = _sheet_row_values(db, row, req_number, current_user, created_out=created_out)
    values["entry_date"] = values["entry_date"] or date.today()
    return MudryiaRequest(req_number=req_number, **values)


def _fill_from_sheet_row(db: Session, record: MudryiaRequest, row: dict,
                         req_number: str, current_user: User,
                         created_out: Optional[dict] = None) -> dict:
    """Fill the empty fields of an existing row from a re-imported sheet.

    A duplicate request number used to be skipped outright, which left rows
    imported before the sheet's headers were mapped with NULLs forever. Only
    fields the stored record does not have are touched — an existing status,
    address or date is never overwritten by a later import.
    """
    return _fill_request_from_sheet_row(db, record, row, req_number, current_user,
                                        table_name=AUDIT_TABLE, created_out=created_out)


@router.get("")
def list_mudryia_requests(
    page: int = 1,
    per_page: int = 50,
    q: Optional[str] = None,
    governorate_id: Optional[int] = None,
    center_id: Optional[int] = None,
    village_id: Optional[int] = None,
    request_status: Optional[str] = None,
    survey_status: Optional[str] = None,
    surveyor_id: Optional[int] = None,
    office_id: Optional[int] = None,
    assigned_to_me: bool = False,
    has_geometry: Optional[bool] = None,
    governorate: Optional[str] = None,
    center: Optional[str] = None,
    village: Optional[str] = None,
    surveyor: Optional[str] = None,
    office: Optional[str] = None,
    unit_type: Optional[str] = None,
    survey_comment: Optional[str] = None,
    survey_comment_state: Optional[str] = None,
    office_comment: Optional[str] = None,
    office_comment_state: Optional[str] = None,
    entry_from: Optional[str] = None,
    entry_to: Optional[str] = None,
    survey_from: Optional[str] = None,
    survey_to: Optional[str] = None,
    directorate_from: Optional[str] = None,
    directorate_to: Optional[str] = None,
    sort: Optional[str] = None,
    dir: Optional[str] = None,
    ids: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    query = _apply_list_filters(
        db.query(MudryiaRequest), db, current_user, MudryiaRequest,
        q=q, governorate_id=governorate_id, center_id=center_id, village_id=village_id,
        request_status=request_status, survey_status=survey_status,
        surveyor_id=surveyor_id, office_id=office_id,
        assigned_to_me=assigned_to_me, has_geometry=has_geometry,
        governorate=governorate, center=center, village=village,
        surveyor=surveyor, office=office,
        unit_type=unit_type,
        survey_comment=survey_comment, survey_comment_state=survey_comment_state,
        office_comment=office_comment, office_comment_state=office_comment_state,
        entry_from=entry_from, entry_to=entry_to,
        survey_from=survey_from, survey_to=survey_to,
        directorate_from=directorate_from, directorate_to=directorate_to,
        sort=sort, dir=dir, ids=ids,
        geom_tables=GEOM_TABLES,
    )

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    geom = _bulk_geometry(db, [r.req_number for r in items], GEOM_TABLES)
    counts = _bulk_geometry_counts(db, [r.req_number for r in items], GEOM_TABLES)
    out = []
    for r in items:
        item = _request_out(r, geom.get(r.req_number, []), counts.get(r.req_number, 0))
        _attach_names(db, item, r)
        out.append(item)
    return {"items": out, "total": total, "page": page, "per_page": per_page}


@router.get("/stats")
def mudryia_request_stats(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    today = date.today()
    total = db.query(func.count(MudryiaRequest.id)).scalar() or 0
    today_imported = db.query(func.count(MudryiaRequest.id)).filter(
        func.date(MudryiaRequest.entry_date) == today
    ).scalar() or 0
    pending = db.query(func.count(MudryiaRequest.id)).filter(
        MudryiaRequest.request_status == "جديد"
    ).scalar() or 0
    in_survey = db.query(func.count(MudryiaRequest.id)).filter(
        MudryiaRequest.survey_status.isnot(None),
        MudryiaRequest.survey_status != "",
    ).scalar() or 0
    tech_office = db.query(func.count(MudryiaRequest.id)).filter(
        or_(MudryiaRequest.office_name.isnot(None),
            MudryiaRequest.assigned_office_id.isnot(None))
    ).scalar() or 0
    rejected_today = db.query(func.count(MudryiaRequest.id)).filter(
        MudryiaRequest.request_status == "مرفوض",
        func.date(MudryiaRequest.status_updated_at) == today,
    ).scalar() or 0
    accepted_today = db.query(func.count(MudryiaRequest.id)).filter(
        MudryiaRequest.request_status == "مقبول",
        func.date(MudryiaRequest.status_updated_at) == today,
    ).scalar() or 0

    by_status = dict(db.execute(
        text(f'SELECT "Request_Status", COUNT(*) FROM {AUDIT_TABLE} GROUP BY "Request_Status"')
    ).fetchall())
    by_center = [{"name": name, "count": n} for name, n in db.execute(
        text(f'''SELECT c.name, COUNT(*) FROM {AUDIT_TABLE} r
                LEFT JOIN centers c ON c.id = r."Center_Id"
                GROUP BY c.name ORDER BY COUNT(*) DESC LIMIT 8''')
    ).fetchall()]

    return {
        "total": total,
        "today_imported": today_imported,
        "pending": pending,
        "in_survey": in_survey,
        "tech_office": tech_office,
        "rejected_today": rejected_today,
        "accepted_today": accepted_today,
        "by_status": {k: v for k, v in by_status.items()},
        "by_center": by_center,
    }


# Declared before "/{request_id}" so the literal paths are not swallowed by the
# int path parameter.
@router.get("/export")
def export_mudryia_requests_csv(
    q: Optional[str] = None,
    governorate_id: Optional[int] = None,
    center_id: Optional[int] = None,
    village_id: Optional[int] = None,
    request_status: Optional[str] = None,
    survey_status: Optional[str] = None,
    surveyor_id: Optional[int] = None,
    office_id: Optional[int] = None,
    assigned_to_me: bool = False,
    has_geometry: Optional[bool] = None,
    governorate: Optional[str] = None,
    center: Optional[str] = None,
    village: Optional[str] = None,
    surveyor: Optional[str] = None,
    office: Optional[str] = None,
    unit_type: Optional[str] = None,
    survey_comment: Optional[str] = None,
    survey_comment_state: Optional[str] = None,
    office_comment: Optional[str] = None,
    office_comment_state: Optional[str] = None,
    entry_from: Optional[str] = None,
    entry_to: Optional[str] = None,
    survey_from: Optional[str] = None,
    survey_to: Optional[str] = None,
    directorate_from: Optional[str] = None,
    directorate_to: Optional[str] = None,
    sort: Optional[str] = None,
    dir: Optional[str] = None,
    ids: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Download every mudryia request matching the list filters as a CSV sheet."""
    query = _apply_list_filters(
        db.query(MudryiaRequest), db, current_user, MudryiaRequest,
        q=q, governorate_id=governorate_id, center_id=center_id, village_id=village_id,
        request_status=request_status, survey_status=survey_status,
        surveyor_id=surveyor_id, office_id=office_id,
        assigned_to_me=assigned_to_me, has_geometry=has_geometry,
        governorate=governorate, center=center, village=village,
        surveyor=surveyor, office=office,
        unit_type=unit_type,
        survey_comment=survey_comment, survey_comment_state=survey_comment_state,
        office_comment=office_comment, office_comment_state=office_comment_state,
        entry_from=entry_from, entry_to=entry_to,
        survey_from=survey_from, survey_to=survey_to,
        directorate_from=directorate_from, directorate_to=directorate_to,
        sort=sort, dir=dir, ids=ids,
        geom_tables=GEOM_TABLES,
    )
    items = query.all()
    headers, rows = _export_table(db, items)
    return _csv_attachment(headers, rows, "requests_mudryia")


@router.get("/import-template")
def download_mudryia_import_template(
    current_user: User = Depends(deps.get_current_user),
):
    """Blank .xlsx for filling in new mudryia requests, with the expected headers."""
    from fastapi.responses import Response
    from app.api.import_template import build_requests_template

    body = build_requests_template("mudryia")
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="mudryia_requests_template.xlsx"'},
    )


@router.get("/import-result-template")
def download_mudryia_import_result_template(
    current_user: User = Depends(deps.get_current_user),
):
    """Blank .xlsx for importing survey results against existing mudryia requests."""
    from fastapi.responses import Response
    from app.api.import_template import build_results_template

    body = build_results_template()
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="mudryia_results_template.xlsx"'},
    )


@router.get("/{request_id}")
def get_mudryia_request(
    request_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    r = db.query(MudryiaRequest).filter(MudryiaRequest.id == request_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    item = _request_out(r, _bulk_geometry(db, [r.req_number], GEOM_TABLES).get(r.req_number, []),
                        _bulk_geometry_counts(db, [r.req_number], GEOM_TABLES).get(r.req_number, 0))
    _attach_names(db, item, r)
    item["assigned_to"] = _assignee_name(db, r)
    history = db.query(AuditTrail).filter(
        AuditTrail.table_name == AUDIT_TABLE,
        AuditTrail.record_id == request_id,
    ).order_by(AuditTrail.id.desc()).all()
    item["history"] = [
        {
            "action": h.action,
            "username": h.username,
            "created_at": h.created_at.isoformat() if h.created_at else None,
            "old_values": json.loads(h.old_values) if h.old_values else None,
            "new_values": json.loads(h.new_values) if h.new_values else None,
        }
        for h in history
    ]
    return item


@router.get("/{request_id}/has-geometry")
def mudryia_request_has_geometry(
    request_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    r = db.query(MudryiaRequest).filter(MudryiaRequest.id == request_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    return {
        "req_number": r.req_number,
        "layers": _bulk_geometry(db, [r.req_number], GEOM_TABLES).get(r.req_number, []),
        "count": _bulk_geometry_counts(db, [r.req_number], GEOM_TABLES).get(r.req_number, 0),
    }


@router.post("")
def create_mudryia_request(
    body: RequestCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_editor),
):
    body.req_number = (body.req_number or "").strip()
    if not body.req_number:
        raise HTTPException(status_code=400, detail="رقم الطلب مطلوب")
    if db.query(MudryiaRequest).filter(MudryiaRequest.req_number == body.req_number).first():
        raise HTTPException(status_code=400, detail=f"الطلب {body.req_number} موجود بالفعل")

    r = _build_from_sheet_row(db, {
        "applicant": body.applicant,
        "phone": body.phone,
        "address": body.address,
        "area_value": body.area_value,
        "area_unit_name": body.area_unit,
        "unit_type": body.unit_type,
        "governorate": body.governorate,
        "center": body.center,
        "village": body.village,
        "surveyor": body.surveyor,
        "office": body.office,
        "survey_status": body.survey_status,
        "survey_comment": body.survey_comment,
        "office_comment": body.office_comment,
        "request_status": body.request_status,
        "reqra_number": body.reqra_number,
        "entry_date": body.entry_date,
        "survey_date": body.survey_date,
    }, body.req_number, current_user)
    # A manually added request keeps an empty entry date unless the user sets
    # one (the sheet import still stamps today when the file has no date).
    r.entry_date = _parse_date(body.entry_date)
    db.add(r)
    db.flush()
    _audit(db, current_user, r.id, "CREATE",
           new={"req_number": r.req_number, "request_status": r.request_status})
    geom_n = _bulk_geometry_counts(db, [r.req_number], GEOM_TABLES).get(r.req_number, 0)
    r.base_map = BASEMAP_WITH_GEOM if geom_n else BASEMAP_WITHOUT_GEOM
    db.commit()
    db.refresh(r)
    item = _request_out(r, None)
    _attach_names(db, item, r)
    return item


@router.patch("/{request_id}")
def update_mudryia_request(
    request_id: int,
    body: RequestUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_editor),
):
    r = db.query(MudryiaRequest).filter(MudryiaRequest.id == request_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    old = {"req_number": r.req_number, "applicant": r.applicant, "request_status": r.request_status}
    changes = {}

    # The edit form sends "" from a dropdown's empty option to clear a field;
    # None means "leave as-is". Consume the clearers here so "" can never reach
    # get_or_create_* (a code-derived centre would otherwise resurrect itself)
    # and every clear lands as a NULL with its own audit entry.
    cleared = set()
    for name, column in (("applicant", "applicant"), ("phone", "phone"), ("address", "address"),
                         ("unit_type", "unit_type"), ("survey_status", "survey_status"),
                         ("survey_comment", "survey_comment"), ("office_comment", "office_comment"),
                         ("request_status", "request_status"), ("reqra_number", "reqra_number"),
                         ("governorate", "governorate_id"), ("center", "center_id"),
                         ("village", "village_id"), ("area_unit", "area_unit_id"),
                         ("surveyor", "surveyor_name"), ("office", "office_name"),
                         ("entry_date", "entry_date"), ("survey_date", "survey_date"),
                         ("distribution_date", "distribution_date"),
                         ("alt_survey_date", "alt_survey_date"),
                         ("geodesy_date", "geodesy_date"),
                         ("directorate_date", "directorate_date"),
                         ("landmarks", "landmarks"), ("field_team", "field_team"),
                         ("raw_files", "raw_files"), ("base_map", "base_map")):
        if getattr(body, name, None) == "":
            setattr(body, name, None)
            cleared.add(name)
            if getattr(r, column) is not None:
                setattr(r, column, None)
                changes[name] = None

    # Clearing the name must also release the person it resolved to, or the
    # row would keep an owner the form no longer shows (and never re-claims).
    if "surveyor" in cleared:
        r.assigned_surveyor_id = None
    if "office" in cleared:
        r.assigned_office_id = None

    def set_if(field, value):
        nonlocal changes
        if value is not None:
            before = getattr(r, field)
            if before != value:
                setattr(r, field, value)
                changes[field] = value

    set_if("applicant", body.applicant)
    set_if("phone", body.phone)
    set_if("address", body.address)
    set_if("area_value", body.area_value)
    if "area_value" in (body.model_fields_set or set()) and body.area_value is None and r.area_value is not None:
        r.area_value = None
        changes["area_value"] = None
    set_if("unit_type", body.unit_type)
    set_if("survey_status", body.survey_status)
    set_if("survey_comment", body.survey_comment)
    set_if("office_comment", body.office_comment)
    set_if("request_status", body.request_status)
    # The status select replaces the old Change-status card, so a status
    # written here must stamp the same "last status change" the transition
    # endpoint would (the daily counters read Status_Updated_At).
    if "request_status" in changes:
        r.status_updated_at = datetime.utcnow()
    set_if("reqra_number", body.reqra_number)
    set_if("landmarks", body.landmarks)
    set_if("field_team", body.field_team)
    set_if("raw_files", body.raw_files)
    set_if("base_map", body.base_map)
    if body.area_unit is not None:
        uid = _resolve_area_unit(db, body.area_unit)
        if r.area_unit_id != uid:
            r.area_unit_id = uid
            changes["area_unit"] = body.area_unit
    if body.governorate is not None or body.center is not None or body.village is not None:
        gov_code, center_code = _parse_req_codes(r.req_number)
        gov_id = r.governorate_id
        if body.governorate is not None:
            gov_id = get_or_create_governorate(db, body.governorate, gov_code)
        center_id = r.center_id
        if body.center is not None:
            center_id = get_or_create_center(db, gov_id, body.center, center_code)
        village_id = r.village_id
        if body.village is not None:
            village_id = get_or_create_village(db, center_id, body.village)
        if body.governorate is not None and r.governorate_id != gov_id:
            r.governorate_id = gov_id
            changes["governorate"] = body.governorate
        if body.center is not None and r.center_id != center_id:
            r.center_id = center_id
            changes["center"] = body.center
        if body.village is not None and r.village_id != village_id:
            r.village_id = village_id
            changes["village"] = body.village
    if body.surveyor is not None and r.surveyor_name != body.surveyor:
        r.surveyor_name = body.surveyor
        r.assigned_surveyor_id = _resolve_person(db, body.surveyor)
        changes["surveyor"] = body.surveyor
    if body.office is not None and r.office_name != body.office:
        r.office_name = body.office
        r.assigned_office_id = _resolve_person(db, body.office)
        changes["office"] = body.office
    if body.entry_date is not None:
        d = _parse_date(body.entry_date)
        if d and d != r.entry_date:
            r.entry_date = d
            changes["entry_date"] = body.entry_date
    if body.survey_date is not None:
        d = _parse_date(body.survey_date)
        if d and d != r.survey_date:
            r.survey_date = d
            changes["survey_date"] = body.survey_date
    for name in ("distribution_date", "alt_survey_date", "geodesy_date", "directorate_date"):
        value = getattr(body, name, None)
        if value is not None:
            d = _parse_date(value)
            if d and d != getattr(r, name):
                setattr(r, name, d)
                changes[name] = value

    _require_acceptable(r)
    _require_date_order(r)
    _require_staff(r)
    if changes:
        _claim_if_unassigned(r, changes, current_user)
        _audit(db, current_user, r.id, "UPDATE", old=old, new={**old, **changes})
    db.commit()
    db.refresh(r)
    item = _request_out(r, None)
    _attach_names(db, item, r)
    item["assigned_to"] = _assignee_name(db, r)
    return item


@router.post("/{request_id}/transition")
def transition_mudryia_request(
    request_id: int,
    body: TransitionIn,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_editor),
):
    r = db.query(MudryiaRequest).filter(MudryiaRequest.id == request_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    target = (body.to or "").strip()
    if target not in _allowed_request_statuses(db):
        raise HTTPException(status_code=400, detail=f"حالة غير صالحة: {target}")
    if r.request_status == target:
        raise HTTPException(status_code=400, detail="الحالة نفسها بلا تغيير")
    old = r.request_status
    r.request_status = target
    r.status_updated_at = datetime.utcnow()
    new_values = {"req_number": r.req_number, "request_status": target}
    if body.comment:
        new_values["comment"] = body.comment
    _require_acceptable(r)
    # A status change is an edit too: it claims an unowned request.
    _claim_if_unassigned(r, new_values, current_user)
    _audit(db, current_user, r.id, "TRANSITION",
           old={"request_status": old}, new=new_values)
    assignee = r.assigned_surveyor_id or r.assigned_office_id
    if assignee and assignee != current_user.id:
        _notify_user(db, assignee, "transition",
                     f"تغيّرت حالة الطلب {r.req_number} إلى {target}",
                     (body.comment or "").strip() or f"بواسطة {current_user.username}",
                     link_req=f"mudryia:{r.req_number}")
    db.commit()
    db.refresh(r)
    return {"id": r.id, "req_number": r.req_number, "request_status": r.request_status,
            "assigned_to": _assignee_name(db, r)}


@router.post("/bulk-assign")
def bulk_assign_mudryia_requests(
    body: BulkAssignIn,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_editor),
):
    """Assign many mudryia requests to a surveyor and/or office by name."""
    ids = [i for i in (body.ids or []) if isinstance(i, int) and i > 0][:2000]
    if not ids:
        raise HTTPException(status_code=400, detail="No request ids provided")
    surveyor = (body.surveyor or "").strip() or None
    office = (body.office or "").strip() or None
    if not surveyor and not office:
        raise HTTPException(status_code=400, detail="Provide a surveyor or an office")
    s_id = _resolve_person(db, surveyor) if surveyor else None
    o_id = _resolve_person(db, office) if office else None
    updated = 0
    for r in db.query(MudryiaRequest).filter(MudryiaRequest.id.in_(ids)).all():
        changes = {}
        if surveyor is not None:
            if r.surveyor_name != surveyor:
                changes["surveyor"] = surveyor
            r.surveyor_name = surveyor
            r.assigned_surveyor_id = s_id
        if office is not None:
            if r.office_name != office:
                changes["office"] = office
            r.office_name = office
            r.assigned_office_id = o_id
        if changes:
            changes["req_number"] = r.req_number
            _audit(db, current_user, r.id, "ASSIGN", new=changes)
            target_uid = s_id or o_id
            if target_uid and target_uid != current_user.id:
                _notify_user(db, target_uid, "assign",
                             f"تم إسناد الطلب {r.req_number} إليك",
                             f"بواسطة {current_user.username}",
                             link_req=f"mudryia:{r.req_number}")
            updated += 1
    db.commit()
    return {"updated": updated}


@router.post("/bulk-transition")
def bulk_transition_mudryia_requests(
    body: BulkTransitionIn,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_editor),
):
    """Move many mudryia requests to one status, with an optional shared comment."""
    ids = [i for i in (body.ids or []) if isinstance(i, int) and i > 0][:2000]
    if not ids:
        raise HTTPException(status_code=400, detail="No request ids provided")
    target = (body.to or "").strip()
    if target not in _allowed_request_statuses(db):
        raise HTTPException(status_code=400, detail=f"حالة غير صالحة: {target}")
    comment = (body.comment or "").strip() or None
    rows = db.query(MudryiaRequest).filter(MudryiaRequest.id.in_(ids)).all()
    if target == "مقبول":
        bad = [r.req_number for r in rows
               if r.request_status != target
               and ((r.survey_status or "").strip() not in ACCEPTED_SURVEY_STATUSES
                    or not (r.surveyor_name or "").strip()
                    or not r.entry_date)]
        if bad:
            raise HTTPException(status_code=400, detail=f"{len(bad)} طلب لا يستوفي شروط القبول (تم المعاينة + مساح + تاريخ الإدخال)")
    updated = 0
    for r in rows:
        if r.request_status == target:
            continue
        old = r.request_status
        r.request_status = target
        r.status_updated_at = datetime.utcnow()
        new_values = {"req_number": r.req_number, "request_status": target}
        if comment:
            new_values["comment"] = comment
        _claim_if_unassigned(r, new_values, current_user)
        _audit(db, current_user, r.id, "TRANSITION", old={"request_status": old}, new=new_values)
        assignee = r.assigned_surveyor_id or r.assigned_office_id
        if assignee and assignee != current_user.id:
            _notify_user(db, assignee, "transition",
                         f"تغيّرت حالة الطلب {r.req_number} إلى {target}",
                         comment or f"بواسطة {current_user.username}",
                         link_req=f"mudryia:{r.req_number}")
        updated += 1
    db.commit()
    return {"updated": updated}


@router.post("/import")
def import_mudryia_requests(
    file: UploadFile = File(...),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_editor),
    force: bool = False,
):
    raw = file.file.read()
    unmapped: set = set()
    parsed = parse_sheet(raw, file.filename or "sheet.csv", unmapped_out=unmapped)
    if not parsed:
        raise HTTPException(
            status_code=400,
            detail="لا توجد صفوف قابلة للقراءة في الملف"
                    + (f" (أعمدة غير معروفة: {', '.join(sorted(unmapped))})" if unmapped else ""),
        )
    if not force:
        _reject_unmapped_sheet(parsed, unmapped)

    added, duplicated, errors = [], [], []
    updated, update_errors = [], []
    skipped_no_number = 0
    created_out: dict = {}
    for row in parsed:
        req_number = _to_ascii_digits(row.get("req_number", "") or "").strip()
        if not req_number:
            # The template ships a status reference list below the header row.
            # Those rows carry a status but no business key, so skip them
            # quietly instead of reporting them as import errors.
            skipped_no_number += 1
            continue
        # A failing row rolls its SAVEPOINT back, including any lookup it had
        # just created — restore the report so it does not claim a phantom.
        snapshot = {k: list(v) for k, v in created_out.items()}
        try:
            # Everything that touches the database runs inside a SAVEPOINT:
            # a failing row must roll back only itself — never the rows
            # imported before it, and never poison the outer transaction.
            with db.begin_nested():
                existing = db.query(MudryiaRequest).filter(MudryiaRequest.req_number == req_number).first()
                if existing is not None:
                    # Re-importing a sheet whose headers only became known later must
                    # fill the fields the row is still missing, not skip it again.
                    changes = _fill_from_sheet_row(db, existing, row, req_number, current_user,
                                                   created_out=created_out)
                else:
                    changes = None
                    r = _build_from_sheet_row(db, row, req_number, current_user,
                                              created_out=created_out)
                    db.add(r)
                    db.flush()
                    _audit(db, current_user, r.id, "IMPORT",
                           new={"req_number": req_number, "request_status": r.request_status})
            if existing is not None:
                (updated if changes else duplicated).append(req_number)
            else:
                added.append(req_number)
        except Exception as exc:  # noqa: BLE001
            # SAVEPOINT keeps every row imported before this one; a plain
            # rollback would silently erase them while still reporting them
            # as added.
            created_out.clear()
            created_out.update(snapshot)
            errors.append({"reason": str(exc), "req_number": req_number})
    if added:
        _notify_all(db, "import",
                    title="استيراد جديد لطلبات المديرية",
                    body=f"تم استيراد {len(added)} طلبًا جديدًا")

    db.commit()

    try:
        sync_base_map_bulk(db, added + updated + duplicated)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"Base_Map sync failed after import: {exc}")

    rows_with_no, seen, avg_fields, missing = _sheet_coverage(parsed)
    return {
        "added": len(added),
        "duplicated": len(duplicated),
        "errors": len(errors) + len(update_errors),
        # Rows that already existed but gained the fields they were missing.
        "updated": len(updated),
        "added_numbers": added[:50],
        "duplicates": duplicated[:50],
        "updated_numbers": updated[:50],
        "error_details": (errors + update_errors)[:20],
        # Columns in the uploaded sheet that no mapping matched, so nothing is
        # silently dropped — the caller can report them to the user.
        "unmapped_columns": sorted(unmapped),
        "skipped_no_number": skipped_no_number,
        # How much of the sheet really mapped. `missing_fields` lists the record
        # fields the sheet did not supply, which is the signal that the headers
        # did not match and the stored rows are effectively empty.
        "rows_with_number": rows_with_no,
        "mapped_fields": sorted(seen),
        "missing_fields": missing,
        "avg_fields_per_row": round(avg_fields, 2),
        # Lookup values this import had to add to the shared lookups tables.
        "created_lookups": created_out,
    }


@router.post("/import-result")
def mudryia_import_result(
    file: UploadFile = File(...),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_editor),
    force: bool = False,
):
    raw = file.file.read()
    unmapped: set = set()
    parsed = parse_sheet(raw, file.filename or "result.csv", unmapped_out=unmapped, kind="result")
    if not parsed:
        raise HTTPException(
            status_code=400,
            detail="لا توجد صفوف قابلة للقراءة في الملف"
                    + (f" (أعمدة غير معروفة: {', '.join(sorted(unmapped))})" if unmapped else ""),
        )
    # A results sheet legitimately carries only a number and a verdict, so the
    # same coverage guard would misfire here. Only require that a result column
    # and a request-number column were actually recognised.
    if not force and not any(r.get("result") for r in parsed):
        raise HTTPException(
            status_code=400,
            detail=(
                "تم إيقاف الاستيراد: لا يوجد عمود نتيجة معروف. "
                f"الأعمدة غير المعروفة: {', '.join(sorted(unmapped)) or '(لم يُقرأ أي عمود معروف)'} — "
                "الأسماء المتوقعة لملف النتائج: رقم الطلب | النتيجة | رقم التقنين. "
                "أعد تسمية رؤوس الأعمدة ثم أعد المحاولة، أو استخدم force=true للتجاوز."
            ),
        )

    updated, not_found, errors = [], [], []
    skipped_no_number = 0
    rejected = accepted = 0
    for row in parsed:
        req_number = _to_ascii_digits(row.get("req_number", "") or "").strip()
        if not req_number:
            # The template ships a status reference list below the header row.
            # Those rows carry a status but no business key, so skip them
            # quietly instead of reporting them as import errors.
            skipped_no_number += 1
            continue
        r = db.query(MudryiaRequest).filter(MudryiaRequest.req_number == req_number).first()
        if not r:
            not_found.append(req_number)
            continue
        result = str(row.get("result") or row.get("request_status") or "").strip()
        if not result:
            errors.append({"reason": "missing_result", "req_number": req_number})
            continue
        if "مرفوض" in result:
            result = "مرفوض"
        elif "مقبول" in result:
            result = "مقبول"
        old = r.request_status
        new_status = result if result in REQUEST_STATUSES else r.request_status
        r.request_status = new_status
        if row.get("reqra_number"):
            r.reqra_number = str(row["reqra_number"]).strip()
        r.status_updated_at = datetime.utcnow()
        _audit(db, current_user, r.id, "IMPORT_RESULT",
               old={"request_status": old},
               new={"request_status": new_status, "reqra_number": r.reqra_number})
        updated.append(req_number)
        if new_status == "مرفوض":
            rejected += 1
        elif new_status == "مقبول":
            accepted += 1
    if updated:
        _notify_all(db, "result",
                    title="تحديث نتيجة طلبات المديرية",
                    body=f"تم تحديث نتيجة {len(updated)} طلبًا — {accepted} مقبول | {rejected} مرفوض")

    db.commit()

    return {
        "updated": len(updated),
        "not_found": len(not_found),
        "errors": len(errors),
        "rejected": rejected,
        "accepted": accepted,
        "updated_numbers": updated[:50],
        "not_found_numbers": not_found[:50],
        "unmapped_columns": sorted(unmapped),
        "skipped_no_number": skipped_no_number,
    }
