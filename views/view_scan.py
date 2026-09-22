"""Page 1 — Automated Scan: configure paths, scan folders, show results."""

import streamlit as st
import pandas as pd
import geopandas as gpd
import os
import glob

from core.geo_engine import GeoEngine


def render(T: dict, engine: GeoEngine):
    st.header("📂 " + T["path_settings"])

    # ── Path inputs ─────────────────────────────────────────────────────
    base_dir = st.text_input(T["input_dir"], st.session_state.base_dir)

    col_done, col_prob = st.columns(2)
    with col_done:
        done_dir = st.text_input("✅ Done Folder (processed files)", st.session_state.done_dir)
    with col_prob:
        problems_dir = st.text_input("❌ Problems Folder (conflict files)", st.session_state.problems_dir)

    db_path = st.text_input(T["db_path"], st.session_state.db_path)

    # Sync session state & engine
    st.session_state.base_dir = base_dir
    st.session_state.done_dir = done_dir
    st.session_state.problems_dir = problems_dir
    st.session_state.db_path = db_path
    engine.base_dir = base_dir
    engine.db_path = db_path
    engine.rename_dir = done_dir
    engine.problems_dir = problems_dir
    engine.conflicts_file = os.path.join(problems_dir, "conflicts.json")

    # ── Scan button ─────────────────────────────────────────────────────
    st.divider()
    st.caption(T["scan_desc"])

    if st.button(T["run_scan"], type="primary", use_container_width=True):
        _run_scan(T, engine)


def _run_scan(T: dict, engine: GeoEngine):
    """Execute the folder scan and display results."""

    if not os.path.isdir(engine.base_dir):
        st.error(f"{T['err_no_dir']}  `{engine.base_dir}`")
        return

    folders = [f.path for f in os.scandir(engine.base_dir) if f.is_dir()]
    if not folders:
        st.warning("No sub-folders found in the input directory.")
        return

    conflicts = engine.load_conflicts()
    processed = []
    new_conflicts = 0

    # Clean stale conflict entries
    on_disk = {os.path.basename(f) for f in folders}
    conflicts = {k: v for k, v in conflicts.items() if k in on_disk}

    progress = st.progress(0, text=T["scanning"])
    for i, folder in enumerate(folders):
        progress.progress((i + 1) / len(folders), text=f"Scanning {i+1}/{len(folders)}…")
        folder_name = os.path.basename(folder)

        if folder_name in conflicts:
            continue
        if os.path.exists(os.path.join(engine.rename_dir, folder_name)):
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
            except Exception:
                corrupt += 1

        # Determine conflict
        reasons = []
        if corrupt > 0:
            reasons.append(T["err_corrupt"])
        elif not poly_files and not point_files:
            reasons.append(T["err_empty"])
        elif not poly_files:
            reasons.append(T["err_no_poly"])

        if reasons:
            conflicts[folder_name] = {
                "folder_path": folder,
                "reason": " | ".join(reasons),
            }
            new_conflicts += 1
        else:
            engine.process_valid_folder(folder, poly_files, point_files)
            processed.append(folder_name)

    engine.save_conflicts(conflicts)
    progress.empty()

    # ── Results ─────────────────────────────────────────────────────────
    st.success(T["scan_done"].format(succ=len(processed), err=new_conflicts))

    m1, m2 = st.columns(2)
    m1.metric(T["successful"], len(processed))
    m2.metric(T["conflicts"], len(conflicts))

    col_ok, col_err = st.columns(2)
    with col_ok:
        st.subheader(T["successful"])
        if processed:
            st.dataframe(
                pd.DataFrame(processed, columns=[T["col_folder"]]),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info(T["no_success"])

    with col_err:
        st.subheader(T["conflicts"])
        if conflicts:
            rows = [{T["col_folder"]: k, T["col_issue"]: v["reason"]} for k, v in conflicts.items()]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info(T["no_conflicts"])
