from pathlib import Path
import sys


nanpin_app_path = Path(__file__).resolve().parents[1] / "nanpin_app" / "app.py"
nanpin_app_directory = str(nanpin_app_path.parent)
if nanpin_app_directory not in sys.path:
    sys.path.insert(0, nanpin_app_directory)
nanpin_namespace = {
    "__file__": str(nanpin_app_path),
    "__name__": "__main__",
}
exec(
    compile(nanpin_app_path.read_text(encoding="utf-8"), str(nanpin_app_path), "exec"),
    nanpin_namespace,
)
