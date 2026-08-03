from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol

import numpy as np

from . import video_frames
from .indexer import looks_like_screenshot

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"

# Must be set before transformers/huggingface_hub are imported anywhere - keeps
# every model file (including any auxiliary ones a model pulls in) inside the
# project folder instead of the default ~/.cache/huggingface, so the whole
# install stays self-contained and portable as one folder.
os.environ.setdefault("HF_HOME", str(MODELS_DIR))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

log = logging.getLogger(__name__)

# Confidence (softmax probability) the winning category needs to clear before we
# recommend it - anything under this is treated as "other" (not flagged). Chosen
# from empirical testing: correct classifications scored 0.62-0.76, an incorrect
# ambiguous one scored 0.38, so 0.5 sits cleanly between them.
CATEGORY_CONFIDENCE_THRESHOLD = 0.5

CATEGORY_PROMPTS: dict[str, str] = {
    "food": "a photo of food or a meal",
    "screenshot": "a screenshot of a phone or computer screen",
    "document": "a photo of a receipt or document with printed text",
    "meme": "a meme or social media image with a bold text caption",
    "whiteboard": "a photo of a whiteboard or handwritten notes",
    "blank": "a blank, dark, or accidental photo with no clear subject",
}
OTHER_PROMPT = "a normal photograph of a person, place, or thing"

PERSON_PROMPT = "a photo that includes at least one person"
NO_PERSON_PROMPT = "a photo with no people in it"

CATEGORY_LABELS: dict[str, str] = {
    "food": "Food",
    "screenshot": "Screenshot",
    "document": "Document/Receipt",
    "meme": "Meme/Social media image",
    "whiteboard": "Whiteboard/Notes",
    "blank": "Blank/Accidental shot",
}


class VisionBackend(Protocol):
    """Anything that can answer the two questions content tagging needs. CLIP
    (below) is the only implementation."""

    def classify_category(self, image) -> tuple[str | None, float]:
        """Returns (category_key, confidence) or (None, confidence) if nothing
        cleared the threshold."""
        ...

    def detect_person(self, image) -> tuple[bool, float]:
        """Returns (has_person, confidence)."""
        ...

    def embed_image(self, image) -> np.ndarray:
        """Returns an L2-normalized embedding vector for a photo/frame, used for
        free-text content search."""
        ...


