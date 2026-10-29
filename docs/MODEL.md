# The recognition model

Photo Organizer uses OpenAI's CLIP ViT-B/32 (MIT licence) to tag photos (screenshots,
documents, food, ...) and to search them by meaning. It can run two ways:

| | PyTorch (original) | ONNX Runtime (new) |
| --- | --- | --- |
| Code | `ClipBackend` in `app/content_tagging.py` | `OnnxClipBackend` in `app/onnx_clip.py` |
| Needs at run time | torch (about 4 GB installed) and transformers | onnxruntime and tokenizers (tens of MB) |
| Model files | `models/models--openai--clip-vit-base-patch32/...` (580 MB) | `models/clip-vit-b32-onnx/` (606 MB: `visual.onnx`, `text.onnx`, `tokenizer.json`, `meta.json`) |
| Chosen when | the ONNX files are missing or fail their checksum | the ONNX files are present and verified |

`content_tagging.create_backend()` makes that choice. Setup installs only the ONNX build, so an
installed app never has PyTorch; the PyTorch backend remains for development, where it is the
reference the ONNX build is checked against. With neither present, the scan skips recognition and
says so, and everything else still works.

## How the model reaches a user

1. `dev/export_clip_onnx.py` makes the four files in `models/clip-vit-b32-onnx/`.
2. `dev/make_model_manifest.py` writes `app/model_manifest.json`: each file's size and SHA-256, and the
   address Setup downloads from. The manifest ships inside the app, so a given version of the app
   only ever accepts the exact files it was tested with.
3. **Publishing (done by hand, once per model version).** Create a GitHub release with the tag the
   script printed (`model-clip-vit-b32-1`), tick **Set as a pre-release**, attach the four files, and
   publish. It must be a pre-release: `Install.bat` installs the app from the *latest* release, and a
   model release must never become that.
4. Setup runs `python -m app.model_fetch`. It downloads only files that are missing or fail their
   checksum, resumes an interrupted download, retries on connection errors, and refuses any file
   that does not match. A copy of the project that already contains `models\clip-vit-b32-onnx` (an
   offline bundle) skips the download.

A new model is a new tag and a new manifest, never a replacement of files under an existing tag.

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

## Installer (checked on the development PC)

Setup was run unattended into a scratch folder (`Setup.ps1 -InstallDir ... -Unattended -SkipIntegration
-ModelBaseUrl ...`) against a local copy of the release files:

- Fresh install: 1.7 minutes with pip's cache warm; the installed folder is 1.0 GB (PyTorch used to
  make it 4.5 GB or more). A full scan of a generated library ran on it, including recognition, with
  `torch` and `transformers` not importable.
- Upgrade from an install made by the previous version (simulated by a `torch` folder and the old
  model cache): the environment was rebuilt without PyTorch, the old model cache was removed after
  the new model verified, the ONNX files already present were kept, and the user's data was untouched.
- The pinned libraries resolve to ready-made packages for Python 3.12, 3.13 and 3.14 (not 3.11).
  Only 3.14 was actually installed from; 3.12 and 3.13 were checked by resolving and downloading.

## Not done yet

- **The first model release.** `app/model_manifest.json` points at
  `releases/download/model-clip-vit-b32-1/`, which does not exist until the four files are uploaded
  there (step 3 above). Until then Setup finishes with a note that recognition is not installed.
- **Speed on the target PC.** 31 ms per photo here (12 threads). Measured with 2 threads it was
  about 50 ms; an 8 GB CPU-only laptop has not been tried. At 100 ms per photo, 20,000 photos take
  about 35 minutes of recognition.
- **GPU.** Only the CPU path exists, by decision. DirectML is the candidate for Windows GPUs but is in
  maintenance; it needs a benchmark before adopting.
- **Microsoft Store package.** The Store build will carry the model inside the package instead of
  downloading it; that is a packaging step still to do.
