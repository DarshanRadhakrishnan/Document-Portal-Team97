from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="Evolutionary Algorithm Benchmark Selection System",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(
    """<style>
    header[data-testid="stHeader"]{display:none}
    footer{visibility:hidden}
    .block-container{padding:0 !important;max-width:100% !important}
    </style>""",
    unsafe_allow_html=True,
)
page = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")
page = ("<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>" + page)
components.html(page, height=1800, scrolling=True)
