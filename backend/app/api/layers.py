from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.api import deps
import json

router = APIRouter()

VALID_LAYERS = ["lands", "eshghalat", "points"]

@router.get("/{layer_name}/geojson")
def get_layer_geojson(
    layer_name: str, 
    bbox: str | None = None,
    db: Session = Depends(deps.get_db),
    current_user = Depends(deps.get_current_user)
):
    if layer_name not in VALID_LAYERS:
        raise HTTPException(status_code=404, detail="Invalid layer name")
    
    bbox_filter = ""
    params = {}
    if bbox:
        try:
            minx, miny, maxx, maxy = map(float, bbox.split(","))
            if minx > maxx or miny > maxy:
                raise ValueError("min must be <= max")
            bbox_filter = "WHERE ST_Intersects(geometry, ST_Transform(ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326), 32636))"
            params = {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid bbox format. Expected minx,miny,maxx,maxy")

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
          FROM (SELECT * FROM {layer_name} {bbox_filter}) inputs
        ) features;
    ''')
    
    try:
        result = db.execute(query, params).scalar()
        if not result:
            return {"type": "FeatureCollection", "features": []}
        if isinstance(result, str):
            return json.loads(result)
        return result
    except Exception as e:
        print(f"Error fetching {layer_name}: {str(e)}")
        raise HTTPException(status_code=500, detail="Database query failed")


@router.get("/{layer_name}/attributes")
def get_layer_attributes(
    layer_name: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, gt=0),
    sort_by: str | None = "id",
    order: str | None = "asc",
    q: str | None = None,
    db: Session = Depends(deps.get_db),
    current_user = Depends(deps.get_current_user)
):
    if layer_name not in VALID_LAYERS:
        raise HTTPException(status_code=404, detail="Invalid layer name")

    # Anti-SQL Injection for sorting
    allowed_sort_columns = ["id", "req_number", "owner_name", "area_sqm", "area_feddan", "created_at"]
    if sort_by not in allowed_sort_columns:
        raise HTTPException(status_code=400, detail="Invalid sort column")
    if order not in ["asc", "desc"]:
        raise HTTPException(status_code=400, detail="Invalid order parameter")

    search_filter = ""
    params = {}
    if q:
        search_filter = 'WHERE "Req_Number" ILIKE :q OR "Owner_Name" ILIKE :q'
        params["q"] = f"%{q}%"

    count_query = text(f'SELECT COUNT(*) FROM {layer_name} {search_filter}')
    total_count = db.execute(count_query, params).scalar()
    
    offset = (page - 1) * limit
    if offset >= total_count and total_count > 0:
        return {"items": [], "total": total_count, "page": page, "pages": (total_count + limit - 1) // limit}
    
    # We map sort_by to the actual columns
    sort_mapping = {
        "id": "id",
        "req_number": '"Req_Number"',
        "owner_name": '"Owner_Name"',
        "area_sqm": '"Area_SQM"',
        "area_feddan": '"Area_Feddan"',
        "created_at": "created_at"
    }
    db_sort_col = sort_mapping.get(sort_by, "id")

    data_query = text(f'''
        SELECT id, "Req_Number" as req_number, "Owner_Name" as owner_name, "Layer_Type" as layer_type, 
               "Area_SQM" as area_sqm, "Area_Feddan" as area_feddan, "X" as x, "Y" as y, created_at
        FROM {layer_name}
        {search_filter}
        ORDER BY {db_sort_col} {order.upper()}
        LIMIT :limit OFFSET :offset
    ''')
    params["limit"] = limit
    params["offset"] = offset

    rows = db.execute(data_query, params).fetchall()
    items = [dict(row._mapping) for row in rows]
    
    pages = (total_count + limit - 1) // limit if total_count > 0 else 0

    return {
        "items": items,
        "total": total_count,
        "page": page,
        "pages": pages
    }


@router.get("/{layer_name}/search")
def search_layer(layer_name: str, q: str = Query(..., min_length=2),
                 db: Session = Depends(deps.get_db),
                 current_user = Depends(deps.get_current_user)):
    # Accept any registered public spatial layer (map_layers table), not just a
    # hard-coded list, so new layers (e.g. mudryia) are searchable out of the box.
    reg = db.execute(text(
        "SELECT 1 FROM map_layers WHERE table_name = :t"
    ), {"t": layer_name}).first()
    if not reg:
        raise HTTPException(status_code=404, detail="Invalid layer name")

    # Some tables (e.g. regoin) do not carry Req_Number / Owner_Name text
    # columns; they simply have nothing to match on.
    col_rows = db.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = :t "
        "AND column_name IN ('Req_Number', 'Owner_Name')"
    ), {"t": layer_name}).fetchall()
    if not col_rows:
        return {"type": "FeatureCollection", "features": []}

    # Capped so one broad query can never flood the browser
    search_query = text(f'''
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
              WHERE "Req_Number" ILIKE :q OR "Owner_Name" ILIKE :q
              LIMIT 100
           ) inputs
        ) features;
    ''')
    
    try:
        result = db.execute(search_query, {"q": f"%{q}%"}).scalar()
        if not result:
            return {"type": "FeatureCollection", "features": []}
        if isinstance(result, str):
            return json.loads(result)
        return result
    except Exception as e:
        print(f"Error searching {layer_name}: {str(e)}")
        raise HTTPException(status_code=500, detail="Database query failed")
