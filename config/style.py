"""Minimal custom CSS. Keeps the native Streamlit look but polishes a few details."""

import streamlit as st


def apply_style():
    st.markdown("""
    <style>
        .block-container { padding-top: 1rem !important; padding-bottom: 0 !important; }

        /* Make header transparent and hide only the deploy toolbar, preserving the sidebar toggle */
        [data-testid="stHeader"] { background: transparent !important; }
        [data-testid="stToolbar"] { display: none !important; }
        [data-testid="stDecoration"] { display: none !important; }

        /* Make Folium map fill full width */
        iframe { width: 100% !important; }
    </style>
    """, unsafe_allow_html=True)
