"""Builds a dataset whose right answers are known by construction.

Each family below starts from one base picture and applies a documented change, so we know
which pictures belong together and which one is best. Bases are either generated scenes
(nothing personal, reproducible) or your own photos via `--from`, in which case the output
stays on your PC like the originals.

What this can and cannot tell you: it measures how robust the engine is to the edits people
actually produce (messaging-app recompression, bursts, soft focus, wide-gamut exports). It
cannot say whether two real shots count as "the same moment" or which a person prefers;
that needs a hand-labelled set of real photos.
"""
from __future__ import annotations

import io
import os
import random
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from dev.make_demo_library import _font, make_document, make_scene, save_jpeg

from . import truth as truthmod

SIZES = {"tiny": 1, "small": 2, "medium": 6}  # multiplier on the per-family counts below
BASE_EDGE = 1600
SOURCE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}

# A blur of this many pixels (Gaussian sigma on a 1600 px picture) is clearly soft; below
# the lower bound it looks sharp; between them people disagree, so it is left unscored.
SHARP_MAX_SIGMA = 1.2
BLURRY_MIN_SIGMA = 4.0
BLUR_LEVELS = (0.0, 0.6, 1.2, 2.0, 3.0, 4.0, 6.0, 10.0, 20.0)


def _real_bases(folder: Path, rng: random.Random) -> list[Path]:
    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in SOURCE_EXTS)
    rng.shuffle(files)
    return files


def _load_real(path: Path) -> Image.Image:
    import pillow_heif

    pillow_heif.register_heif_opener()
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((BASE_EDGE, BASE_EDGE), Image.Resampling.LANCZOS)
        return img.copy()


def _gradient(rng: np.random.RandomState, w: int = BASE_EDGE, h: int = 1200) -> Image.Image:
    """A near-empty picture (a sky, a wall). Such images trick perceptual hashes into
    calling unrelated pictures alike, and trip naive blur detectors."""
    a, b = rng.randint(30, 230, 3), rng.randint(30, 230, 3)
    t = np.linspace(0, 1, h if rng.rand() < 0.5 else w)
    ramp = (a[None, :] * (1 - t[:, None]) + b[None, :] * t[:, None])
    arr = np.broadcast_to(ramp[:, None, :], (len(t), w if len(t) == h else h, 3))
    return Image.fromarray(np.ascontiguousarray(arr).astype("uint8"))


def screenshot_like(rng: np.random.RandomState) -> Image.Image:
    """A phone screen with its own layout each time. (The demo library's screenshot
    template is identical from one to the next, which would make every screenshot a
    'near duplicate' of the others and test the template rather than the engine.)"""
    w, h = 1170, 2532
    dark = rng.rand() < 0.5
    bg = tuple(int(c) for c in (rng.randint(8, 40, 3) if dark else rng.randint(215, 252, 3)))
    ink = (235, 235, 240) if dark else (22, 22, 26)
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    d.text((60, 40), f"{rng.randint(1, 12)}:{rng.randint(10, 59)}", fill=ink, font=_font(56))
    d.rectangle([0, 150, w, int(150 + rng.randint(120, 520))], fill=tuple(int(c) for c in rng.randint(0, 255, 3)))
    y = 800
    while y < h - 200:
        height = int(rng.randint(120, 480))
        shade = tuple(int(min(255, max(0, c + rng.randint(-45, 45)))) for c in bg)
        left, right = int(rng.randint(30, 200)), int(w - rng.randint(30, 400))
        d.rounded_rectangle([left, y, right, y + height], radius=int(rng.randint(8, 60)), fill=shade)
        if rng.rand() < 0.7:
            d.text((left + 30, y + 24), "".join(chr(97 + int(c)) for c in rng.randint(0, 26, int(rng.randint(6, 22)))),
                   fill=ink, font=_font(int(rng.randint(34, 70))))
        y += height + int(rng.randint(30, 120))
    return img


