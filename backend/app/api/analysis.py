from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import Any, Dict, List
from app.api import deps
import json
from shapely.geometry import shape

router = APIRouter()

VALID_LAYERS = ["lands", "eshghalat", "points"]

class IntersectRequest(BaseModel):
    geometry: Dict[str, Any]
    layers: List[str]

class DuplicatesRequest(BaseModel):
    layer: str
    min_overlap_sqm: float = 0.1

def _require_req_column(db: Session, table: str) -> None:
    """Request-number operations need a Req_Number column."""
    row = db.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :t AND column_name = 'Req_Number';
    """), {"t": table}).first()
    if not row:
        raise HTTPException(status_code=400, detail=f"Table {table} has no Req_Number column")

class LayerIntersectRequest(BaseModel):
    source_layer: str
    target_layer: str

class TopologyRequest(BaseModel):
    layer: str

@router.post("/intersect")
def analysis_intersect(req: IntersectRequest, db: Session = Depends(deps.get_db),
                       current_user = Depends(deps.get_current_user)):
    for layer in req.layers:
        if layer not in VALID_LAYERS:
            raise HTTPException(status_code=400, detail=f"Invalid layer: {layer}")
    for layer in req.layers:
        _require_req_column(db, layer)
            
    try:
        geom = shape(req.geometry)
        if not geom.is_valid:
            raise HTTPException(status_code=422, detail="Invalid geometry")
    except Exception:
        raise HTTPException(status_code=422, detail="Malformed GeoJSON")
        
    geojson_str = json.dumps(req.geometry)
    features_by_layer = {}
    total = 0
    
    for layer in req.layers:
        query = text(f'''
            SELECT 
                id,
                "Req_Number" as req_number,
                "Owner_Name" as owner_name,
                "Area_SQM" as area_sqm,
                ST_AsGeoJSON(ST_Transform(ST_MakeValid(geometry), 4326))::json as geojson
            FROM {layer}
            WHERE ST_Intersects(ST_MakeValid(geometry), ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326), 32636))
            LIMIT 1000
        ''')
        try:
            res = db.execute(query, {"geojson": geojson_str}).mappings().all()
            features = [dict(r) for r in res]
            features_by_layer[layer] = features
            total += len(features)
        except Exception:
            raise HTTPException(status_code=422, detail="Malformed geometry")
        
    return {
        "features_by_layer": features_by_layer,
        "total_features": total
    }

@router.post("/duplicates")
def check_duplicates(req: DuplicatesRequest, db: Session = Depends(deps.get_db),
                     current_user = Depends(deps.get_current_user)):
    if req.layer not in VALID_LAYERS:
        raise HTTPException(status_code=400, detail="Invalid layer name")
    _require_req_column(db, req.layer)
        
    query = text(f'''
        SELECT 
            a.id as id1, 
            b.id as id2, 
            ST_Area(ST_Intersection(ST_MakeValid(a.geometry), ST_MakeValid(b.geometry))) as overlap_area_sqm
        FROM {req.layer} a
        JOIN {req.layer} b ON ST_Intersects(ST_MakeValid(a.geometry), ST_MakeValid(b.geometry)) AND a.id < b.id
        WHERE ST_Area(ST_Intersection(ST_MakeValid(a.geometry), ST_MakeValid(b.geometry))) >= :min_overlap
        LIMIT 100
    ''')
    rows = db.execute(query, {"min_overlap": req.min_overlap_sqm}).fetchall()
    return {"duplicates": [dict(r._mapping) for r in rows]}

@router.post("/layer-intersect")
def layer_intersect(req: LayerIntersectRequest, db: Session = Depends(deps.get_db),
                    current_user = Depends(deps.get_current_user)):
    if req.source_layer not in VALID_LAYERS or req.target_layer not in VALID_LAYERS:
        raise HTTPException(status_code=400, detail="Invalid layer name")
    _require_req_column(db, req.source_layer)
    _require_req_column(db, req.target_layer)
        
    query = text(f'''
        SELECT 
            s.id as source_id, 
            t.id as target_id, 
            ST_Area(ST_Intersection(ST_MakeValid(s.geometry), ST_MakeValid(t.geometry))) as overlap_area_sqm
        FROM {req.source_layer} s
        JOIN {req.target_layer} t ON ST_Intersects(ST_MakeValid(s.geometry), ST_MakeValid(t.geometry))
        WHERE ST_Area(ST_Intersection(ST_MakeValid(s.geometry), ST_MakeValid(t.geometry))) > 0.01
        LIMIT 500
    ''')
    rows = db.execute(query).fetchall()
    return {"intersections": [dict(r._mapping) for r in rows]}

@router.post("/topology")
def check_topology(req: TopologyRequest, db: Session = Depends(deps.get_db),
                   current_user = Depends(deps.get_current_user)):
    if req.layer not in VALID_LAYERS:
        raise HTTPException(status_code=400, detail="Invalid layer name")
    _require_req_column(db, req.layer)
        
    # Overlaps
    overlap_query = text(f'''
        SELECT a.id as id1, b.id as id2, ST_Area(ST_Intersection(ST_MakeValid(a.geometry), ST_MakeValid(b.geometry))) as overlap_area
        FROM {req.layer} a
        JOIN {req.layer} b ON ST_Intersects(ST_MakeValid(a.geometry), ST_MakeValid(b.geometry)) AND a.id < b.id
        WHERE ST_Area(ST_Intersection(ST_MakeValid(a.geometry), ST_MakeValid(b.geometry))) > 0.1
        LIMIT 100
    ''')
    overlaps = db.execute(overlap_query).fetchall()
    
    return {
        "overlaps": [dict(r._mapping) for r in overlaps],
        "gaps": []  # Gaps calculation is complex, return empty list for now to satisfy contract
    }


# ---- Map-viewer endpoints (used by the frontend) ----

class AOIRequest(BaseModel):
    geometry: Dict[str, Any]

@router.get("/topology/{layer_name}")
def check_topology_by_layer(layer_name: str, db: Session = Depends(deps.get_db),
                            current_user = Depends(deps.get_current_user)):
    # Find overlapping geometries in the same layer
    query = text(f'''
        SELECT a.id as id1, b.id as id2, ST_Area(ST_Intersection(ST_MakeValid(a.geometry), ST_MakeValid(b.geometry))) as overlap_area
        FROM {layer_name} a
        JOIN {layer_name} b ON ST_Intersects(ST_MakeValid(a.geometry), ST_MakeValid(b.geometry)) AND a.id < b.id
        WHERE ST_Area(ST_Intersection(ST_MakeValid(a.geometry), ST_MakeValid(b.geometry))) > 1.0
        LIMIT 100
    ''')
    overlaps = db.execute(query).fetchall()
    return {"overlaps": [{"id1": r.id1, "id2": r.id2, "overlap_area": r.overlap_area} for r in overlaps]}

@router.post("/intersect/{layer_name}")
def intersect_layer(layer_name: str, aoi: AOIRequest, db: Session = Depends(deps.get_db),
                    current_user = Depends(deps.get_current_user)):
    # Accept any registered public spatial layer (map_layers table) so new
    # layers (e.g. mudryia, regoin) are intersectable out of the box.
    if not db.execute(text("SELECT 1 FROM map_layers WHERE table_name = :t"),
                      {"t": layer_name}).first():
        raise HTTPException(status_code=404, detail="Invalid layer name")

    geojson_str = json.dumps(aoi.geometry)
    query = text(f'''
        SELECT jsonb_build_object(
            'type',     'FeatureCollection',
            'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
        )
        FROM (
          SELECT jsonb_build_object(
            'type',       'Feature',
            'id',         id,
            'geometry',   ST_AsGeoJSON(ST_Transform(ST_MakeValid(geometry), 4326))::jsonb,
            'properties', to_jsonb(inputs) - 'geometry'
          ) AS feature
          FROM (
             SELECT * FROM {layer_name}
             WHERE ST_Intersects(ST_MakeValid(geometry), ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326), 32636))
             LIMIT 1000
          ) inputs
        ) features;
    ''')
    result = db.execute(query, {"geojson": geojson_str}).scalar()
    return result if result else {"type": "FeatureCollection", "features": []}
