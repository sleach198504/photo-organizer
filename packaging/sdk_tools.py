"""Gets Microsoft's package-building tools (makeappx, makepri, signtool) without installing the Windows SDK.

They come from the official `Microsoft.Windows.SDK.BuildTools` package on nuget.org (22 MB), are
checked against the checksum below, and are unpacked into packaging/cache. Nothing is installed on
the PC and no administrator rights are needed.
"""
from __future__ import annotations

import hashlib
import shutil
import urllib.request
import zipfile
from pathlib import Path

CACHE = Path(__file__).resolve().parent / "cache"

VERSION = "10.0.26100.9457"
URL = f"https://api.nuget.org/v3-flatcontainer/microsoft.windows.sdk.buildtools/{VERSION}/microsoft.windows.sdk.buildtools.{VERSION}.nupkg"
SHA256 = "4c2e0d85f3490e7f7c065c35b4c47fe913b1bc9627e9711ae349b2cdc7edc791"

TOOLS = ("makeappx.exe", "makepri.exe", "signtool.exe")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_tools() -> dict[str, Path]:
    """Paths to makeappx.exe, makepri.exe and signtool.exe, downloading them the first time."""
    folder = CACHE / f"sdk-buildtools-{VERSION}"
    found = {name: next(iter(folder.rglob(f"x64/{name}")), None) for name in TOOLS} if folder.is_dir() else {}
    if found and all(found.values()):
        return {name: path for name, path in found.items()}

    CACHE.mkdir(parents=True, exist_ok=True)
    package = CACHE / f"Microsoft.Windows.SDK.BuildTools.{VERSION}.nupkg"
    if not package.is_file():
        print(f"Downloading {URL}", flush=True)
        with urllib.request.urlopen(URL, timeout=120) as response, package.open("wb") as out:
            shutil.copyfileobj(response, out)
    if SHA256 and _sha256(package) != SHA256:
        package.unlink()
        raise SystemExit("The SDK build tools download does not match its recorded checksum; refusing to use it.")
    shutil.rmtree(folder, ignore_errors=True)
    with zipfile.ZipFile(package) as z:
        z.extractall(folder)
    found = {name: next(iter(folder.rglob(f"x64/{name}")), None) for name in TOOLS}
    missing = [name for name, path in found.items() if path is None]
    if missing:
        raise SystemExit(f"The SDK build tools package did not contain {', '.join(missing)}")
    return found  # type: ignore[return-value]


if __name__ == "__main__":
    for tool, path in get_tools().items():
        print(f"{tool:14} {path}")
    print("package sha256:", _sha256(CACHE / f"Microsoft.Windows.SDK.BuildTools.{VERSION}.nupkg"))
