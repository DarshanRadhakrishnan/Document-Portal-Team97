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
    /* fill the window with the page's own frame so there is one scrollbar, not two */
    iframe{height:100vh !important;height:100dvh !important;display:block}
    [data-testid="stMain"],[data-testid="stAppViewContainer"]{overflow:hidden !important}
    [data-testid="stVerticalBlock"]{gap:0 !important}    </style>""",
    unsafe_allow_html=True,
)
# Inside Streamlit's srcdoc iframe, href="#id" resolves against the Streamlit URL and
# reloads the app in the frame, so in-page links are scrolled by hand instead.
# window.scrollTo rather than scrollIntoView, which would also scroll the Streamlit page.
NAV_FIX = """<script>
document.addEventListener('click', function (e) {
  var a = e.target.closest('a[href^="#"]'); if (!a) return;
  e.preventDefault();
  var id = a.getAttribute('href').slice(1);
  var t = id && document.getElementById(id);
  var pad = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
  window.scrollTo({top: t ? t.getBoundingClientRect().top + window.scrollY - pad : 0});
});
</script>"""
page = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")
page = ("<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>" + NAV_FIX + page)
components.html(page, height=1800, scrolling=True)
