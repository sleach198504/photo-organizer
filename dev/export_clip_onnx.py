"""Converts the downloaded CLIP model to ONNX so the app can run it without PyTorch.

    venv\\Scripts\\python.exe dev\\export_clip_onnx.py [--out models\\clip-vit-b32-onnx]

A build-time developer tool: it needs torch and transformers (the old runtime), which the
installed app will no longer need. It writes
    visual.onnx    photo -> 512-number embedding
    text.onnx      tokenised text -> 512-number embedding
    tokenizer.json the text tokenizer
    meta.json      the few constants the runtime needs, and checksums
then checks the result against the original model and refuses to finish if they differ.
CLIP ViT-B/32 is MIT-licensed (OpenAI).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODEL = "openai/clip-vit-base-patch32"
OPSET = 17
PARITY_FLOOR = 0.9999  # cosine similarity between the original and exported embeddings


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "models" / "clip-vit-b32-onnx")
    args = parser.parse_args()

    import torch
    from transformers import CLIPModel, CLIPProcessor

    from app.paths import MODELS_DIR

    model = CLIPModel.from_pretrained(MODEL, cache_dir=str(MODELS_DIR), use_safetensors=True, local_files_only=True).eval()
    processor = CLIPProcessor.from_pretrained(MODEL, cache_dir=str(MODELS_DIR), local_files_only=True)
    args.out.mkdir(parents=True, exist_ok=True)

    class Visual(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.m = model

        def forward(self, pixel_values):
            return self.m.get_image_features(pixel_values=pixel_values)

    class Text(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.m = model

        def forward(self, input_ids):
            return self.m.get_text_features(input_ids=input_ids)

    pixels = torch.randn(2, 3, 224, 224)
    ids = processor.tokenizer(["a photo of a dog", "a screenshot"], padding="max_length", max_length=77,
                              return_tensors="pt")["input_ids"]

    print("Exporting the image encoder...")
    torch.onnx.export(Visual().eval(), (pixels,), str(args.out / "visual.onnx"), input_names=["pixels"],
                      output_names=["embedding"], dynamic_axes={"pixels": {0: "batch"}, "embedding": {0: "batch"}},
                      opset_version=OPSET, dynamo=False)
    print("Exporting the text encoder...")
    torch.onnx.export(Text().eval(), (ids,), str(args.out / "text.onnx"), input_names=["ids"],
                      output_names=["embedding"], dynamic_axes={"ids": {0: "batch"}, "embedding": {0: "batch"}},
                      opset_version=OPSET, dynamo=False)

    tokenizer_json = next(MODELS_DIR.rglob("tokenizer.json"))
    shutil.copy2(tokenizer_json, args.out / "tokenizer.json")

    # --- prove the export matches the original ---
    import onnxruntime as ort

    options = ort.SessionOptions()
    visual = ort.InferenceSession(str(args.out / "visual.onnx"), options, providers=["CPUExecutionProvider"])
    text = ort.InferenceSession(str(args.out / "text.onnx"), options, providers=["CPUExecutionProvider"])

    def cosine(a: np.ndarray, b: np.ndarray) -> float:
        a, b = a / np.linalg.norm(a, axis=1, keepdims=True), b / np.linalg.norm(b, axis=1, keepdims=True)
        return float((a * b).sum(axis=1).min())

    with torch.no_grad():
        want_v = model.get_image_features(pixel_values=pixels).numpy()
        want_t = model.get_text_features(input_ids=ids).numpy()
    got_v = visual.run(None, {"pixels": pixels.numpy()})[0]
    got_t = text.run(None, {"ids": ids.numpy().astype(np.int64)})[0]
    cv, ct = cosine(want_v, got_v), cosine(want_t, got_t)
    print(f"Parity with the original model: image {cv:.6f}, text {ct:.6f}")
    if min(cv, ct) < PARITY_FLOOR:
        print("The exported model does not match the original closely enough; not writing meta.json.")
        return 1

    meta = {
        "source": MODEL,
        "license": "MIT (OpenAI)",
        "logit_scale": float(model.logit_scale.exp().item()),
        "image_size": 224,
        "mean": list(processor.image_processor.image_mean),
        "std": list(processor.image_processor.image_std),
        "context_length": 77,
        "pad_token_id": int(processor.tokenizer.pad_token_id),
        "files": {name: sha256(args.out / name) for name in ("visual.onnx", "text.onnx", "tokenizer.json")},
    }
    (args.out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    for name in ("visual.onnx", "text.onnx"):
        print(f"{name}: {(args.out / name).stat().st_size / 1e6:.0f} MB")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