def recompress(img: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def centre_crop(img: Image.Image, keep: float) -> Image.Image:
    w, h = img.size
    cw, ch = int(w * keep), int(h * keep)
    left, top = (w - cw) // 2, (h - ch) // 2
    return img.crop((left, top, left + cw, top + ch))


def shallow_focus(img: Image.Image, rng: random.Random) -> Image.Image:
    """Portrait-mode look: a sharp subject over a deliberately soft background."""
    w, h = img.size
    soft = img.filter(ImageFilter.GaussianBlur(9))
    mask = Image.new("L", (w, h), 0)
    cx, cy = int(w * rng.uniform(0.35, 0.65)), int(h * rng.uniform(0.4, 0.6))
    ImageDraw.Draw(mask).ellipse([cx - w // 5, cy - h // 4, cx + w // 5, cy + h // 4], fill=255)
    return Image.composite(img, soft, mask.filter(ImageFilter.GaussianBlur(40)))


class _Builder:
    def __init__(self, out: Path, seed: int, source: Path | None, size: int) -> None:
        self.out = out
        self.size = size
        self.pyrng = random.Random(seed)
        self.nprng = np.random.RandomState(seed)
        self.real = _real_bases(source, self.pyrng) if source else []
        if source and not self.real:
            raise SystemExit(f"No photos found under {source}")
        self.cursor = 0
        self.number = 4000
        self.clock = datetime(2024, 5, 4, 9, 0, 0)
        self.truth = truthmod.Truth(
            name=out.name,
            source="real-bases" if source else "synthetic",
            tasks=["near_duplicates", "keeper", "flags"],
            content_reliable=bool(source),
        )
        self.group_count = 0

    # -- plumbing --------------------------------------------------------

    def tick(self, seconds: int | None = None) -> datetime:
        self.clock += timedelta(seconds=seconds if seconds is not None else self.pyrng.randint(1800, 40000))
        return self.clock

    def base(self) -> Image.Image:
        if self.real:
            path = self.real[self.cursor % len(self.real)]
            self.cursor += 1
            return _load_real(path)
        return make_scene(self.nprng, BASE_EDGE, 1200)

    def save(self, img: Image.Image, note: str, when: datetime | None = None, png: bool = False) -> str:
        """Writes the picture under a neutral name and returns its relative path."""
        self.number += 1
        rel = f"Camera Roll/IMG_{self.number}.{'png' if png else 'jpg'}"
        target = self.out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if png:
            img.save(target)
            ts = (when or self.tick()).timestamp()
            os.utime(target, (ts, ts))
        else:
            save_jpeg(img, target, when or self.tick())
        self.truth.notes[rel] = note
        return rel

    def group(self, kind: str, members: list[str], best: list[str], *tags: str) -> None:
        self.group_count += 1
        self.truth.groups.append(truthmod.Group(
            id=f"g{self.group_count}", kind=kind, members=members, best=best, tags=list(tags)))

    # -- families --------------------------------------------------------

    def bursts(self, n: int) -> None:
        """Rapid shots of one moment: a few pixels of drift and a hint of exposure change."""
        for _ in range(n):
            base, start = self.base(), self.tick()
            members = []
            for k in range(self.pyrng.randint(3, 6)):
                shot = base if k == 0 else ImageEnhance.Brightness(ImageChops.offset(
                    base, self.pyrng.randint(-7, 7), self.pyrng.randint(-7, 7))).enhance(1 + self.pyrng.uniform(-0.04, 0.04))
                members.append(self.save(shot, "burst frame", start + timedelta(seconds=k)))
            self.group("near", members, members, "burst")

    def resaved_copies(self, n: int) -> None:
        """The original plus the smaller, recompressed copy a messaging app produces."""
        for _ in range(n):
            base = self.base()
            original = self.save(base, "original")
            small = base.resize((int(base.width * 0.6), int(base.height * 0.6)), Image.Resampling.LANCZOS)
            copy = self.save(recompress(small, self.pyrng.randint(35, 60)), "messaging-app copy (60%, JPEG q35-60)")
            self.group("near", [original, copy], [original], "recompressed")

    def crops(self, n: int) -> None:
        for _ in range(n):
            base = self.base()
            full = self.save(base, "original")
            cropped = self.save(centre_crop(base, self.pyrng.uniform(0.88, 0.94)), "centre crop 88-94%")
            self.group("near", [full, cropped], [full, cropped], "crop")

    def exposure(self, n: int) -> None:
        for _ in range(n):
            base = self.base()
            good = self.save(base, "original")
            dark = self.save(ImageEnhance.Brightness(base).enhance(self.pyrng.uniform(0.55, 0.7)), "underexposed by 30-45%")
            self.group("near", [good, dark], [good], "exposure")

    def sharp_small_vs_blurry_big(self, n: int) -> None:
        """The case a resolution-first rule gets wrong: the large copy is soft, the small one crisp."""
        for _ in range(n):
            base = self.base()
            big_soft = self.save(base.filter(ImageFilter.GaussianBlur(4.5)), "full size, soft focus (sigma 4.5)")
            small_sharp = self.save(
                base.resize((int(base.width * 0.55), int(base.height * 0.55)), Image.Resampling.LANCZOS),
                "55% size, sharp")
            self.group("near", [big_soft, small_sharp], [small_sharp], "contested", "blur-vs-resolution")
            self.truth.flags.setdefault(big_soft, []).append("blurry")

    def exact_copies(self, n: int) -> None:
        for _ in range(n):
            original = self.save(self.base(), "original")
            self.number += 1
            copy_rel = f"Camera Roll/IMG_{self.number}.jpg"
            shutil.copy2(self.out / original, self.out / copy_rel)
            self.truth.notes[copy_rel] = "byte-identical copy"
            self.group("exact", [original, copy_rel], [original, copy_rel], "exact")

    def singles(self, n: int) -> None:
        for _ in range(n):
            self.save(self.base(), "unique picture")

    def plain_pictures(self, n: int) -> None:
        """Skies and walls: sharp, but nearly empty. They must neither merge nor look blurry."""
        for _ in range(n):
            self.save(_gradient(self.nprng), "near-empty gradient (sharp)")

    def blur_ladder(self, per_level: int) -> None:
        for sigma in BLUR_LEVELS:
            for _ in range(per_level):
                img = self.base()
                if sigma:
                    img = img.filter(ImageFilter.GaussianBlur(sigma))
                rel = self.save(img, f"Gaussian blur sigma {sigma}")
                if sigma >= BLURRY_MIN_SIGMA:
                    self.truth.flags.setdefault(rel, []).append("blurry")
                elif sigma > SHARP_MAX_SIGMA:
                    self.truth.unsure.setdefault(rel, []).append("blurry")

    def shallow_focus_shots(self, n: int) -> None:
        for _ in range(n):
            self.save(shallow_focus(self.base(), self.pyrng), "sharp subject, soft background (not blurry)")

    def screenshots(self, n: int) -> None:
        for _ in range(n):
            rel = self.save(screenshot_like(self.nprng), "phone screenshot (PNG, no camera tag)", png=True)
            self.truth.flags.setdefault(rel, []).append("screenshot")
        for _ in range(max(1, n // 3)):  # some phones save screenshots as JPEG
            rel = self.save(screenshot_like(self.nprng), "phone screenshot saved as JPEG, no camera tag")
            self.truth.flags.setdefault(rel, []).append("screenshot")
            path = self.out / rel
            Image.open(path).convert("RGB").save(path, "JPEG", quality=90)  # drops the camera tag

    def edited_exports(self, n: int) -> None:
        """Real photos re-saved as PNG with no camera tag: not screenshots, but they look like one."""
        for _ in range(n):
            self.save(self.base(), "photo exported as PNG (not a screenshot)", png=True)

    def documents(self, n: int) -> None:
        for _ in range(n):
            rel = self.save(make_document(self.nprng), "photographed receipt")
            self.truth.flags.setdefault(rel, []).append("document")


def build(out: Path, size: str = "small", seed: int = 11, source: Path | None = None) -> truthmod.Truth:
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; choose a new folder so a dataset is never mixed with other files")
    mult = SIZES[size]
    b = _Builder(out, seed, source, mult)
    b.singles(8 * mult)
    b.plain_pictures(4 * mult)
    b.bursts(3 * mult)
    b.resaved_copies(3 * mult)
    b.crops(2 * mult)
    b.exposure(2 * mult)
    b.sharp_small_vs_blurry_big(2 * mult)
    b.exact_copies(2 * mult)
    b.blur_ladder(2 * mult)
    b.shallow_focus_shots(2 * mult)
    b.screenshots(3 * mult)
    b.edited_exports(2 * mult)
    b.documents(2 * mult)
    truthmod.save(b.truth, out)
    truthmod.load(out)  # prove what we wrote is valid
    return b.truth
