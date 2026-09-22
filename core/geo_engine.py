import os
import glob
import shutil
import json
import geopandas as gpd
import pandas as pd


class GeoEngine:
    """Core engine for processing geospatial Shapefile folders into a unified GeoPackage database."""

    def __init__(self, base_dir, done_dir, problems_dir, db_path):
        self.base_dir = base_dir
        self.db_path = db_path
        self.rename_dir = done_dir          # successfully processed files go here
        self.problems_dir = problems_dir    # conflict records go here
        self.conflicts_file = os.path.join(problems_dir, "conflicts.json")

    def init_state(self):
        """Ensure output directories and conflicts file exist."""
        os.makedirs(self.rename_dir, exist_ok=True)
        os.makedirs(self.problems_dir, exist_ok=True)
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        if not os.path.exists(self.conflicts_file):
            with open(self.conflicts_file, "w", encoding="utf-8") as f:
                json.dump({}, f)

    def load_conflicts(self):
        self.init_state()
        with open(self.conflicts_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_conflicts(self, conflicts):
        with open(self.conflicts_file, "w", encoding="utf-8") as f:
            json.dump(conflicts, f, ensure_ascii=False, indent=4)

    def reset_system(self):
        """Delete database, conflicts, and processed files to start fresh."""
        for path in [self.db_path, self.db_path + "-wal", self.db_path + "-shm", self.conflicts_file]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        for folder in [self.rename_dir, self.problems_dir]:
            if os.path.exists(folder):
                try:
                    shutil.rmtree(folder)
                except OSError:
                    pass
        self.init_state()

    def rename_and_copy_shapefile(self, src_shp, dest_dir, new_name):
        """Copy all sidecar files (.shx, .dbf, .prj, etc.) alongside the .shp."""
        base_src = os.path.splitext(src_shp)[0]
        base_dest = os.path.join(dest_dir, new_name)
        os.makedirs(dest_dir, exist_ok=True)
        src_dir = os.path.dirname(src_shp)
        src_filename = os.path.basename(base_src)
        for ext_file in os.listdir(src_dir):
            if ext_file.startswith(src_filename + ".") and not ext_file.endswith(".lock"):
                ext = os.path.splitext(ext_file)[1]
                shutil.copy2(os.path.join(src_dir, ext_file), base_dest + ext)

    def append_to_db(self, gdf, layer_name):
        """Append a GeoDataFrame to the GeoPackage under the given layer name."""
        if gdf.empty:
            return
        mode = "a" if os.path.exists(self.db_path) else "w"
        try:
            standard_cols = ["Req_Number", "Owner_Name", "Layer_Type", "Area_SQM", "Area_Feddan", "X", "Y"]
            for col in standard_cols:
                if col not in gdf.columns:
                    gdf[col] = "-"
            keep_cols = ["geometry"] + standard_cols
            gdf = gdf[[c for c in keep_cols if c in gdf.columns]]
            for col in gdf.columns:
                if col != "geometry":
                    gdf[col] = gdf[col].astype(str)
            gdf.to_file(self.db_path, layer=layer_name, driver="GPKG", mode=mode)
        except Exception:
            pass

    def process_valid_folder(self, folder_path, poly_files, point_files):
        """Process a validated folder: calculate areas, split layers, append to DB, copy files."""
        folder_name = os.path.basename(folder_path)
        if " - " in folder_name:
            req_num = folder_name.split(" - ", 1)[0].strip()
            owner_name = folder_name.split(" - ", 1)[1].strip()
        else:
            req_num = folder_name.strip()
            owner_name = "Unknown"

        dest_dir = os.path.join(self.rename_dir, folder_name)

        # --- Process Polygons ---
        if poly_files:
            gdfs = []
            for f in poly_files:
                try:
                    g = gpd.read_file(f)
                    if not g.empty:
                        gdfs.append(g)
                except Exception:
                    pass

            if gdfs:
                poly_gdf = pd.concat(gdfs, ignore_index=True)

                # Area calculation
                if poly_gdf.crs and poly_gdf.crs.is_geographic:
                    poly_gdf["Area_SQM"] = poly_gdf.to_crs(epsg=3857).geometry.area.round(2)
                else:
                    poly_gdf["Area_SQM"] = poly_gdf.geometry.area.round(2)

                poly_gdf["Area_Feddan"] = (poly_gdf["Area_SQM"] / 4200.83).round(4)

                # Dedup by geometry
                poly_gdf["geom_wkb"] = poly_gdf.geometry.to_wkb()
                poly_gdf = poly_gdf.drop_duplicates(subset=["geom_wkb"])
                poly_gdf = poly_gdf.drop(columns=["geom_wkb"])

                # Sort: largest first = Land, rest = Eshghalat
                poly_gdf = poly_gdf.sort_values(by="Area_SQM", ascending=False)

                land_gdf = poly_gdf.iloc[[0]].copy()
                land_gdf["Layer_Type"] = "Land"
                eshghalat_gdf = poly_gdf.iloc[1:].copy()
                if not eshghalat_gdf.empty:
                    eshghalat_gdf["Layer_Type"] = "Eshghalat"

                for gdf in [land_gdf, eshghalat_gdf]:
                    if gdf.empty:
                        continue
                    gdf["Req_Number"] = req_num
                    gdf["Owner_Name"] = owner_name
                    try:
                        gdf["X"] = gdf.geometry.centroid.x
                        gdf["Y"] = gdf.geometry.centroid.y
                    except Exception:
                        gdf["X"] = "-"
                        gdf["Y"] = "-"
                    layer = gdf.iloc[0]["Layer_Type"]
                    self.append_to_db(gdf, layer)

                for idx, p_file in enumerate(poly_files):
                    self.rename_and_copy_shapefile(p_file, dest_dir, f"{req_num}_poly_{idx+1}")

        # --- Process Points ---
        if point_files:
            gdfs = []
            for f in point_files:
                try:
                    g = gpd.read_file(f)
                    if not g.empty:
                        gdfs.append(g)
                except Exception:
                    pass

            if gdfs:
                point_gdf = pd.concat(gdfs, ignore_index=True)
                try:
                    point_gdf["X"] = point_gdf.geometry.centroid.x
                    point_gdf["Y"] = point_gdf.geometry.centroid.y
                except Exception:
                    point_gdf["X"] = "-"
                    point_gdf["Y"] = "-"

                point_gdf["Req_Number"] = req_num
                point_gdf["Owner_Name"] = owner_name
                point_gdf["Layer_Type"] = "Point"
                self.append_to_db(point_gdf, "Point")

                for idx, p_file in enumerate(point_files):
                    self.rename_and_copy_shapefile(p_file, dest_dir, f"{req_num}_point_{idx+1}")
