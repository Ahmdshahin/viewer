import os
import glob
import shutil
import json
import geopandas as gpd
from shapely import wkb
import warnings

# Suppress PyPROJ and GeoPandas warnings for cleaner output
warnings.filterwarnings('ignore')

class GeospatialDataPipeline:
    def __init__(self, input_dir, done_dir, conflicts_file, output_gpkg, progress_callback=None):
        self.input_dir = input_dir
        self.done_dir = done_dir
        self.conflicts_file = conflicts_file
        self.output_gpkg = output_gpkg
        self.progress_callback = progress_callback
        self.conflicts = []
        self.existing_req_numbers = set()

        # Ensure directories exist
        os.makedirs(self.done_dir, exist_ok=True)
        # Create an empty conflicts file if it doesn't exist
        if not os.path.exists(self.conflicts_file):
            with open(self.conflicts_file, 'w') as f:
                json.dump([], f)

    def log_conflict(self, folder_name, reason):
        conflict = {"folder": folder_name, "reason": reason, "source": self.input_dir}
        self.conflicts.append(conflict)
        pass # print(f"[CONFLICT] {folder_name}: {reason}")
        
    def save_conflicts(self):
        existing = []
        if os.path.exists(self.conflicts_file):
            try:
                with open(self.conflicts_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for k, v in data.items():
                            if isinstance(v, dict):
                                existing.append({"folder": k, "reason": v.get("reason", "Unknown")})
                            else:
                                existing.append({"folder": k, "reason": str(v)})
                    elif isinstance(data, list):
                        existing.extend(data)
                    else:
                        raise ValueError("conflicts file is not a list")
            except Exception:
                # Never silently overwrite a log we failed to read: back it up,
                # then proceed with only the new entries.
                try:
                    shutil.copy2(self.conflicts_file, self.conflicts_file + ".corrupt.bak")
                except Exception:
                    pass
        
        existing.extend(self.conflicts)

        # One row per (source, folder): the latest run's reason wins, so a
        # folder never piles up multiple rows across runs and the conflict
        # count can never exceed the number of folders. The source keeps
        # conflicts of different input directories apart.
        latest = {}
        order = []
        for entry in existing:
            key = (entry.get("source"), entry.get("folder"))
            if key not in latest:
                order.append(key)
            else:
                order.remove(key)
                order.append(key)
            latest[key] = entry
        deduped = [latest[k] for k in order]

        with open(self.conflicts_file, 'w', encoding='utf-8') as f:
            json.dump(deduped, f, ensure_ascii=False, indent=4)

    def load_existing_req_numbers(self):
        """Return the set of Req_Number values already stored in the output GPKG.

        Used to detect folders whose request was processed in a previous run.
        Fail-open: any read error yields an empty set (process as before).
        """
        existing = set()
        if not os.path.exists(self.output_gpkg):
            return existing
        try:
            import pyogrio
            try:
                info = pyogrio.list_layers(self.output_gpkg)
                # pyogrio>=0.5 returns a DataFrame, older versions a list of tuples
                if hasattr(info, "columns") and "name" in info.columns:
                    layers = info["name"].tolist()
                else:
                    layers = [row[0] for row in info]
            except Exception:
                layers = ["Land", "Eshghalat", "Point"]
            for layer in layers:
                try:
                    gdf = gpd.read_file(self.output_gpkg, layer=layer, columns=["Req_Number"], ignore_geometry=True, engine="pyogrio")
                except Exception:
                    try:
                        gdf = gpd.read_file(self.output_gpkg, layer=layer, engine="pyogrio")
                    except Exception:
                        continue
                if gdf is None or "Req_Number" not in gdf.columns:
                    continue
                for v in gdf["Req_Number"].dropna().astype(str).str.strip():
                    if v:
                        existing.add(v)
        except Exception:
            pass
        return existing

    def _ensure_32636(self, gdf):
        """Reproject a frame to the project CRS (EPSG:32636).

        Missing CRS is inferred from coordinate magnitude (meters vs degrees)
        so mixed-CRS folders can still be merged instead of crashing concat.
        """
        if gdf.crs is None:
            try:
                bounds = gdf.total_bounds
                meter_scale = max(abs(bounds[2]), abs(bounds[3])) > 180
            except Exception:
                meter_scale = True
            gdf = gdf.set_crs(epsg=32636 if meter_scale else 4326, allow_override=True)
        try:
            epsg = gdf.crs.to_epsg()
        except Exception:
            epsg = None
        if epsg != 32636:
            gdf = gdf.to_crs(epsg=32636)
        return gdf

    def process_all(self):
        folders = [
            f for f in os.listdir(self.input_dir)
            if os.path.isdir(os.path.join(self.input_dir, f))
        ]
        total = len(folders)

        # New input directory = new task that appends to the DB.
        # Load request numbers already stored so they are never
        # imported twice (repeats are reported as conflicts instead).
        self.existing_req_numbers = self.load_existing_req_numbers()

        if self.progress_callback:
            self.progress_callback(0, total, "Starting...")

        for i, folder_name in enumerate(folders):
            folder_path = os.path.join(self.input_dir, folder_name)
            try:
                self.process_folder(folder_name, folder_path)
            except Exception as e:
                # One bad folder must never abort the whole run
                self.log_conflict(folder_name, f"Processing failed: {e!r}")
            if self.progress_callback:
                self.progress_callback(i + 1, total, folder_name)

        self.save_conflicts()

        if self.progress_callback:
            self.progress_callback(total, total, "Finished")

    def process_folder(self, folder_name, folder_path):
        # 2. Metadata Extraction Rules
        if ' - ' in folder_name:
            parts = folder_name.split(' - ', 1)
            req_number = parts[0].strip()
            owner_name = parts[1].strip()
        else:
            req_number = folder_name.strip()
            owner_name = "Unknown"

        # Skip requests already imported by a previous run (or earlier in
        # this run) — report to the user as a conflict instead of duplicating.
        # NOTE: reason text is stable (no embedded request number) so the same
        # folder never accumulates multiple rows across runs.
        if req_number in self.existing_req_numbers:
            self.log_conflict(folder_name, "Duplicate Request Number: already exists in the database from a previous process. Skipped to avoid duplication.")
            return

        # Find all shapefiles
        shp_files = glob.glob(os.path.join(folder_path, '*.shp'))
        
        # 3. Validation Rules
        if len(shp_files) == 0:
            self.log_conflict(folder_name, "Empty Directory: Zero Shapefiles (.shp) found.")
            return

        polygons = []
        points = []
        
        # Validate corrupted files / missing sidecars
        required_sidecars = ['.shx', '.dbf'] # .prj is good but sometimes missing, .shx and .dbf are strictly required by ESRI spec
        for shp in shp_files:
            base_name = os.path.splitext(shp)[0]
            for ext in required_sidecars:
                if not os.path.exists(base_name + ext):
                    self.log_conflict(folder_name, f"Corrupted File: Missing {ext} sidecar for {os.path.basename(shp)}")
                    return
            
            # Try to open with GeoPandas. DBF attributes are often saved in
            # Windows-1256 (Arabic) without a .cpg sidecar, which QGIS tolerates
            # but the default UTF-8 read rejects - retry with likely encodings.
            gdf = None
            last_err = None
            for enc in ("utf-8", "cp1256", "windows-1252"):
                try:
                    gdf = gpd.read_file(shp, encoding=enc)
                    break
                except Exception as e:
                    last_err = e
            if gdf is None:
                self.log_conflict(folder_name, f"Corrupted File: Cannot read {os.path.basename(shp)}. Error: {str(last_err)}")
                return
                
            if gdf.empty:
                continue

            # Drop missing/empty geometries (their type reads as NaN, not a string)
            try:
                gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
            except Exception:
                pass
            if gdf.empty:
                continue

            geom_type = gdf.geom_type.iloc[0]
            if not isinstance(geom_type, str):
                self.log_conflict(folder_name, f"Unreadable Geometry: {os.path.basename(shp)} contains no valid geometries.")
                return
            if 'Polygon' in geom_type:
                polygons.append((shp, gdf))
            elif 'Point' in geom_type:
                points.append((shp, gdf))
            else:
                self.log_conflict(folder_name, f"Unsupported Geometry Type: {geom_type} in {os.path.basename(shp)}")
                return

        if len(polygons) == 0:
            self.log_conflict(folder_name, "No Polygons: The folder contains no polygon geometry.")
            return

        # 4. Spatial Deduplication & Layer Classification
        # Unify CRS first: folders often mix UTM and WGS84 shapefiles
        all_poly_gdfs = []
        for shp, gdf in polygons:
            all_poly_gdfs.append(self._ensure_32636(gdf))
        
        if all_poly_gdfs:
            combined_polys = gpd.GeoDataFrame(pd.concat(all_poly_gdfs, ignore_index=True), crs=all_poly_gdfs[0].crs)
        else:
            combined_polys = gpd.GeoDataFrame()

        # Deduplication using WKB
        combined_polys['wkb'] = combined_polys.geometry.apply(lambda geom: geom.wkb if geom else None)
        combined_polys = combined_polys.drop_duplicates(subset=['wkb']).drop(columns=['wkb'])

        # Calculate planar area for sorting
        if combined_polys.crs and combined_polys.crs.is_geographic:
            projected_polys = combined_polys.to_crs(epsg=3857)
        else:
            projected_polys = combined_polys

        combined_polys['calc_area'] = projected_polys.geometry.area
        # Sort descending
        combined_polys = combined_polys.sort_values(by='calc_area', ascending=False).reset_index(drop=True)

        # 5. Computations & Schema Preparation for Polygons
        layer_land = []
        layer_eshghalat = []
        
        for idx, row in combined_polys.iterrows():
            layer_type = "Land" if idx == 0 else "Eshghalat"
            feat = self.format_feature(row, req_number, owner_name, layer_type, is_point=False)
            if layer_type == "Land":
                layer_land.append(feat)
            else:
                layer_eshghalat.append(feat)

        # Points
        layer_point = []
        if points:
            all_point_gdfs = [self._ensure_32636(gdf) for shp, gdf in points]
            combined_points = gpd.GeoDataFrame(pd.concat(all_point_gdfs, ignore_index=True), crs=all_point_gdfs[0].crs)
            # Deduplicate points too
            combined_points['wkb'] = combined_points.geometry.apply(lambda geom: geom.wkb if geom else None)
            combined_points = combined_points.drop_duplicates(subset=['wkb']).drop(columns=['wkb'])
            
            for idx, row in combined_points.iterrows():
                feat = self.format_feature(row, req_number, owner_name, "Point", is_point=True)
                layer_point.append(feat)

        # 6. Save to Unified GeoDatabase
        # Using EPSG:4326 for the final geodatabase if possible, or preserving native
        self.append_to_gpkg(layer_land, "Land", combined_polys.crs)
        self.append_to_gpkg(layer_eshghalat, "Eshghalat", combined_polys.crs)
        if layer_point:
            self.append_to_gpkg(layer_point, "Point", combined_points.crs)

        # 7. File Renaming & Archival
        dest_folder = os.path.join(self.done_dir, folder_name)
        os.makedirs(dest_folder, exist_ok=True)
        
        poly_idx = 1
        for shp, _ in polygons:
            self.archive_shapefile(shp, dest_folder, f"{req_number}_poly_{poly_idx}")
            poly_idx += 1
            
        point_idx = 1
        for shp, _ in points:
            self.archive_shapefile(shp, dest_folder, f"{req_number}_point_{point_idx}")
            point_idx += 1
            
        # Move the original folder to a 'processed' state or delete? 
        # Requirement: 'Replicate the request folder inside "Done"'. We archived the files, now we delete original.
        # shutil.rmtree(folder_path)
        # Remember this request so a later folder with the same number
        # in this run is flagged duplicate, not re-imported.
        self.existing_req_numbers.add(req_number)
        pass # print(f"[SUCCESS] Processed {folder_name} -> Land: 1, Eshghalat: {len(layer_eshghalat)}, Point: {len(layer_point)}")


    def format_feature(self, row, req_number, owner_name, layer_type, is_point):
        geom = row.geometry
        area_sqm = "-"
        area_feddan = "-"
        
        if not is_point:
            area = row['calc_area']
            area_sqm = round(area, 2)
            area_feddan = round(area / 4200.83, 4)
            
        try:
            centroid = geom.centroid
            x = centroid.x
            y = centroid.y
        except:
            x = "-"
            y = "-"
            
        return {
            "geometry": geom,
            "Req_Number": str(req_number),
            "Owner_Name": str(owner_name),
            "Layer_Type": layer_type,
            "Area_SQM": area_sqm,
            "Area_Feddan": area_feddan,
            "X": x,
            "Y": y
        }

    def append_to_gpkg(self, features, table_name, crs):
        if not features:
            return
        gdf = gpd.GeoDataFrame(features, geometry='geometry', crs=crs)

        # If gpkg exists, we append
        if os.path.exists(self.output_gpkg):
            # Conform to the existing layer schema first: layers written by
            # older runs (or other tools) may have different columns, and an
            # exact schema match is required for appending.
            try:
                import pyogrio
                info = pyogrio.list_layers(self.output_gpkg)
                if hasattr(info, "columns") and "name" in info.columns:
                    names = info["name"].tolist()
                else:
                    names = [row[0] for row in info]
                if table_name in names:
                    meta = pyogrio.read_info(self.output_gpkg, layer=table_name)
                    fields = [str(f) for f in meta.get("fields", [])]
                    if fields:
                        for c in fields:
                            if c not in gdf.columns:
                                gdf[c] = None
                        keep = [c for c in fields if c in gdf.columns]
                        if "geometry" not in keep:
                            keep = keep + ["geometry"]
                        gdf = gdf[keep]
            except Exception:
                pass
            gdf.to_file(self.output_gpkg, layer=table_name, driver="GPKG", mode="a")
        else:
            gdf.to_file(self.output_gpkg, layer=table_name, driver="GPKG")

    def archive_shapefile(self, src_shp, dest_folder, new_base_name):
        base_dir = os.path.dirname(src_shp)
        src_base = os.path.splitext(os.path.basename(src_shp))[0]
        
        # Copy all sidecars
        for f in os.listdir(base_dir):
            if f.startswith(src_base + '.') and len(f) == len(src_base) + 4: # matches .shp, .shx etc exactly
                ext = os.path.splitext(f)[1]
                src_file = os.path.join(base_dir, f)
                dest_file = os.path.join(dest_folder, new_base_name + ext)
                shutil.copy2(src_file, dest_file)

import pandas as pd # Ensure pandas is imported

if __name__ == "__main__":
    # Example usage / setup paths
    base_dir = r"d:\Systems\MapViewer"
    input_dir = r"d:\Systems\SHP_Files(2)"
    done_dir = os.path.join(base_dir, "Done")
    conflicts_file = os.path.join(base_dir, "conflicts.json")
    output_gpkg = os.path.join(base_dir, "Unified_Database.gpkg")

    os.makedirs(input_dir, exist_ok=True)
    
    pipeline = GeospatialDataPipeline(input_dir, done_dir, conflicts_file, output_gpkg)
    pipeline.process_all()