class ClipBackend:
    MODEL_NAME = "openai/clip-vit-base-patch32"

    def __init__(self, local_files_only: bool = True) -> None:
        import torch
        from transformers import CLIPModel, CLIPProcessor

        # Live-detected, not based on which wheel (requirements-cpu.txt vs
        # requirements-gpu.txt) happened to be installed at setup time - this
        # is what makes GPU support self-healing: an outdated CUDA channel or
        # a driver that stopped working just falls back to CPU here instead
        # of breaking.
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        self.model = CLIPModel.from_pretrained(
            self.MODEL_NAME, cache_dir=str(MODELS_DIR), use_safetensors=True, local_files_only=local_files_only
        )
        self.processor = CLIPProcessor.from_pretrained(
            self.MODEL_NAME, cache_dir=str(MODELS_DIR), local_files_only=local_files_only
        )
        self.model = self.model.to(self.device)
        self.model.eval()
        self._category_keys = list(CATEGORY_PROMPTS.keys())
        self._category_labels = [CATEGORY_PROMPTS[k] for k in self._category_keys] + [OTHER_PROMPT]

    def _best_match(self, image, labels: list[str]) -> tuple[int, float]:
        import torch

        inputs = self.processor(text=labels, images=image, return_tensors="pt", padding=True)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = self.model(**inputs)
        probs = outputs.logits_per_image.softmax(dim=1)[0]
        best_idx = int(probs.argmax())
        return best_idx, float(probs[best_idx])

    def classify_category(self, image) -> tuple[str | None, float]:
        idx, confidence = self._best_match(image, self._category_labels)
        if idx == len(self._category_keys):  # matched the "other" label
            return None, confidence
        if confidence < CATEGORY_CONFIDENCE_THRESHOLD:
            return None, confidence
        return self._category_keys[idx], confidence

    def detect_person(self, image) -> tuple[bool, float]:
        idx, confidence = self._best_match(image, [PERSON_PROMPT, NO_PERSON_PROMPT])
        return idx == 0, confidence

    def _normalized(self, vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.astype(np.float32)

    def embed_image(self, image) -> np.ndarray:
        import torch

        inputs = self.processor(images=image, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            features = self.model.get_image_features(**inputs)
        return self._normalized(features[0].cpu().numpy())

    def embed_text(self, text: str) -> np.ndarray:
        import torch

        inputs = self.processor(text=[text], return_tensors="pt", padding=True)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            features = self.model.get_text_features(**inputs)
        return self._normalized(features[0].cpu().numpy())

    def match_probabilities(self, query: str, embeddings: np.ndarray) -> np.ndarray:
        """P(this embedding actually depicts `query`) for each row of `embeddings`
        (L2-normalized image or video-frame embeddings) - free-text search should
        use this, not a raw top-K by cosine similarity against the query alone.

        Raw CLIP cosine similarity has no fixed, library-independent meaning: the
        "modality gap" between CLIP's text and image embedding cones (Liang et al.,
        "Mind the Gap", NeurIPS 2022) compresses every query's scores into a narrow,
        query-dependent band, so a similarity number that looks like a strong match
        for one query can look identical to pure noise for another - there's no
        universal cutoff to pick. What CLIP's own authors validated at scale is the
        opposite move: pit each candidate against another candidate and take a
        softmax (see the official zero-shot examples at github.com/openai/CLIP,
        `(100 * image_features @ text_features.T).softmax(dim=-1)`) - the same
        paired-comparison pattern this module already uses for category tagging and
        person detection (`_best_match`). This mirrors that: the query is paired
        against an explicit negation of itself, scaled by the model's own learned
        logit_scale (as HF's CLIPModel does internally for `logits_per_image`), so
        a query with no real match in the library correctly nets zero results
        instead of being padded out with the least-bad guesses.
        """
        pos = self.embed_text(f"a photo of {query}")
        neg = self.embed_text(f"a photo of something other than {query}")
        text = np.stack([pos, neg])  # (2, d)
        logit_scale = float(self.model.logit_scale.exp().item())
        logits = logit_scale * (embeddings @ text.T)  # (n, 2)
        logits -= logits.max(axis=1, keepdims=True)  # numerically stable softmax
        exp = np.exp(logits)
        probs = exp / exp.sum(axis=1, keepdims=True)
        return probs[:, 0]


def download_models() -> None:
    """One-time setup step - the only place content tagging touches the network.
    Every other call in this module runs with local_files_only=True."""
    from transformers import CLIPModel, CLIPProcessor

    log.info("Downloading content-tagging model (one-time, ~600MB)...")
    CLIPModel.from_pretrained(ClipBackend.MODEL_NAME, cache_dir=str(MODELS_DIR), use_safetensors=True)
    CLIPProcessor.from_pretrained(ClipBackend.MODEL_NAME, cache_dir=str(MODELS_DIR))
    log.info("Content-tagging model ready.")


def models_downloaded() -> bool:
    return MODELS_DIR.exists() and any(MODELS_DIR.rglob("*.safetensors"))


def gpu_available() -> bool:
    """Live hardware/driver check, not a record of what was requested at setup
    time - lets the UI show accurate GPU/CPU status without constructing a
    full ClipBackend (which loads the model)."""
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False


def _add_recommendation(conn, photo_id: int, reason: str, confidence: float) -> None:
    existing = conn.execute(
        "SELECT id FROM recommendations WHERE photo_id = ? AND reason = ?", (photo_id, reason)
    ).fetchone()
    if existing:
        return  # a prior decision (e.g. 'rejected') survives - don't re-flag it
    conn.execute(
        "INSERT INTO recommendations (photo_id, reason, confidence, decision) VALUES (?, ?, ?, 'pending')",
        (photo_id, reason, confidence),
    )


def run_content_tagging(conn, backend: VisionBackend) -> dict:
    from PIL import Image, ImageOps

    # (has_person IS NULL OR clip_embedding IS NULL) rather than just has_person IS
    # NULL: on a library that was already scanned before clip_embedding existed,
    # every photo already has has_person set, so a plain "IS NULL" check would
    # permanently skip backfilling embeddings for them. Recomputing category/person
    # for an already-tagged photo is harmless (deterministic) and keeps this simple.
    rows = conn.execute(
        "SELECT id, path, camera_model FROM photos WHERE status = 'active' AND media_type = 'photo' AND error IS NULL "
        "AND (has_person IS NULL OR clip_embedding IS NULL)"
    ).fetchall()

    stats = {"tagged": 0, "flagged": 0, "errors": 0}
    for row in rows:
        try:
            with Image.open(row["path"]) as img:
                img = ImageOps.exif_transpose(img).convert("RGB")
                # Metadata beats a vision-model guess when it can answer at all -
                # see looks_like_screenshot's docstring - so it takes priority and
                # skips CLIP's category pass entirely for anything it's confident
                # about (also a nice speedup: no inference needed for those).
                if looks_like_screenshot(Path(row["path"]), row["camera_model"]):
                    category, cat_confidence = "screenshot", 1.0
                else:
                    category, cat_confidence = backend.classify_category(img)
                has_person, _ = backend.detect_person(img)
                embedding = backend.embed_image(img)
        except Exception as exc:
            log.warning("Failed to tag %s: %s", row["path"], exc)
            stats["errors"] += 1
            continue

        conn.execute(
            "UPDATE photos SET content_tags = ?, has_person = ?, clip_embedding = ? WHERE id = ?",
            (category, 1 if has_person else 0, embedding.tobytes(), row["id"]),
        )
        if category:
            _add_recommendation(conn, row["id"], category, cat_confidence)
            stats["flagged"] += 1

        stats["tagged"] += 1
        if stats["tagged"] % 100 == 0:
            conn.commit()
            log.info("Tagged %d photos so far...", stats["tagged"])

    conn.commit()
    return stats


def run_video_frame_embedding(conn, backend: VisionBackend, interval_seconds: float) -> dict:
    """Samples frames from each active video not yet embedded and stores a CLIP
    embedding per frame in video_frame_embeddings, for content search. Idempotent -
    a video with any existing frame rows is skipped, so re-running after changing
    the interval only affects videos indexed since the change."""
    rows = conn.execute(
        """
        SELECT id, path FROM photos
        WHERE status = 'active' AND media_type = 'video' AND error IS NULL
        AND NOT EXISTS (SELECT 1 FROM video_frame_embeddings WHERE photo_id = photos.id)
        """
    ).fetchall()

    stats = {"videos": 0, "frames": 0, "errors": 0}
    for row in rows:
        try:
            frame_rows = [
                (row["id"], offset, backend.embed_image(frame).tobytes())
                for offset, frame in video_frames.iter_sampled_frames(Path(row["path"]), interval_seconds)
            ]
        except Exception as exc:
            log.warning("Failed to embed video %s: %s", row["path"], exc)
            stats["errors"] += 1
            continue

        if not frame_rows:
            stats["errors"] += 1
            continue

        conn.executemany(
            "INSERT INTO video_frame_embeddings (photo_id, offset_seconds, embedding) VALUES (?, ?, ?)",
            frame_rows,
        )
        stats["videos"] += 1
        stats["frames"] += len(frame_rows)
        if stats["videos"] % 20 == 0:
            conn.commit()
            log.info("Embedded %d videos so far...", stats["videos"])

    conn.commit()
    return stats
