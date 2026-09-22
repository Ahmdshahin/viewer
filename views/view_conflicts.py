"""Page 2 — Conflicts Portal: review and resolve failed folders."""

import streamlit as st
import os

from core.geo_engine import GeoEngine


def render(T: dict, engine: GeoEngine):
    st.header("🔍 " + T["conflicts_title"])

    if not os.path.isdir(engine.problems_dir):
        st.warning(T["no_output_dir"])
        return

    conflicts = engine.load_conflicts()

    if not conflicts:
        st.success(T["all_clear"])
        return

    st.warning(T["n_conflicts"].format(n=len(conflicts)))

    folder_names = list(conflicts.keys())
    selected = st.selectbox(T["select_folder"], folder_names)

    if selected:
        data = conflicts[selected]
        st.error(f"**{T['issue_label']}:** {data['reason']}")
        st.info(T["fix_instructions"])

        if st.button(T["mark_fixed"], type="primary", use_container_width=True):
            del conflicts[selected]
            engine.save_conflicts(conflicts)
            st.toast(T["fixed_done"], icon="✅")
            st.rerun()
