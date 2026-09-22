"""
GeoData Processor & Portal — main entry point.

Layout:
  Sidebar  → page navigation + danger-zone reset
  Main     → the selected page view
"""

import streamlit as st

from config.translations import T
from config.style import apply_style
from core.geo_engine import GeoEngine
from views import view_scan, view_conflicts, view_map

# ── Page config (must be first Streamlit call) ──────────────────────────────
st.set_page_config(
    page_title="GeoData Processor & Portal",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_style()


# ── Session-state defaults ──────────────────────────────────────────────────
_DEFAULTS = {
    "base_dir":     r"d:\Systems\SHP_Files(2)",
    "done_dir":     r"d:\Systems\MapViewer\Done",
    "problems_dir": r"d:\Systems\MapViewer\Problems",
    "db_path":      r"d:\Systems\MapViewer\Unified_Database.gpkg",
    "layers_cfg": {
        "Land":      {"show": True, "color": "#e74c3c", "opacity": 0.5},
        "Eshghalat": {"show": True, "color": "#3498db", "opacity": 0.5},
        "Point":     {"show": True, "color": "#27ae60", "opacity": 0.8},
    },
}
for key, val in _DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ── Engine ──────────────────────────────────────────────────────────────────
engine = GeoEngine(
    base_dir=st.session_state.base_dir,
    done_dir=st.session_state.done_dir,
    problems_dir=st.session_state.problems_dir,
    db_path=st.session_state.db_path,
)

# ── Sidebar ─────────────────────────────────────────────────────────────────
st.sidebar.title(T["app_title"])

page = st.sidebar.radio(
    "Navigate",
    [T["menu_scan"], T["menu_conflicts"], T["menu_map"]],
    label_visibility="collapsed",
)

st.sidebar.divider()

with st.sidebar.expander(T["adv_opts"], icon="⚠️"):
    st.caption(T["reset_warn"])
    if st.button(T["reset_btn"], type="primary", use_container_width=True):
        engine.reset_system()
        st.toast(T["reset_done"], icon="✅")
        st.rerun()

# ── Page router ─────────────────────────────────────────────────────────────
if page == T["menu_scan"]:
    view_scan.render(T, engine)
elif page == T["menu_conflicts"]:
    view_conflicts.render(T, engine)
elif page == T["menu_map"]:
    view_map.render(T, engine)
