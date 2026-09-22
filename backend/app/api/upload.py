from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from app.api import deps
import os
import shutil
import tempfile
import json
import zipfile
import geopandas as gpd

router = APIRouter()

@router.post("/process")
async def process_shapefile(
    file: UploadFile = File(...),
    layer_name: str = Form(...),
    current_user = Depends(deps.get_current_user)
):
    """Preview-only upload: parse a zipped shapefile and return it as GeoJSON
    for map display. Nothing is written to any database."""
    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Must be a .zip file containing a shapefile")
    
    if layer_name not in ['land', 'eshghalat', 'point']:
        raise HTTPException(status_code=400, detail="Invalid layer name")

    # Create temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "upload.zip")
        with open(zip_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        if size_mb > 100:
            raise HTTPException(status_code=413, detail=f"ZIP too large ({size_mb:.1f} MB, max 100 MB)")

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(tmpdir)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid zip file")

        # Find .shp file
        shp_files = [f for f in os.listdir(tmpdir) if f.endswith('.shp')]
        if not shp_files:
            raise HTTPException(status_code=400, detail="No .shp file found in zip")
            
        shp_path = os.path.join(tmpdir, shp_files[0])
        
        try:
            gdf = gpd.read_file(shp_path)
            if gdf.empty:
                raise HTTPException(status_code=400, detail="Shapefile contains no features")
            if gdf.crs is None:
                # Unknown CRS: meter-scale numbers mean local UTM, else lon/lat
                bounds = gdf.total_bounds
                gdf = gdf.set_crs(epsg=32636 if max(abs(bounds[2]), abs(bounds[3])) > 180 else 4326)
            gdf_4326 = gdf.to_crs(epsg=4326)
            
            features = json.loads(gdf_4326.to_json())
            count = len(features.get("features", []))
            
            return {
                "message": f"Loaded {count} features for viewing (not saved to database)",
                "count": count,
                "geojson": features
            }
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error processing shapefile: {str(e)}")
