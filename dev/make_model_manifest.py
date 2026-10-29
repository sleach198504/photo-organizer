"""Writes app/model_manifest.json from the exported ONNX model files.

Run it after dev/export_clip_onnx.py. It records each file's size and SHA-256, and the address
Setup downloads them from. Upload the four files in the folder it names to a GitHub release
with that tag, marked as a pre-release so it never becomes the "latest" release that Install.bat
installs the app from.

    venv\\Scripts\\python.exe dev\\make_model_manifest.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import model_fetch, onnx_clip  # noqa: E402

REPO = "sleach198504/photo-organizer"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="model-clip-vit-b32-1", help="release tag the files are uploaded under")
    parser.add_argument("--folder", type=Path, default=onnx_clip.MODEL_DIR)
    args = parser.parse_args()

    if not onnx_clip.model_files_present(args.folder) or not onnx_clip.verify_files(args.folder):
        print(f"{args.folder} does not hold a complete, verified model. Run dev/export_clip_onnx.py first.")
        return 1

    files = [
        {"name": name, "size": (args.folder / name).stat().st_size, "sha256": model_fetch.sha256_of(args.folder / name)}
        for name in onnx_clip.REQUIRED_FILES
    ]
    manifest = {
        "model": "openai/clip-vit-base-patch32 (MIT), converted to ONNX",
        "base_url": f"https://github.com/{REPO}/releases/download/{args.tag}",
        "files": files,
    }
    model_fetch.MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {model_fetch.MANIFEST_PATH}")
    print(f"Upload these files to a pre-release tagged {args.tag}:")
    for entry in files:
        print(f"  {args.folder / entry['name']}  ({entry['size']:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
