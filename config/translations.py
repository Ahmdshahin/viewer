"""UI text constants for the application."""

T = {
    # Sidebar
    "app_title": "GeoData Portal",
    "menu_scan": "Automated Scan",
    "menu_conflicts": "Conflicts Portal",
    "menu_map": "Map Viewer",
    "adv_opts": "Advanced Options",
    "reset_warn": "This will erase the database, processed files, and conflict records.",
    "reset_btn": "🗑️ Erase All Data & Start Fresh",
    "reset_done": "✅ System reset successfully.",

    # Page 1 – Scan
    "path_settings": "Path Settings",
    "input_dir": "Input Folder",
    "out_dir": "Output Folder",
    "db_path": "Database File (.gpkg)",
    "scan_desc": "Scans request folders, validates shapefiles, and appends valid data to the geodatabase.",
    "run_scan": "🚀 Run Scan",
    "scanning": "Scanning…",
    "err_no_dir": "Input folder not found.",
    "err_corrupt": "Corrupt or incomplete file",
    "err_empty": "No shapefiles found",
    "err_no_poly": "No polygon shapefiles found",
    "scan_done": "Scan complete — {succ} succeeded, {err} conflicts.",
    "col_folder": "Folder",
    "col_issue": "Issue",
    "successful": "Successful",
    "conflicts": "Conflicts",
    "no_success": "No new successful requests.",
    "no_conflicts": "No conflicts found.",

    # Page 2 – Conflicts
    "conflicts_title": "Conflicts Portal",
    "no_output_dir": "Output path does not exist.",
    "all_clear": "🎉 No pending conflicts.",
    "n_conflicts": "{n} folder(s) need attention.",
    "select_folder": "Select a folder to inspect:",
    "issue_label": "Issue",
    "fix_instructions": "Fix the folder manually, then click below to re-verify.",
    "mark_fixed": "✅ Mark as Fixed",
    "fixed_done": "Conflict removed — you can re-scan now.",

    # Page 3 – Map
    "map_title": "🌍 Unified Geo-Database Viewer",
    "layer_panel": "Layer Settings",
    "basemap": "Basemap",
    "no_db": "Database not found. Run a scan first.",
    "db_empty": "Database is empty.",
    "map_error": "Error rendering map:",
}
