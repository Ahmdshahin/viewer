"""Admin-managed lookup endpoints (governorates / centers / villages / area_units).

Values are added, renamed, or disabled — never hard-deleted once used, so
referencing requests stay intact. Governed by the admin role only.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.api import deps
from app.db.models import (
    AreaUnit, CadastralRequest, Center, Governorate, LookupValue, MudryiaRequest,
    REQUEST_STATUSES, SURVEY_STATUSES, User, Village,
)

router = APIRouter()

LOOKUP_TYPES = ("governorates", "centers", "villages", "area_units")


def _model_for(kind: str):
    return {
        "governorates": Governorate,
        "centers": Center,
        "villages": Village,
        "area_units": AreaUnit,
    }[kind]


class LookupCreate(BaseModel):
    name: str
    code: Optional[str] = None
    governorate_id: Optional[int] = None
    center_id: Optional[int] = None


class LookupUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    is_active: Optional[bool] = None


def _out(kind: str, obj) -> dict:
    base = {
        "id": obj.id,
        "name": obj.name,
        "code": getattr(obj, "code", None),
        "is_active": obj.is_active,
    }
    if kind == "centers":
        base["governorate_id"] = obj.governorate_id
    if kind == "villages":
        base["center_id"] = obj.center_id
    return base


@router.get("/meta")
def lookup_meta(current_user: User = Depends(deps.get_current_user)):
    return {"types": LOOKUP_TYPES}


@router.get("/people")
def lookup_people(
    type: str = Query("surveyor"),
    ledger: str = Query("all"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Distinct surveyor/office names already written in the ledgers, plus the
    raw-files status values each ledger has actually used.

    The edit form offers these as dropdowns instead of free-text fields, so
    the same person/status cannot be typed twice with two spellings. Scoped per
    ledger because the two ledgers keep separate staff and status lists.
    """
    if type not in ("surveyor", "office", "raw_files"):
        raise HTTPException(status_code=400, detail="type must be surveyor, office or raw_files")
    if ledger not in ("company", "mudryia", "all"):
        raise HTTPException(status_code=400, detail="ledger must be company, mudryia or all")
    models = {"company": [CadastralRequest], "mudryia": [MudryiaRequest],
              "all": [CadastralRequest, MudryiaRequest]}[ledger]
    name_col = {"surveyor": "surveyor_name", "office": "office_name",
                "raw_files": "raw_files"}[type]
    names = set()
    for model in models:
        column = getattr(model, name_col)
        for (value,) in db.query(column).filter(column.isnot(None), column != "").distinct().all():
            names.add(value)
    return sorted(names)


class PeopleRename(BaseModel):
    old: str
    new: str


class PeopleMerge(BaseModel):
    sources: List[str]
    target: str


def _repoint_people(db: Session, type: str, mapping: dict) -> int:
    if type not in PEOPLE_COLUMNS:
        raise HTTPException(status_code=400, detail="type must be surveyor, office or raw_files")
    moved = 0
    for model in (CadastralRequest, MudryiaRequest):
        for col in PEOPLE_COLUMNS[type]:
            column = getattr(model, col)
            for old, new in mapping.items():
                moved += db.query(model).filter(column == old).update(
                    {column: new}, synchronize_session=False)
    return moved


