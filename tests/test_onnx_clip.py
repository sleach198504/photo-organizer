"""The ONNX recognition backend must give the same answers as the original model."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from app import content_tagging, onnx_clip

HAVE_MODEL = onnx_clip.model_files_present()


class FileCheckTests(unittest.TestCase):
    def test_checksums_catch_damaged_or_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "visual.onnx").write_bytes(b"weights")
            (folder / "meta.json").write_text(json.dumps(
                {"files": {"visual.onnx": hashlib.sha256(b"weights").hexdigest()}}), encoding="utf-8")
            self.assertTrue(onnx_clip.verify_files(folder))
            (folder / "visual.onnx").write_bytes(b"weights, but half copied")
            self.assertFalse(onnx_clip.verify_files(folder))
            (folder / "visual.onnx").unlink()
            self.assertFalse(onnx_clip.verify_files(folder))
            self.assertFalse(onnx_clip.model_files_present(folder))

    def test_without_the_onnx_files_the_original_backend_is_the_development_fallback(self) -> None:
        with mock.patch.object(onnx_clip, "model_files_present", return_value=False), \
                mock.patch.object(content_tagging, "_torch_model_present", return_value=True), \
                mock.patch.object(content_tagging, "ClipBackend", return_value="torch-backend"):
            self.assertEqual(content_tagging.create_backend(), "torch-backend")

    def test_with_no_model_at_all_the_error_says_what_to_do(self) -> None:
        with mock.patch.object(onnx_clip, "model_files_present", return_value=False), \
                mock.patch.object(content_tagging, "_torch_model_present", return_value=False):
            with self.assertRaisesRegex(content_tagging.ModelUnavailable, "isn't installed"):
                content_tagging.create_backend()
            self.assertFalse(content_tagging.models_downloaded())

    def test_damaged_onnx_files_are_not_trusted(self) -> None:
        with mock.patch.object(onnx_clip, "model_files_present", return_value=True), \
                mock.patch.object(onnx_clip, "verify_files", return_value=False), \
                mock.patch.object(content_tagging, "_torch_model_present", return_value=False):
            with self.assertRaisesRegex(content_tagging.ModelUnavailable, "damaged"):
                content_tagging.create_backend()


@unittest.skipUnless(HAVE_MODEL, "the ONNX model files are not exported on this machine")
class BackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.backend = onnx_clip.OnnxClipBackend()
        rng = np.random.RandomState(0)
        cls.images = [Image.fromarray(rng.randint(0, 255, (h, w, 3), dtype=np.uint8)) for w, h in ((640, 480), (300, 700), (224, 224))]

    def test_preprocessing_matches_the_original_pipeline(self) -> None:
        try:
            from transformers import CLIPProcessor
        except ImportError:
            self.skipTest("transformers is not installed")
        processor = CLIPProcessor.from_pretrained(
            "openai/clip-vit-base-patch32", cache_dir=str(content_tagging.MODELS_DIR), local_files_only=True)
        for image in self.images:
            want = processor.image_processor(images=image, return_tensors="np")["pixel_values"][0]
            np.testing.assert_allclose(self.backend.preprocess(image), want, atol=1e-5)

    def test_text_tokens_match_the_original_tokenizer(self) -> None:
        try:
            from transformers import CLIPProcessor
        except ImportError:
            self.skipTest("transformers is not installed")
        processor = CLIPProcessor.from_pretrained(
            "openai/clip-vit-base-patch32", cache_dir=str(content_tagging.MODELS_DIR), local_files_only=True)
        for text in ("a photo of a dog", "A Screenshot of a PHONE screen!", "birthday cake  with candles", "x " * 100):
            want = processor.tokenizer([text], padding="max_length", max_length=77, truncation=True)["input_ids"][0]
            got = self.backend._tokenizer.encode(text).ids
            self.assertEqual(got, want, text)

    def test_batch_analysis_shapes_and_ranges(self) -> None:
        results = self.backend.analyze_batch(self.images)
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertAlmostEqual(float(np.linalg.norm(r["embedding"])), 1.0, places=4)
            self.assertEqual(r["embedding"].dtype, np.float32)
            self.assertTrue(0.0 < r["confidence"] <= 1.0)
            self.assertIn(r["category"], [None, *content_tagging.CATEGORY_PROMPTS])
        self.assertEqual(self.backend.analyze_batch([]), [])

    def test_preprocessed_arrays_and_images_give_the_same_answer(self) -> None:
        by_image = self.backend.analyze_batch(self.images)
        by_array = self.backend.analyze_batch([self.backend.preprocess(i) for i in self.images])
        for a, b in zip(by_image, by_array):
            np.testing.assert_allclose(a["embedding"], b["embedding"], atol=1e-6)

    def test_search_pits_the_query_against_its_negation(self) -> None:
        embeddings = np.stack([r["embedding"] for r in self.backend.analyze_batch(self.images)])
        probs = self.backend.match_probabilities("a dog", embeddings)
        self.assertEqual(probs.shape, (3,))
        self.assertTrue(((probs >= 0) & (probs <= 1)).all())


if __name__ == "__main__":
    unittest.main()
