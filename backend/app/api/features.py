from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.api import deps
import json

router = APIRouter()

VALID_LAYERS = ["lands", "eshghalat", "points"]

@router.get("/{layer_name}/{feature_id}")
def get_feature(layer_name: str, feature_id: int, db: Session = Depends(deps.get_db),
                current_user = Depends(deps.get_current_user)):
    if layer_name not in VALID_LAYERS:
        raise HTTPException(status_code=404, detail="Invalid layer name")
        
    query = text(f'''
        SELECT id, "Req_Number" AS req_number, "Owner_Name" AS owner_name,
               "Layer_Type" AS layer_type, "Area_SQM" AS area_sqm,
               "Area_Feddan" AS area_feddan, "X" AS x, "Y" AS y,
               created_by, created_at,
               ST_AsGeoJSON(ST_Transform(geometry, 4326))::json AS geojson
        FROM {layer_name} WHERE id = :id
    ''')
    row = db.execute(query, {"id": feature_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Feature not found")

    attrs = dict(row._mapping)
    if attrs.get("created_at") is not None:
        try:
            attrs["created_at"] = attrs["created_at"].isoformat()
        except Exception:
            attrs["created_at"] = str(attrs["created_at"])
         
    audit_query = text(f'''
        SELECT action, old_values, new_values, username, timestamp 
        FROM audit_trail 
        WHERE table_name = :layer AND record_id = :id
        ORDER BY timestamp DESC
    ''')
    audits = db.execute(audit_query, {"layer": layer_name, "id": feature_id}).fetchall()
    
    return {
        "attributes": attrs,
        "history": [dict(a._mapping) for a in audits]
    }
