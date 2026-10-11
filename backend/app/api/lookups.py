"""Admin-managed lookup endpoints (governorates / centers / villages / area_units).

Values are added, renamed, or disabled — never hard-deleted once used, so
referencing requests stay intact. Governed by the admin role only.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api import deps
from app.db.models import (
    AreaUnit, CadastralRequest, Center, Governorate, MudryiaRequest, User, Village,
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