import os
import glob
import shutil
import json
import geopandas as gpd
import pandas as pd
from sqlalchemy import create_engine, text

# Configuration
DB_URL = "postgresql://admin:admin123@localhost:5432/geoportal"
BASE_DIR = r"D:\Systems\MapViewer\input_folders"
DONE_DIR = r"D:\Systems\MapViewer\processed"
PROBLEMS_DIR = r"D:\Systems\MapViewer\conflicts"
CONFLICTS_FILE = os.path.join(PROBLEMS_DIR, "conflicts.json")

def init_dirs():
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(DONE_DIR, exist_ok=True)
    os.makedirs(PROBLEMS_DIR, exist_ok=True)

def append_to_db(engine, gdf, layer_name, req_num, owner_name):
    # Ensure standard schema and CRS
    if gdf.crs is None or gdf.crs.to_epsg() != 32636:
        gdf = gdf.to_crs(epsg=32636)

    with engine.begin() as conn:
        for idx, row in gdf.iterrows():
            geom_wkt = row.geometry.wkt
            
            area_sqm = row.get("Area_SQM", 0)
            area_feddan = row.get("Area_Feddan", 0)
            x, y = 0, 0
            if row.geometry.centroid:
                x, y = row.geometry.centroid.x, row.geometry.centroid.y
                
            query = text(f"""
                INSERT INTO {layer_name} 
                (req_number, owner_name, layer_type, area_sqm, area_feddan, x, y, geom)
                VALUES 
                (:req, :owner, :ltype, :area_sqm, :area_feddan, :x, :y, ST_GeomFromText(:geom, 32636))
            """)
            conn.execute(query, {
                "req": req_num,
                "owner": owner_name,
                "ltype": layer_name.capitalize(),
                "area_sqm": area_sqm if not pd.isna(area_sqm) else None,
                "area_feddan": area_feddan if not pd.isna(area_feddan) else None,
                "x": x,
                "y": y,
                "geom": geom_wkt
            })

def rename_and_copy(src_shp, dest_dir, new_name):
    base_src = os.path.splitext(src_shp)[0]
    base_dest = os.path.join(dest_dir, new_name)
    os.makedirs(dest_dir, exist_ok=True)
    src_dir = os.path.dirname(src_shp)
    src_filename = os.path.basename(base_src)
    for ext_file in os.listdir(src_dir):
        if ext_file.startswith(src_filename + ".") and not ext_file.endswith(".lock"):
            ext = os.path.splitext(ext_file)[1]
            shutil.copy2(os.path.join(src_dir, ext_file), base_dest + ext)

def run_scan():
    print(f"--- Starting Batch Scan ---")
    print(f"Scanning directory: {BASE_DIR}")
    
    init_dirs()
    engine = create_engine(DB_URL)
    
    if os.path.exists(CONFLICTS_FILE):
        with open(CONFLICTS_FILE, "r") as f:
            conflicts = json.load(f)
    else:
        conflicts = {}

    folders = [f.path for f in os.scandir(BASE_DIR) if f.is_dir()]
    if not folders:
        print("No sub-folders found to process.")
        return

    processed_count = 0
    new_conflicts = 0

    for i, folder in enumerate(folders):
        folder_name = os.path.basename(folder)
        print(f"[{i+1}/{len(folders)}] Processing folder: {folder_name}")

        if folder_name in conflicts:
            print("  -> Skipped (already in conflicts)")
            continue
        if os.path.exists(os.path.join(DONE_DIR, folder_name)):
            print("  -> Skipped (already processed)")
            continue

        shp_files = glob.glob(os.path.join(folder, "*.shp"))
        poly_files, point_files, corrupt = [], [], 0

        for shp in shp_files:
            try:
                gdf = gpd.read_file(shp)
                if gdf.empty:
                    continue
                geom_type = gdf.geometry.iloc[0].geom_type
                if "Polygon" in geom_type:
                    poly_files.append(shp)
                elif "Point" in geom_type:
                    point_files.append(shp)
            except Exception as e:
                corrupt += 1

        reasons = []
        if corrupt > 0:
            reasons.append("Corrupted shapefile(s)")
        elif not poly_files and not point_files:
            reasons.append("Empty folder (no valid Polygons or Points)")
        elif not poly_files:
            reasons.append("Missing Polygon file (Land/Eshghalat)")

        if reasons:
            conflicts[folder_name] = {
                "folder_path": folder,
                "reason": " | ".join(reasons),
            }
            new_conflicts += 1
            print(f"  -> Conflict: {conflicts[folder_name]['reason']}")
        else:
            # Parse ReqNum and Owner
            if " - " in folder_name:
                req_num = folder_name.split(" - ", 1)[0].strip()
                owner_name = folder_name.split(" - ", 1)[1].strip()
            else:
                req_num = folder_name.strip()
                owner_name = "Unknown"

            dest_dir = os.path.join(DONE_DIR, folder_name)

            try:
                # Process Polygons
                if poly_files:
                    gdfs = [gpd.read_file(f) for f in poly_files if not gpd.read_file(f).empty]
                    if gdfs:
                        poly_gdf = pd.concat(gdfs, ignore_index=True)
                        if poly_gdf.crs and poly_gdf.crs.is_geographic:
                            poly_gdf["Area_SQM"] = poly_gdf.to_crs(epsg=3857).geometry.area.round(2)
                        else:
                            poly_gdf["Area_SQM"] = poly_gdf.geometry.area.round(2)
                        
                        poly_gdf["Area_Feddan"] = (poly_gdf["Area_SQM"] / 4200.83).round(4)
                        
                        # Dedup and sort
                        poly_gdf["geom_wkb"] = poly_gdf.geometry.to_wkb()
                        poly_gdf = poly_gdf.drop_duplicates(subset=["geom_wkb"]).drop(columns=["geom_wkb"])
                        poly_gdf = poly_gdf.sort_values(by="Area_SQM", ascending=False)
                        
                        land_gdf = poly_gdf.iloc[[0]].copy()
                        eshghalat_gdf = poly_gdf.iloc[1:].copy()
                        
                        if not land_gdf.empty:
                            append_to_db(engine, land_gdf, "land_parcels", req_num, owner_name)
                        if not eshghalat_gdf.empty:
                            append_to_db(engine, eshghalat_gdf, "eshghalat", req_num, owner_name)
                            
                        for idx, p_file in enumerate(poly_files):
                            rename_and_copy(p_file, dest_dir, f"{req_num}_poly_{idx+1}")

                # Process Points
                if point_files:
                    gdfs = [gpd.read_file(f) for f in point_files if not gpd.read_file(f).empty]
                    if gdfs:
                        point_gdf = pd.concat(gdfs, ignore_index=True)
                        append_to_db(engine, point_gdf, "points", req_num, owner_name)
                        for idx, p_file in enumerate(point_files):
                            rename_and_copy(p_file, dest_dir, f"{req_num}_point_{idx+1}")

                processed_count += 1
                print(f"  -> Successfully imported into DB and moved to {DONE_DIR}")
            except Exception as e:
                conflicts[folder_name] = {
                    "folder_path": folder,
                    "reason": f"Database insertion error: {str(e)}",
                }
                new_conflicts += 1
                print(f"  -> DB Error: {str(e)}")

    with open(CONFLICTS_FILE, "w") as f:
        json.dump(conflicts, f, indent=4)
        
    print(f"\n--- Scan Complete ---")
    print(f"Successfully processed: {processed_count} folders")
    print(f"New conflicts found: {new_conflicts}")
    print(f"Check {CONFLICTS_FILE} for details.")

if __name__ == '__main__':
    run_scan()
