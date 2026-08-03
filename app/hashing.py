from __future__ import annotations

import hashlib
from pathlib import Path

import imagehash
from PIL import Image

CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def perceptual_hash(image: Image.Image) -> str:
    return str(imagehash.phash(image))


def hash_distance(hash_a: str, hash_b: str) -> int:
    return imagehash.hex_to_hash(hash_a) - imagehash.hex_to_hash(hash_b)
