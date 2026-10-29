# The recognition model

Photo Organizer uses OpenAI's CLIP ViT-B/32 (MIT licence) to tag photos (screenshots,
documents, food, ...) and to search them by meaning. It can run two ways:

| | PyTorch (original) | ONNX Runtime (new) |
| --- | --- | --- |
| Code | `ClipBackend` in `app/content_tagging.py` | `OnnxClipBackend` in `app/onnx_clip.py` |
| Needs at run time | torch (about 4 GB installed) and transformers | onnxruntime and tokenizers (tens of MB) |
| Model files | `models/models--openai--clip-vit-base-patch32/...` (580 MB) | `models/clip-vit-b32-onnx/` (606 MB: `visual.onnx`, `text.onnx`, `tokenizer.json`, `meta.json`) |
| Chosen when | the ONNX files are missing or fail their checksum | the ONNX files are present and verified |

`content_tagging.create_backend()` makes that choice, so an installed copy that has only the
PyTorch model keeps working unchanged.

## Making the ONNX files

```
venv\Scripts\python.exe -m pip install -r dev\requirements-dev.txt
venv\Scripts\python.exe dev\export_clip_onnx.py
```

The script converts both halves of the model, then compares them with the original and refuses to
write `meta.json` unless the results match (cosine similarity of at least 0.9999).

## What was checked (on the development PC)

- Converted model against the original: embedding cosine similarity 1.000000 for both the image
  and the text half.
- On 64 test pictures: preprocessing identical (0.0 difference), embeddings cosine 1.000000, all 64
  category decisions and all 64 person decisions the same, largest probability difference 5e-6,
  search probabilities within 2.3e-6.
- The whole scan runs with PyTorch and Transformers blocked from importing.
- Tests in `tests/test_onnx_clip.py` cover preprocessing and tokenisation against the original
  pipeline, output ranges, and the checksum and fallback rules. They skip if the ONNX files are not
  exported on the machine.

## Decisions

- **No INT8.** Dynamic INT8 quantisation made the image model 4x smaller (89 MB) but no faster on
  this CPU (34.5 against 32.5 ms per photo), and it changed 6 of 64 category decisions
  (embedding cosine as low as 0.948). Accuracy loss with no speed gain, so FP32 stays.
- **Same model for now.** This swap changes the runtime, not the model, so results are unchanged. A
  better model (SigLIP 2 or similar) is a separate decision to make with labelled photos, using
  `docs/EVALUATION.md`.

## Not done yet

- **Installer.** Setup still downloads the PyTorch model and installs torch. It needs to ship or
  fetch the exported ONNX files instead, then drop torch and transformers from the requirements.
- **Speed on the target PC.** 31 ms per photo here (12 threads). Measured with 2 threads it was
  about 50 ms; an 8 GB CPU-only laptop has not been tried. At 100 ms per photo, 20,000 photos take
  about 35 minutes of recognition.
- **GPU.** Only the CPU path exists. DirectML is the candidate for Windows GPUs but is in
  maintenance; it needs a benchmark before adopting.
