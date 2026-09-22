"""Page 3 — Map Viewer: interactive Folium map with layer styling controls."""

import streamlit as st
import geopandas as gpd
import os
import folium
from streamlit_folium import st_folium

from core.geo_engine import GeoEngine

_TOOLTIP_FIELDS = ["Req_Number", "Owner_Name", "Layer_Type", "Area_SQM", "Area_Feddan", "X", "Y"]
_TOOLTIP_ALIASES = ["Req #", "Owner", "Layer", "Area (m²)", "Area (fed)", "X", "Y"]

_LAYER_ORDER_OPTIONS = [
    ["Land", "Eshghalat", "Point"],
    ["Eshghalat", "Land", "Point"],
    ["Point", "Land", "Eshghalat"],
    ["Point", "Eshghalat", "Land"],
]


def render(T: dict, engine: GeoEngine):
    # ── Sidebar: Layer Styling Controls ─────────────────────────────────
    st.sidebar.divider()
    st.sidebar.markdown("### 🎨 Layer Styling")

    for lname in ["Land", "Eshghalat", "Point"]:
        cfg = st.session_state.layers_cfg[lname]
        with st.sidebar.expander(f"{'👁️' if cfg['show'] else '🚫'} {lname}", expanded=False):
            cfg["show"] = st.checkbox("Visible", value=cfg["show"], key=f"vis_{lname}")
            cfg["color"] = st.color_picker("Color", value=cfg["color"], key=f"col_{lname}")
            cfg["opacity"] = st.slider("Opacity", 0.0, 1.0, cfg.get("opacity", 0.5), 0.05, key=f"opa_{lname}")

    st.sidebar.divider()
    order_labels = [" → ".join(o) for o in _LAYER_ORDER_OPTIONS]
    order_idx = st.sidebar.selectbox("📋 Layer Draw Order", range(len(order_labels)), format_func=lambda i: order_labels[i])
    draw_order = _LAYER_ORDER_OPTIONS[order_idx]

    # ── Map ──────────────────────────────────────────────────────────────
    if not os.path.exists(engine.db_path):
        st.info(T["no_db"])
        return

    try:
        m = folium.Map(location=[26.8206, 30.8025], zoom_start=6, tiles=None, prefer_canvas=True)

        # Basemaps
        folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
        folium.TileLayer(
            tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
            attr="Google Satellite",
            name="Satellite",
        ).add_to(m)

        bounds = []
        any_loaded = False

        # Draw layers in user-selected order
        for layer_name in draw_order:
            cfg = st.session_state.layers_cfg[layer_name]
            if not cfg["show"]:
                continue

            try:
                gdf = gpd.read_file(engine.db_path, layer=layer_name)
                if gdf.empty:
                    continue
                any_loaded = True
                if gdf.crs:
                    gdf = gdf.to_crs(epsg=4326)

                color = cfg["color"]
                opacity = cfg.get("opacity", 0.5)
                fg = folium.FeatureGroup(name=layer_name, show=True)

                tooltip = folium.GeoJsonTooltip(
                    fields=_TOOLTIP_FIELDS,
                    aliases=_TOOLTIP_ALIASES,
                    localize=True,
                    sticky=False,
                    labels=True,
                    style="background-color:#F0EFEF; border:2px solid #333; border-radius:4px; box-shadow:2px 2px 6px rgba(0,0,0,.3); padding:6px;",
                    max_width=400,
                )

                if layer_name == "Point":
                    marker = folium.CircleMarker(
                        radius=5, color="black", weight=1, fill_color=color, fill_opacity=opacity
                    )
                    folium.GeoJson(gdf, name=layer_name, marker=marker, tooltip=tooltip).add_to(fg)
                else:
                    def style_fn(feature, _c=color, _o=opacity):
                        return {"fillColor": _c, "color": _c, "weight": 1.5, "fillOpacity": _o}

                    folium.GeoJson(
                        gdf, name=layer_name, style_function=style_fn,
                        smooth_factor=2.0, tooltip=tooltip,
                    ).add_to(fg)

                fg.add_to(m)
                minx, miny, maxx, maxy = gdf.total_bounds
                bounds.append([[miny, minx], [maxy, maxx]])

            except Exception:
                pass

        if not any_loaded:
            st.info(T["db_empty"])
            return

        if bounds:
            flat = [pt for pair in bounds for pt in pair]
            m.fit_bounds(flat)

        folium.LayerControl(position="topright", collapsed=False).add_to(m)
        st_folium(m, use_container_width=True, height=850, returned_objects=[])

    except Exception as e:
        st.error(f"{T['map_error']} {e}")
