"""Alternative Streamlit entry point used to refresh the Cloud deployment."""

from pathlib import Path
import runpy

import streamlit as st


_native_page_link = st.page_link


def _deployment_page_link(page, *args, **kwargs):
    if page == "app.py":
        page = "deployment_entry.py"
    return _native_page_link(page, *args, **kwargs)


st.page_link = _deployment_page_link
runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
