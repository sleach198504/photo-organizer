# Evaluation harness

Every threshold in the engine (the similarity distance, the sharpness cut-off, the 0.5 category
confidence) was tuned by eye on a handful of pictures. This harness replaces guesswork with
numbers: it runs the engine over a dataset whose right answers are known, scores it, and lets
us compare one version of the engine with the next.

It lives in `dev/evalkit`. Nothing in the app imports it.

## Quick start

```
venv\Scripts\python.exe -m dev.evalkit synth C:\scratch\ds --size small
venv\Scripts\python.exe -m dev.evalkit run C:\scratch\ds
venv\Scripts\python.exe -m dev.evalkit compare before.json after.json
```

- `synth` builds a folder of pictures plus `truth.json` (sizes: tiny ~75 pictures, small ~150,
  medium ~450). The same `--seed` always builds the same dataset. `--from <your photos>` uses
  your own photos as the starting pictures instead of generated scenes; the result stays on your
  PC and is git-ignored if you put it in `eval_data/`.
- `run` drives the app's real pipeline stages against a throwaway database (your real library
  and settings are never touched), scores the result, prints a report, and saves JSON and
  Markdown to `eval_runs/`. `--no-content` skips the recognition model; `--no-sweep` skips the
  threshold sweep.
- `compare` prints the headline numbers from two saved runs side by side.

The first baseline is in `docs/baselines/`.

## What it measures

| Area | Scores |
| --- | --- |
| Exact copies | Pairwise precision, recall, F1 |
| Similar photos | Pairwise precision, recall, F1; B-cubed precision and recall; sets that merged different moments; moments split across sets; largest set; a sweep over every Hamming distance from 0 to 14 |
| Which photo to keep | Right pick, overall and by case (`burst`, `recompressed`, `crop`, `exposure`, and the deliberately `contested` blur-versus-resolution case); groups the engine never formed are counted separately |
| Flags (blurry, screenshot, document, ...) | Precision, recall, false alarms and misses by name; for blurry, also ranking average precision, which judges the raw score independent of the cut-off |
| Categories | Accuracy, per-category precision and recall, confusion matrix (needs labelled real photos) |
| Search | recall at 1, 5 and 10, and mean reciprocal rank (needs labelled real photos) |
| Speed | Seconds and milliseconds per photo for each stage |

Precision answers "of what the app flagged, how much was right". Recall answers "of what it should
have flagged, how much did it find". For a tool that only suggests, a false alarm costs the
person a look; a miss costs the clutter staying. Both are reported rather than blended.

## The dataset format

A dataset is a folder of photos plus `truth.json` (full description in
`dev/evalkit/truth.py`). Paths are relative to the folder. Only the tasks listed in `tasks` are
scored, and for those every unmentioned photo is a negative, so list a task only when the whole
folder has been labelled for it. `unsure` removes a photo from one flag's scores when a person
could argue either way. Malformed files are rejected with a message rather than silently
skewing a score.

## What the generated dataset can and cannot tell you

Each family applies a documented change to a base picture, so the answer is known: bursts
(drift and a hint of exposure change), messaging-app copies (60% size, JPEG quality 35-60), centre
crops, underexposure, a ladder of Gaussian blur from none to heavy, shallow-focus portraits that
must not count as blurry, near-empty skies and walls, screenshots, photographed receipts, photos
re-saved as PNG, and byte-identical copies.

It is good at: regressions, threshold behaviour, and how the engine copes with edits people
really produce. It is **not** evidence about:

- whether two real shots count as the same moment, or which one a person prefers;
- recognition (food, documents, memes, search). The recognition model is built for photographs
  and mislabels abstract generated scenes, so these are not scored on generated pictures and the
  report says so;
- speed on a typical laptop. Numbers are from the machine named in each report.

A hand-labelled set of real photos is still needed for those; the format above already supports
it (groups with acceptable keepers, flags, categories, search queries). A labelling tool is the
next piece of work.

## Using it to compare engines

An engine is anything that returns an `EngineResult` (`dev/evalkit/engine.py`): groups with a
keeper, flags by name, a sharpness score per photo, a category per photo, and optionally ranked
search results. The ONNX engine planned in `docs/RESEARCH.md` plugs in by producing the same
structure, and `compare` shows what changed.
