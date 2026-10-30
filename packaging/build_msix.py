"""Builds the Microsoft Store package (.msix) from the app.

    venv\\Scripts\\python.exe packaging\\build_msix.py [--sign] [--skip-payload]

1. builds the payload for the "store" channel (packaging/build_payload.py) into build/msix-layout,
2. adds AppxManifest.xml, the tile images and resources.pri,
3. packs it with makeappx (fetched by packaging/sdk_tools.py; nothing is installed),
4. with --sign, signs it with a throwaway development certificate so it can be test-installed.

The package identity comes from packaging/store_identity.json. The real values are assigned by
Microsoft Partner Center; for the file you submit, leave signing off - the Store signs it itself.
"""
from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packaging"))

import build_payload  # noqa: E402
import sdk_tools  # noqa: E402
from app.version import __version__  # noqa: E402

CACHE = ROOT / "packaging" / "cache"
IDENTITY = ROOT / "packaging" / "store_identity.json"
LAYOUT = ROOT / "build" / "msix-layout"
DIST = ROOT / "build" / "dist"

# Windows 10 version 1809 is the oldest that can install MSIX with these features.
MIN_WINDOWS = "10.0.17763.0"


def say(message: str) -> None:
    print(message, flush=True)


def run(command: list, **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run([str(c) for c in command], capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise SystemExit(f"Command failed ({result.returncode}): {' '.join(str(c) for c in command[:4])}\n{result.stdout}\n{result.stderr}")
    return result


def package_version() -> str:
    """Store versions are four numbers, and the last must stay 0 (the Store reserves it)."""
    parts = (__version__.split(".") + ["0", "0", "0"])[:3]
    return ".".join(parts) + ".0"


def manifest_xml(identity: dict) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
         xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
         IgnorableNamespaces="uap rescap">
  <Identity Name={quoteattr(identity['identity_name'])} Publisher={quoteattr(identity['publisher'])}
            Version="{package_version()}" ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>{escape(identity['display_name'])}</DisplayName>
    <PublisherDisplayName>{escape(identity['publisher_display_name'])}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="{MIN_WINDOWS}" MaxVersionTested="10.0.26100.0" />
  </Dependencies>
  <Resources>
    <Resource Language="en-us" />
  </Resources>
  <Applications>
    <Application Id="PhotoOrganizer" Executable="PhotoOrganizer.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName={quoteattr(identity['display_name'])} Description={quoteattr(identity['description'])}
                          BackgroundColor="transparent"
                          Square150x150Logo="Assets\\Square150x150Logo.png"
                          Square44x44Logo="Assets\\Square44x44Logo.png">
        <uap:DefaultTile Wide310x150Logo="Assets\\Wide310x150Logo.png" ShortName="Photo Organizer" />
      </uap:VisualElements>
    </Application>
  </Applications>
  <Capabilities>
    <!-- The app reads and moves the photos in folders the person chooses, anywhere on the PC. -->
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
</Package>
"""


def make_assets(layout: Path) -> None:
    """Tile and logo images, drawn from the same code as the app icon (dev/make_icons.py)."""
    from PIL import Image

    from dev.make_icons import draw

    master = draw(1024)
    assets = layout / "Assets"
    assets.mkdir(parents=True, exist_ok=True)

    def square(name: str, size: int) -> None:
        master.resize((size, size), Image.Resampling.LANCZOS).save(assets / name)

    def wide(name: str, width: int, height: int) -> None:
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        icon = master.resize((height, height), Image.Resampling.LANCZOS)
        canvas.paste(icon, ((width - height) // 2, 0), icon)
        canvas.save(assets / name)

    for scale, factor in ((100, 1), (200, 2), (400, 4)):
        square(f"StoreLogo.scale-{scale}.png", 50 * factor)
        square(f"Square44x44Logo.scale-{scale}.png", 44 * factor)
        square(f"Square150x150Logo.scale-{scale}.png", 150 * factor)
        wide(f"Wide310x150Logo.scale-{scale}.png", 310 * factor, 150 * factor)
    for target in (16, 24, 32, 48, 256):
        square(f"Square44x44Logo.targetsize-{target}.png", target)
        square(f"Square44x44Logo.targetsize-{target}_altform-unplated.png", target)


def make_resource_index(layout: Path, tools: dict[str, Path]) -> None:
    """resources.pri lets Windows pick the right image size. It is built from the manifest and
    assets alone: scanning the whole payload (tens of thousands of files) would be slow and pointless."""
    work = CACHE / "pri-work"
    shutil.rmtree(work, ignore_errors=True)
    (work / "Assets").parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(layout / "Assets", work / "Assets")
    shutil.copyfile(layout / "AppxManifest.xml", work / "AppxManifest.xml")
    config = CACHE / "priconfig.xml"
    run([tools["makepri.exe"], "createconfig", "/cf", config, "/dq", "en-US", "/pv", "10.0.0", "/o"])
    run([tools["makepri.exe"], "new", "/pr", work, "/cf", config, "/mn", work / "AppxManifest.xml",
         "/of", layout / "resources.pri", "/o"])


def sign_package(package: Path, identity: dict, tools: dict[str, Path]) -> Path:
    """Signs with a development certificate whose name matches the package's publisher. The
    certificate is created once, exported to packaging/cache, and removed from the Windows store
    again so nothing is left behind on the PC. Returns the public certificate (.cer)."""
    pfx, cer, pw_file = CACHE / "test-signing.pfx", CACHE / "test-signing.cer", CACHE / "test-signing.pw"
    stale = not pfx.is_file() or json.loads(pw_file.read_text() if pw_file.is_file() else "{}").get("publisher") != identity["publisher"]
    if stale:
        say("Creating a development signing certificate")
        password = secrets.token_urlsafe(18)
        script = f"""
$ErrorActionPreference = 'Stop'
$cert = New-SelfSignedCertificate -Type Custom -Subject '{identity['publisher']}' -KeyUsage DigitalSignature `
  -FriendlyName 'Photo Organizer development signing' -CertStoreLocation 'Cert:\\CurrentUser\\My' `
  -TextExtension @('2.5.29.37={{text}}1.3.6.1.5.5.7.3.3', '2.5.29.19={{text}}') -NotAfter (Get-Date).AddYears(2)
try {{
  $secure = ConvertTo-SecureString -String '{password}' -Force -AsPlainText
  Export-PfxCertificate -Cert $cert -FilePath '{pfx}' -Password $secure | Out-Null
  Export-Certificate -Cert $cert -FilePath '{cer}' | Out-Null
}} finally {{
  Remove-Item $cert.PSPath -ErrorAction SilentlyContinue
}}
"""
        run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script])
        pw_file.write_text(json.dumps({"password": password, "publisher": identity["publisher"]}), encoding="utf-8")
    password = json.loads(pw_file.read_text(encoding="utf-8"))["password"]
    run([tools["signtool.exe"], "sign", "/fd", "SHA256", "/f", pfx, "/p", password, package])
    return cer


def check_package(package: Path, layout: Path) -> None:
    """The package is a zip: make sure the pieces that matter are in it, at the right sizes."""
    with zipfile.ZipFile(package) as z:
        names = {i.filename: i for i in z.infolist()}
    for required in ("AppxManifest.xml", "AppxBlockMap.xml", "resources.pri", "PhotoOrganizer.exe", "app/package_info.json",
                     "runtime/pythonw.exe", "models/clip-vit-b32-onnx/visual.onnx"):
        if required not in names:
            raise SystemExit(f"The package is missing {required}")
    on_disk = layout / "models" / "clip-vit-b32-onnx" / "visual.onnx"
    if names["models/clip-vit-b32-onnx/visual.onnx"].file_size != on_disk.stat().st_size:
        raise SystemExit("The model inside the package has the wrong size")
    info = json.loads(zipfile.ZipFile(package).read("app/package_info.json"))
    if info.get("channel") != "store":
        raise SystemExit("The package was not built for the store channel")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sign", action="store_true", help="sign with a development certificate, for test installs")
    parser.add_argument("--skip-payload", action="store_true", help="reuse build/msix-layout from the last run")
    args = parser.parse_args()

    identity = json.loads(IDENTITY.read_text(encoding="utf-8"))
    tools = sdk_tools.get_tools()

    if not args.skip_payload or not LAYOUT.is_dir():
        build_payload_args = ["--channel", "store", "--out", str(LAYOUT)]
        sys.argv = ["build_payload.py", *build_payload_args]
        if build_payload.main() != 0:
            return 1
    say("Manifest and images")
    (LAYOUT / "AppxManifest.xml").write_text(manifest_xml(identity), encoding="utf-8")
    shutil.rmtree(LAYOUT / "Assets", ignore_errors=True)
    make_assets(LAYOUT)
    make_resource_index(LAYOUT, tools)

    DIST.mkdir(parents=True, exist_ok=True)
    package = DIST / f"PhotoOrganizer_{package_version()}_x64.msix"
    package.unlink(missing_ok=True)
    say("Packing (this takes a few minutes)")
    run([tools["makeappx.exe"], "pack", "/d", LAYOUT, "/p", package, "/o"])
    check_package(package, LAYOUT)

    say(f"\nBuilt {package}  ({package.stat().st_size / (1 << 20):,.0f} MB)")
    if args.sign:
        cer = sign_package(package, identity, tools)
        say(f"Signed with a development certificate. To test-install, trust {cer} first (see docs/PACKAGING.md).")
    else:
        say("Not signed: this is the file to submit to the Store, which signs it itself.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
