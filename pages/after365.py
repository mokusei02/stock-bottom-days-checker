"""「最安値から365日後…」ページ。

ナンピン君と同じ機能・表示を共有し、両ページの仕様がずれないようにする。
"""

from pathlib import Path
import sys


repository_root = Path(__file__).resolve().parents[1]
repository_root_directory = str(repository_root)
if repository_root_directory not in sys.path:
    sys.path.insert(0, repository_root_directory)

nanpin_app_path = repository_root / "nanpin_app" / "app.py"
nanpin_app_directory = str(nanpin_app_path.parent)
if nanpin_app_directory not in sys.path:
    sys.path.insert(0, nanpin_app_directory)
nanpin_namespace = {
    "__file__": str(nanpin_app_path),
    "__name__": "__main__",
    "APP_VARIANT": "after365",
}
exec(
    compile(nanpin_app_path.read_text(encoding="utf-8"), str(nanpin_app_path), "exec"),
    nanpin_namespace,
)
