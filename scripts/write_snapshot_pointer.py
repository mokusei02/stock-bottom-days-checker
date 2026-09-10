"""Generate a pointer to a committed snapshot before publishing both commits."""
import argparse
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--data", type=Path, required=True)
args = parser.parse_args()
revision = subprocess.check_output(["git", "-C", str(args.data), "rev-parse", "HEAD"], text=True).strip()
(args.data / "latest.json").write_text(json.dumps({"revision": revision}) + "\n", encoding="utf-8")