@router.post("/people/rename")
def rename_person(
    body: PeopleRename,
    type: str = Query("surveyor"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
):
    """Fix a staff-name spelling everywhere it appears in both ledgers."""
    old = (body.old or "").strip()
    new = (body.new or "").strip()
    if not old or not new:
        raise HTTPException(status_code=400, detail="Both old and new names are required")
    if old == new:
        raise HTTPException(status_code=400, detail="Nothing to change")
    moved = _repoint_people(db, type, {old: new})
    # The resolved user link follows the new spelling on next edit; fix the
    # direct assignments now so ownership never points at a stale name.
    if type == "surveyor":
        from app.api.requests import _resolve_person as _rp
        uid = _rp(db, new)
        for model in (CadastralRequest, MudryiaRequest):
            db.query(model).filter(model.surveyor_name == new).update(
                {model.assigned_surveyor_id: uid}, synchronize_session=False)
    if type == "office":
        from app.api.requests import _resolve_person as _rp
        uid = _rp(db, new)
        for model in (CadastralRequest, MudryiaRequest):
            db.query(model).filter(model.office_name == new).update(
                {model.assigned_office_id: uid}, synchronize_session=False)
    db.commit()
    return {"moved": moved}


@router.post("/people/merge")
def merge_people(
    body: PeopleMerge,
    type: str = Query("surveyor"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
):
    """Fold duplicate staff-name spellings into one target spelling."""
    sources = [s.strip() for s in (body.sources or []) if isinstance(s, str) and s.strip()]
    target = (body.target or "").strip()
    if not sources or not target:
        raise HTTPException(status_code=400, detail="sources and target names are required")
    mapping = {s: target for s in sources if s != target}
    if not mapping:
        raise HTTPException(status_code=400, detail="Nothing to change")
    moved = _repoint_people(db, type, mapping)
    db.commit()
    return {"moved": moved}

# NOTE: registered before the /{kind} catch-all below — FastAPI matches routes
# in registration order, and "people" would otherwise be read as a lookup kind.
@router.get("/{kind}")
def list_lookups(
    kind: str,
    governorate_id: Optional[int] = None,
    center_id: Optional[int] = None,
    include_inactive: bool = False,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    if kind not in LOOKUP_TYPES:
        raise HTTPException(status_code=404, detail="Unknown lookup type")
    q = db.query(_model_for(kind))
    if not include_inactive:
        q = q.filter(_model_for(kind).is_active == True)  # noqa: E712
    if kind == "centers" and governorate_id is not None:
        q = q.filter(Center.governorate_id == governorate_id)
    if kind == "villages" and center_id is not None:
        q = q.filter(Village.center_id == center_id)
    objs = q.order_by(_model_for(kind).name.asc()).all()
    return [_out(kind, o) for o in objs]


@router.post("/{kind}")
def create_lookup(
    kind: str,
    body: LookupCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
):
    if kind not in LOOKUP_TYPES:
        raise HTTPException(status_code=404, detail="Unknown lookup type")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="الاسم مطلوب")
    if kind == "governorates":
        if db.query(Governorate).filter(Governorate.name == name).first():
            raise HTTPException(status_code=400, detail="المحافظة موجودة بالفعل")
        obj = Governorate(name=name, code=(body.code or "").strip() or None)
    elif kind == "centers":
        if not body.governorate_id:
            raise HTTPException(status_code=400, detail="governorate_id مطلوب للمركز")
        if db.query(Center).filter(
            Center.governorate_id == body.governorate_id, Center.name == name
        ).first():
            raise HTTPException(status_code=400, detail="المركز موجود بالفعل")
        obj = Center(governorate_id=body.governorate_id, name=name, code=(body.code or "").strip() or None)
    elif kind == "villages":
        if not body.center_id:
            raise HTTPException(status_code=400, detail="center_id مطلوب للقرية")
        if db.query(Village).filter(Village.center_id == body.center_id, Village.name == name).first():
            raise HTTPException(status_code=400, detail="القرية موجودة بالفعل")
        obj = Village(center_id=body.center_id, name=name)
    else:
        code = (body.code or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="code مطلوب لوحدة المساحة")
        if db.query(AreaUnit).filter(AreaUnit.code == code).first():
            raise HTTPException(status_code=400, detail="الكود موجود بالفعل")
        obj = AreaUnit(code=code, name=name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return _out(kind, obj)


@router.patch("/{kind}/{item_id}")
def update_lookup(
    kind: str,
    item_id: int,
    body: LookupUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
):
    if kind not in LOOKUP_TYPES:
        raise HTTPException(status_code=404, detail="Unknown lookup type")
    obj = db.query(_model_for(kind)).filter(_model_for(kind).id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Not found")
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="الاسم مطلوب")
        obj.name = name
    if body.code is not None:
        obj.code = body.code.strip() or None
    if body.is_active is not None:
        obj.is_active = body.is_active
    db.commit()
    db.refresh(obj)
    return _out(kind, obj)


@router.post("/{kind}/{item_id}/disable")
def disable_lookup(
    kind: str,
    item_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
):
    if kind not in LOOKUP_TYPES:
        raise HTTPException(status_code=404, detail="Unknown lookup type")
    obj = db.query(_model_for(kind)).filter(_model_for(kind).id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Not found")
    obj.is_active = False
    db.commit()
    return {"id": item_id, "is_active": False}


@router.post("/{kind}/{item_id}/enable")
def enable_lookup(
    kind: str,
    item_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
):
    if kind not in LOOKUP_TYPES:
        raise HTTPException(status_code=404, detail="Unknown lookup type")
    obj = db.query(_model_for(kind)).filter(_model_for(kind).id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Not found")
    obj.is_active = True
    db.commit()
    return {"id": item_id, "is_active": True}


class LookupMerge(BaseModel):
    source_ids: List[int]
    target_id: int


@router.post("/{kind}/merge")
def merge_lookups(
    kind: str,
    body: LookupMerge,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
):
    """Fold duplicate lookup rows into one target: re-point both ledgers, then
    disable the sources (never hard-deleted, so history stays intact)."""
    if kind not in LOOKUP_TYPES:
        raise HTTPException(status_code=404, detail="Unknown lookup type")
    model = _model_for(kind)
    sources = [i for i in (body.source_ids or [])
               if isinstance(i, int) and i > 0 and i != body.target_id]
    if not sources:
        raise HTTPException(status_code=400, detail="No source ids provided")
    target = db.query(model).filter(model.id == body.target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    col = {
        "governorates": "governorate_id",
        "centers": "center_id",
        "villages": "village_id",
        "area_units": "area_unit_id",
    }[kind]
    moved = 0
    for ledger in (CadastralRequest, MudryiaRequest):
        fk = getattr(ledger, col)
        moved += db.query(ledger).filter(fk.in_(sources)).update(
            {fk: target.id}, synchronize_session=False)
    db.query(model).filter(model.id.in_(sources)).update(
        {model.is_active: False}, synchronize_session=False)
    db.commit()
    return {"moved": moved, "target_id": target.id}


# ---- Managed value lists (request/survey/raw statuses) ----
# Ledger rows store these as plain text, so the admin can curate the exact
# vocabulary the forms, filters and transitions offer.

VALUE_KINDS = ("request_status", "survey_status", "raw_status", "surveyor", "office")

# Which ledger columns carry each value kind (both ledgers, same column names).
VALUE_COLUMNS = {
    "request_status": ("request_status",),
    "survey_status": ("survey_status",),
    "raw_status": ("raw_files",),
    "surveyor": ("surveyor_name",),
    "office": ("office_name",),
}

# Staff-name columns for the people cleanup endpoints below.
PEOPLE_COLUMNS = {
    "surveyor": ("surveyor_name",),
    "office": ("office_name",),
    "raw_files": ("raw_files",),
}

# Seed = the exact values the request form offers today (per the approved
# screenshots), plus any extra spellings already stored in ledger rows.
VALUE_SEED = {
    "request_status": ["مقبول", "مرفوض", "قيد الدراسة", "جديد", "لا يوجد", "مكتمل ولم يرسل"],
    "survey_status": ["تم المعاينه", "تم الرفع وجارى المراجعه", "لم يتم العمل عليه",
                      "تم المعاينة", "تم الرفع وجاري المراجعة", "لم يتم المعاينه"],
    "raw_status": ["تم الارسال جيوديسيا", "لم يتم الارسال جيوديسيا", "لم يتم العمل عليه",
                   "مرفوض جيوديسيا", "مقبول جيوديسيا", "مكتمل جيوديسيا"],
    "surveyor": [],
    "office": [],
}


def _ensure_lookup_values(db: Session) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS lookup_values (
            id SERIAL PRIMARY KEY,
            kind VARCHAR(40) NOT NULL,
            name VARCHAR(120) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            UNIQUE (kind, name)
        )
    """))
    db.commit()


def _seed_value_kind(db: Session, kind: str) -> None:
    """First-use seeding: canonical list plus every spelling the ledgers use."""
    have = {n for (n,) in db.query(LookupValue.name).filter(LookupValue.kind == kind).all()}
    wanted = list(dict.fromkeys(list(VALUE_SEED.get(kind, [])) + _distinct_ledger_values(db, kind)))
    for name in wanted:
        name = (name or "").strip()
        if name and name not in have:
            db.add(LookupValue(kind=kind, name=name, is_active=True))
            have.add(name)
    db.commit()


def _distinct_ledger_values(db: Session, kind: str) -> list:
    out = set()
    for model in (CadastralRequest, MudryiaRequest):
        for col in VALUE_COLUMNS[kind]:
            column = getattr(model, col)
            for (value,) in db.query(column).filter(column.isnot(None), column != "").distinct().all():
                out.add(value)
    return sorted(out)


def _value_out(o: LookupValue) -> dict:
    return {"id": o.id, "name": o.name, "is_active": o.is_active}


class ValueCreate(BaseModel):
    name: str


class ValueUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None


def _repoint_value_rows(db: Session, kind: str, mapping: dict) -> int:
    """Rewrite ledger text (old name -> new name) for rename/merge. Returns rows touched."""
    moved = 0
    for model in (CadastralRequest, MudryiaRequest):
        for col in VALUE_COLUMNS[kind]:
            column = getattr(model, col)
            for old, new in mapping.items():
                moved += db.query(model).filter(column == old).update(
                    {column: new}, synchronize_session=False)
    return moved


@router.get("/values/{kind}")
def list_values(
    kind: str,
    include_inactive: bool = False,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    if kind not in VALUE_KINDS:
        raise HTTPException(status_code=404, detail="Unknown value list")
    _ensure_lookup_values(db)
    if not db.query(LookupValue.id).filter(LookupValue.kind == kind).first():
        _seed_value_kind(db, kind)
    q = db.query(LookupValue).filter(LookupValue.kind == kind)
    if not include_inactive:
        q = q.filter(LookupValue.is_active == True)  # noqa: E712
    return [_value_out(o) for o in q.order_by(LookupValue.name.asc()).all()]


@router.post("/values/{kind}")
def create_value(
    kind: str,
    body: ValueCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
):
    if kind not in VALUE_KINDS:
        raise HTTPException(status_code=404, detail="Unknown value list")
    _ensure_lookup_values(db)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="الاسم مطلوب")
    if db.query(LookupValue).filter(LookupValue.kind == kind, LookupValue.name == name).first():
        raise HTTPException(status_code=400, detail="القيمة موجودة بالفعل")
    obj = LookupValue(kind=kind, name=name, is_active=True)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return _value_out(obj)


@router.patch("/values/{kind}/{item_id}")
def update_value(
    kind: str,
    item_id: int,
    body: ValueUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
):
    if kind not in VALUE_KINDS:
        raise HTTPException(status_code=404, detail="Unknown value list")
    _ensure_lookup_values(db)
    obj = db.query(LookupValue).filter(LookupValue.kind == kind, LookupValue.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Not found")
    moved = 0
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="الاسم مطلوب")
        if name != obj.name:
            if db.query(LookupValue).filter(
                    LookupValue.kind == kind, LookupValue.name == name,
                    LookupValue.id != obj.id).first():
                raise HTTPException(status_code=400, detail="القيمة موجودة بالفعل")
            moved = _repoint_value_rows(db, kind, {obj.name: name})
            obj.name = name
    if body.is_active is not None:
        obj.is_active = body.is_active
    db.commit()
    db.refresh(obj)
    out = _value_out(obj)
    out["rows_updated"] = moved
    return out


@router.post("/values/{kind}/{item_id}/disable")
def disable_value(
    kind: str,
    item_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
):
    if kind not in VALUE_KINDS:
        raise HTTPException(status_code=404, detail="Unknown value list")
    _ensure_lookup_values(db)
    obj = db.query(LookupValue).filter(LookupValue.kind == kind, LookupValue.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Not found")
    obj.is_active = False
    db.commit()
    return {"id": item_id, "is_active": False}


@router.post("/values/{kind}/{item_id}/enable")
def enable_value(
    kind: str,
    item_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
):
    if kind not in VALUE_KINDS:
        raise HTTPException(status_code=404, detail="Unknown value list")
    _ensure_lookup_values(db)
    obj = db.query(LookupValue).filter(LookupValue.kind == kind, LookupValue.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Not found")
    obj.is_active = True
    db.commit()
    return {"id": item_id, "is_active": True}


@router.delete("/values/{kind}/{item_id}")
def delete_value(
    kind: str,
    item_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
):
    """Permanently remove a disabled value. Refuses while any ledger row
    still uses the name — merge or rename first."""
    if kind not in VALUE_KINDS:
        raise HTTPException(status_code=404, detail="Unknown value list")
    _ensure_lookup_values(db)
    obj = db.query(LookupValue).filter(LookupValue.kind == kind, LookupValue.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Not found")
    if obj.is_active:
        raise HTTPException(status_code=400, detail="Disable the value first")
    used = 0
    for model in (CadastralRequest, MudryiaRequest):
        for col in VALUE_COLUMNS[kind]:
            used += db.query(model).filter(getattr(model, col) == obj.name).count()
    if used:
        raise HTTPException(
            status_code=400,
            detail=f"القيمة مستخدمة في {used} طلب — ادمجها أولاً",
        )
    db.delete(obj)
    db.commit()
    return {"deleted": item_id}


@router.post("/values/{kind}/merge")
def merge_values(
    kind: str,
    body: LookupMerge,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_admin),
):
    """Fold duplicate spellings into one target: re-point ledger rows, then
    disable the absorbed values."""
    if kind not in VALUE_KINDS:
        raise HTTPException(status_code=404, detail="Unknown value list")
    _ensure_lookup_values(db)
    sources = [i for i in (body.source_ids or [])
               if isinstance(i, int) and i > 0 and i != body.target_id]
    if not sources:
        raise HTTPException(status_code=400, detail="No source ids provided")
    target = db.query(LookupValue).filter(
        LookupValue.kind == kind, LookupValue.id == body.target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    names = [n for (n,) in db.query(LookupValue.name).filter(
        LookupValue.kind == kind, LookupValue.id.in_(sources)).all()]
    moved = _repoint_value_rows(db, kind, {n: target.name for n in names})
    db.query(LookupValue).filter(
        LookupValue.kind == kind, LookupValue.id.in_(sources)).update(
        {LookupValue.is_active: False}, synchronize_session=False)
    db.commit()
    return {"moved": moved, "target_id": target.id}
