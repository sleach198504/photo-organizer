"""Builds the self-contained Photo Organizer folder that every package is made from.

    venv\\Scripts\\python.exe packaging\\build_payload.py [--channel store|installer] [--out build\\payload]

The folder holds everything the app needs and downloads nothing when it is installed or run:

    PhotoOrganizer.exe     the launcher Windows starts
    runtime\\              Python 3.12 (the official embeddable build from python.org)
    site-packages\\        the libraries, at the exact versions in constraints.txt
    app\\                  the application (plus package_info.json saying which channel this is)
    models\\               the recognition model
    LICENSE, THIRD_PARTY_NOTICES.md, config.example.yaml

Build-time downloads (Python, one library's source) are cached in packaging\\cache and checked
against the checksums below. Run it from the development environment; it needs the model files
(models\\clip-vit-b32-onnx), which dev/export_clip_onnx.py or app/model_fetch.py provides.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import onnx_clip  # noqa: E402
from app.version import __version__  # noqa: E402

CACHE = ROOT / "packaging" / "cache"

PYTHON_VERSION = "3.12.10"
PYTHON_TAG = "312"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"

# Libraries that are only published as source. They are pure Python, so building a wheel for them
# here works for any Python version.
SOURCE_ONLY = ("reverse_geocoder",)

ICON = ROOT / "app" / "web" / "static" / "icons" / "app.ico"
LAUNCHER_SOURCE = ROOT / "packaging" / "launcher" / "PhotoOrganizer.cs"


def say(message: str) -> None:
    print(message, flush=True)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path, sha256: str) -> Path:
    if dest.is_file() and sha256_of(dest) == sha256:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    say(f"Downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, tmp.open("wb") as out:
        shutil.copyfileobj(response, out)
    if sha256_of(tmp) != sha256:
        tmp.unlink()
        raise SystemExit(f"{dest.name} does not match its recorded checksum; refusing to use it.")
    tmp.replace(dest)
    return dest


def run(command: list, **kwargs) -> None:
    result = subprocess.run([str(c) for c in command], **kwargs)
    if result.returncode != 0:
        raise SystemExit(f"Command failed ({result.returncode}): {' '.join(str(c) for c in command[:6])} ...")


def pinned(name: str) -> str:
    """The `name==version` line from constraints.txt."""
    for line in (ROOT / "constraints.txt").read_text(encoding="utf-8").splitlines():
        if line.lower().replace("_", "-").startswith(name.lower().replace("_", "-") + "=="):
            return line.strip()
    raise SystemExit(f"{name} is not pinned in constraints.txt")


def install_runtime(out: Path) -> None:
    say(f"Python {PYTHON_VERSION} runtime")
    archive = download(PYTHON_URL, CACHE / f"python-{PYTHON_VERSION}-embed-amd64.zip", PYTHON_SHA256)
    runtime = out / "runtime"
    with zipfile.ZipFile(archive) as z:
        z.extractall(runtime)
    # Paths are relative to this file. `..` is the payload root, so `import app` works.
    (runtime / f"python{PYTHON_TAG}._pth").write_text(
        f"python{PYTHON_TAG}.zip\n.\n..\\site-packages\n..\n\nimport site\n", encoding="utf-8"
    )


def install_libraries(out: Path) -> None:
    say("Libraries (exact versions from constraints.txt)")
    site = out / "site-packages"
    skip = {s.lower().replace("_", "-") for s in SOURCE_ONLY}

    def without_source_only(lines: list[str]) -> list[str]:
        return [ln for ln in lines if ln.strip().lower().replace("_", "-").split("=")[0].split(">")[0].split("[")[0] not in skip]

    work = CACHE / "work"
    work.mkdir(parents=True, exist_ok=True)
    reqs, cons = work / "requirements.txt", work / "constraints.txt"
    reqs.write_text("\n".join(without_source_only((ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines())), encoding="utf-8")
    cons.write_text("\n".join(without_source_only((ROOT / "constraints.txt").read_text(encoding="utf-8").splitlines())), encoding="utf-8")

    run([
        sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-compile", "--upgrade",
        "--target", site, "--python-version", "3.12", "--platform", "win_amd64", "--implementation", "cp",
        "--only-binary=:all:", "-r", reqs, "-c", cons,
    ])
    for name in SOURCE_ONLY:
        wheels = CACHE / "wheels"
        run([sys.executable, "-m", "pip", "wheel", "--disable-pip-version-check", "--no-deps", "-w", wheels, pinned(name)])
        wheel = next(wheels.glob(f"{name}-*.whl"))
        run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-compile", "--no-deps",
             "--target", site, wheel])

    shutil.rmtree(site / "bin", ignore_errors=True)  # command-line scripts nobody runs from here
    # Test suites of the two big numerical libraries (tens of MB). `numpy.testing` is a different thing and stays.
    for package in ("numpy", "scipy"):
        for tests in (site / package).rglob("tests"):
            if tests.is_dir():
                shutil.rmtree(tests, ignore_errors=True)


def copy_application(out: Path, channel: str) -> None:
    say("Application")
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "package_info.json")
    shutil.copytree(ROOT / "app", out / "app", ignore=ignore)
    for name in ("config.example.yaml", "LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copyfile(ROOT / name, out / name)
    (out / "app" / "package_info.json").write_text(
        json.dumps({"channel": channel, "version": __version__, "built": datetime.now(timezone.utc).isoformat(timespec="seconds")}, indent=2) + "\n",
        encoding="utf-8",
    )


def copy_model(out: Path) -> None:
    say("Recognition model")
    if not onnx_clip.model_files_present() or not onnx_clip.verify_files():
        raise SystemExit("The recognition model is missing or damaged here. Run dev/export_clip_onnx.py or app/model_fetch.py first.")
    shutil.copytree(onnx_clip.MODEL_DIR, out / "models" / onnx_clip.MODEL_DIR.name)


def find_csc() -> Path:
    for framework in ("Framework64", "Framework"):
        csc = Path(f"C:/Windows/Microsoft.NET/{framework}/v4.0.30319/csc.exe")
        if csc.is_file():
            return csc
    raise SystemExit("csc.exe (the C# compiler that comes with Windows) was not found.")


def build_launcher(out: Path) -> None:
    say("Launcher")
    version = ".".join((__version__.split(".") + ["0", "0", "0"])[:3] + ["0"])
    source = CACHE / "work" / "PhotoOrganizer.cs"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(LAUNCHER_SOURCE.read_text(encoding="utf-8").replace("0.0.0.0", version), encoding="utf-8")
    run([find_csc(), "/nologo", "/target:winexe", "/optimize+", f"/win32icon:{ICON}", f"/out:{out / 'PhotoOrganizer.exe'}",
         "/reference:System.Windows.Forms.dll", source])


def precompile(out: Path) -> None:
    """Python cannot write .pyc files into a read-only install, so make them now. Without them every
    start would compile every library again."""
    say("Precompiling")
    run([out / "runtime" / "python.exe", "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "unchecked-hash",
         out / "site-packages", out / "app"])


def folder_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--channel", choices=("store", "installer"), default="installer")
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "payload")
    args = parser.parse_args()

    out = args.out.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    install_runtime(out)
    install_libraries(out)
    copy_application(out, args.channel)
    copy_model(out)
    build_launcher(out)
    precompile(out)

    say("")
    say(f"Built {out}  (version {__version__}, channel {args.channel})")
    for part in ("runtime", "site-packages", "app", "models"):
        say(f"  {part:14} {folder_size(out / part) / (1 << 20):8,.0f} MB")
    say(f"  {'total':14} {folder_size(out) / (1 << 20):8,.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
