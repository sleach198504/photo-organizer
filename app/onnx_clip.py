"""CLIP running on ONNX Runtime: the same model and the same answers as the PyTorch
version, without installing PyTorch (about 4 GB) or Transformers.

The two model files and the tokenizer are produced once by dev/export_clip_onnx.py, which
checks them against the original. Nothing here touches the network.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import numpy as np
from PIL import Image

from .paths import MODELS_DIR

log = logging.getLogger(__name__)

MODEL_DIR = MODELS_DIR / "clip-vit-b32-onnx"
REQUIRED_FILES = ("visual.onnx", "text.onnx", "tokenizer.json", "meta.json")


def model_files_present(folder: Path = MODEL_DIR) -> bool:
    return all((folder / name).is_file() for name in REQUIRED_FILES)


def verify_files(folder: Path = MODEL_DIR) -> bool:
    """True when every model file matches the checksum recorded when it was exported, so a
    half-copied or damaged file is caught before it gives wrong answers."""
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        for name, expected in meta["files"].items():
            h = hashlib.sha256()
            with (folder / name).open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != expected:
                return False
        return True
    except (OSError, KeyError, ValueError):
        return False


def _softmax(logits: np.ndarray) -> np.ndarray:
    logits = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(logits)
    return exp / exp.sum(axis=1, keepdims=True)


class OnnxClipBackend:
    device = "cpu"

    def __init__(self, folder: Path = MODEL_DIR) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        from .content_tagging import CATEGORY_PROMPTS, NO_PERSON_PROMPT, OTHER_PROMPT, PERSON_PROMPT

        self.meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.log_severity_level = 3
        providers = ["CPUExecutionProvider"]
        self._visual = ort.InferenceSession(str(folder / "visual.onnx"), options, providers=providers)
        self._text = ort.InferenceSession(str(folder / "text.onnx"), options, providers=providers)

        self._tokenizer = Tokenizer.from_file(str(folder / "tokenizer.json"))
        length, pad = self.meta["context_length"], self.meta["pad_token_id"]
        self._tokenizer.enable_truncation(max_length=length)
        self._tokenizer.enable_padding(length=length, pad_id=pad, pad_token=self._tokenizer.id_to_token(pad))

        self._size = self.meta["image_size"]
        self._mean = np.array(self.meta["mean"], dtype=np.float32).reshape(3, 1, 1)
        self._std = np.array(self.meta["std"], dtype=np.float32).reshape(3, 1, 1)
        self._logit_scale = float(self.meta["logit_scale"])

        self._category_keys = list(CATEGORY_PROMPTS)
        self._category_labels = [CATEGORY_PROMPTS[k] for k in self._category_keys] + [OTHER_PROMPT]
        features = self._encode_text(self._category_labels + [PERSON_PROMPT, NO_PERSON_PROMPT])
        split = len(self._category_labels)
        self._category_text, self._person_text = features[:split], features[split:]

    # -- encoders ------------------------------------------------------------

    def _encode_text(self, texts: list[str]) -> np.ndarray:
        ids = np.array([e.ids for e in self._tokenizer.encode_batch(texts)], dtype=np.int64)
        out = self._text.run(None, {"ids": ids})[0]
        return self._unit(out)

    @staticmethod
    def _unit(vectors: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vectors, axis=-1, keepdims=True)
        return (vectors / np.where(norm > 0, norm, 1.0)).astype(np.float32)

    def preprocess(self, image: Image.Image) -> np.ndarray:
        """CLIP's own resize, centre crop and normalisation, as a (3, 224, 224) array.
        Pure CPU work with no shared state, so callers run it on worker threads."""
        img = image.convert("RGB")
        w, h = img.size
        short, long = (w, h) if w <= h else (h, w)
        new_short, new_long = self._size, int(self._size * long / short)
        new_w, new_h = (new_short, new_long) if w <= h else (new_long, new_short)
        img = img.resize((new_w, new_h), Image.Resampling.BICUBIC)
        left, top = (new_w - self._size) // 2, (new_h - self._size) // 2
        img = img.crop((left, top, left + self._size, top + self._size))
        arr = np.asarray(img, dtype=np.float32).transpose(2, 0, 1) / 255.0
        return (arr - self._mean) / self._std

    def _encode_images(self, pixels: np.ndarray) -> np.ndarray:
        return self._unit(self._visual.run(None, {"pixels": pixels.astype(np.float32)})[0])

    # -- what the scan and search use ----------------------------------------

    def analyze_batch(self, images: list) -> list[dict]:
        from .content_tagging import CATEGORY_CONFIDENCE_THRESHOLD

        if not images:
            return []
        pixels = np.stack([i if isinstance(i, np.ndarray) else self.preprocess(i) for i in images])
        feats = self._encode_images(pixels)
        category_probs = _softmax(self._logit_scale * feats @ self._category_text.T)
        person_probs = _softmax(self._logit_scale * feats @ self._person_text.T)

        other_index = len(self._category_keys)
        results = []
        for i in range(len(images)):
            idx = int(category_probs[i].argmax())
            confidence = float(category_probs[i][idx])
            keep = idx != other_index and confidence >= CATEGORY_CONFIDENCE_THRESHOLD
            results.append({
                "category": self._category_keys[idx] if keep else None,
                "confidence": confidence,
                "has_person": bool(person_probs[i].argmax() == 0),
                "embedding": feats[i],
            })
        return results

    def classify_category(self, image) -> tuple[str | None, float]:
        result = self.analyze_batch([image])[0]
        return result["category"], result["confidence"]

    def detect_person(self, image) -> tuple[bool, float]:
        feats = self._encode_images(self.preprocess(image)[None])
        probs = _softmax(self._logit_scale * feats @ self._person_text.T)[0]
        return bool(probs.argmax() == 0), float(probs.max())

    def embed_image(self, image) -> np.ndarray:
        return self._encode_images(self.preprocess(image)[None])[0]

    def embed_text(self, text: str) -> np.ndarray:
        return self._encode_text([text])[0]

    def match_probabilities(self, query: str, embeddings: np.ndarray) -> np.ndarray:
        """P(this embedding depicts `query`), as in ClipBackend: the query is pitted against
        an explicit negation of itself, so a query with no real match returns nothing."""
        text = self._encode_text([f"a photo of {query}", f"a photo of something other than {query}"])
        probs = _softmax(self._logit_scale * (embeddings @ text.T))
        return probs[:, 0]
