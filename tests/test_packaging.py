"""The Store package's manifest and version rules (the build itself is exercised by packaging/smoke_payload.py)."""
from __future__ import annotations

import json
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))

import build_msix  # noqa: E402

NS = {
    "m": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
    "uap": "http://schemas.microsoft.com/appx/manifest/uap/windows10",
    "rescap": "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities",
}


def identity(**over) -> dict:
    base = json.loads((ROOT / "packaging" / "store_identity.json").read_text(encoding="utf-8"))
    return {**base, **over}


class VersionTests(unittest.TestCase):
    def test_store_versions_have_four_parts_and_end_in_zero(self) -> None:
        for version, want in (("2.0.0", "2.0.0.0"), ("2.1", "2.1.0.0"), ("3", "3.0.0.0"), ("2.0.5", "2.0.5.0")):
            with mock.patch.object(build_msix, "__version__", version):
                self.assertEqual(build_msix.package_version(), want)


class ManifestTests(unittest.TestCase):
    def parse(self, **over) -> ET.Element:
        return ET.fromstring(build_msix.manifest_xml(identity(**over)))

    def test_it_is_well_formed_and_names_the_launcher(self) -> None:
        root = self.parse()
        app = root.find("m:Applications/m:Application", NS)
        self.assertEqual(app.get("Executable"), "PhotoOrganizer.exe")
        self.assertEqual(app.get("EntryPoint"), "Windows.FullTrustApplication")

    def test_identity_comes_from_the_identity_file(self) -> None:
        root = self.parse(identity_name="12345Pat.PhotoOrganizer", publisher="CN=ABCD-1234")
        ident = root.find("m:Identity", NS)
        self.assertEqual(ident.get("Name"), "12345Pat.PhotoOrganizer")
        self.assertEqual(ident.get("Publisher"), "CN=ABCD-1234")
        self.assertEqual(ident.get("ProcessorArchitecture"), "x64")

    def test_text_with_special_characters_cannot_break_the_manifest(self) -> None:
        root = self.parse(display_name='Photo & "Video" <Organizer>', publisher_display_name="Pat & Co", description='A "quoted" <b>')
        self.assertEqual(root.find("m:Properties/m:DisplayName", NS).text, 'Photo & "Video" <Organizer>')
        self.assertEqual(root.find("m:Properties/m:PublisherDisplayName", NS).text, "Pat & Co")

    def test_the_only_capability_asked_for_is_full_trust(self) -> None:
        caps = self.parse().findall("m:Capabilities/*", NS)
        self.assertEqual([c.get("Name") for c in caps], ["runFullTrust"])

    def test_every_image_the_manifest_names_gets_generated(self) -> None:
        import tempfile

        root = self.parse()
        named = {
            root.find("m:Properties/m:Logo", NS).text,
            *(v for e in root.iter() for k, v in e.attrib.items() if k.endswith("Logo")),
        }
        with tempfile.TemporaryDirectory() as tmp:
            build_msix.make_assets(Path(tmp))
            made = {p.name for p in (Path(tmp) / "Assets").iterdir()}
        for logo in named:
            stem, ext = Path(logo.replace("\\", "/")).stem, Path(logo).suffix
            self.assertTrue(
                any(name.startswith(stem + ".") and name.endswith(ext) for name in made),
                f"no image was generated for {logo}",
            )


if __name__ == "__main__":
    unittest.main()
