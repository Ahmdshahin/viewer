from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.api import deps

router = APIRouter()

@router.get("")
def search(q: str = Query(..., min_length=2), db: Session = Depends(deps.get_db),
           current_user = Depends(deps.get_current_user)):
    # Prevent completely empty searches
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
        
    query_str = f"%{q.strip()}%"
    
    # We query lands, eshghalat, and points
    # Return bounding box so frontend can zoom to feature
    
    sql = text("""
        WITH search_results AS (
            SELECT 
                id, 
                'land' as layer,
                "Req_Number" as req_number, 
                "Owner_Name" as owner_name, 
                "Area_SQM" as area_sqm,
                ST_AsGeoJSON(ST_Transform(geometry, 4326))::json as geojson,
                Box2D(ST_Transform(geometry, 4326))::text as bbox_wkt
            FROM lands 
            WHERE "Req_Number" ILIKE :q OR "Owner_Name" ILIKE :q
            UNION ALL
            SELECT 
                id, 
                'eshghalat' as layer,
                "Req_Number" as req_number, 
                "Owner_Name" as owner_name, 
                "Area_SQM" as area_sqm,
                ST_AsGeoJSON(ST_Transform(geometry, 4326))::json as geojson,
                Box2D(ST_Transform(geometry, 4326))::text as bbox_wkt
            FROM eshghalat
            WHERE "Req_Number" ILIKE :q OR "Owner_Name" ILIKE :q
            UNION ALL
            SELECT 
                id, 
                'point' as layer,
                "Req_Number" as req_number, 
                "Owner_Name" as owner_name, 
                "Area_SQM" as area_sqm,
                ST_AsGeoJSON(ST_Transform(geometry, 4326))::json as geojson,
                Box2D(ST_Transform(geometry, 4326))::text as bbox_wkt
            FROM points
            WHERE "Req_Number" ILIKE :q OR "Owner_Name" ILIKE :q
        )
        SELECT * FROM search_results LIMIT 100;
    """)
    
    rows = db.execute(sql, {"q": query_str}).fetchall()
    
    results = []
    for row in rows:
        results.append({
            "id": row.id,
            "layer": row.layer,
            "req_number": row.req_number,
            "owner_name": row.owner_name,
            "area_sqm": row.area_sqm,
            "geojson": row.geojson,
            "bbox": row.bbox_wkt
        })
        
    return {"results": results}
