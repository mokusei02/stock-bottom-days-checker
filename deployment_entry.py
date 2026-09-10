"""Alternative Streamlit entry point used to refresh the Cloud deployment."""

from pathlib import Path
import runpy


runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
