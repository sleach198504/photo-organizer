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
- grouping by recognition-model embeddings (the idea of verifying or replacing the hash, which would also
  catch crops). Measured 2026-10-29: on the generated scenes, unrelated pictures reach cosine similarity
  0.975 while real edited copies start at 0.934 (crops at 0.984), so no threshold separates them. The
  recognition model sees all abstract shapes as alike, so this says nothing about photographs; it has to be
  tested on Copydays or hand-labelled photos before the app relies on it;
- speed on a typical laptop. Numbers are from the machine named in each report.

A hand-labelled set of real photos is needed for those, and the labelling tool below builds it.

## Labelling your own photos

Three commands, then an hour or so of clicking for about 400 photos. Your photo folder is only
read. Finished photos are copied into `eval_data/<name>/`, which is git-ignored and stays on this PC.

```
venv\Scripts\python.exe -m dev.evalkit prepare "D:\Photos" --name mine --count 400
venv\Scripts\python.exe -m dev.evalkit label mine
venv\Scripts\python.exe -m dev.evalkit export mine
```

`prepare` reads the folder (slow on a big library; a re-run resumes) and picks a mixed sample:
about 45% sets that might be the same moment, found with a deliberately looser test than the
app uses (so look-alikes the app would miss are included); about 20% single photos spread
across the sharpness range, weighted towards the soft end; and about 35% ordinary photos with no
look-alike or neighbour anywhere in the library. Because the sample is enriched, absolute rates
will not match your whole library; use it to compare one engine with another.

`label` opens a page at `http://127.0.0.1:8767/`. It never shows the app's own opinions, so the
labels are yours. For each set of photos:

1. Select the photos that are the same moment (click or Space) and press **G** to group them.
2. Press **B** on every photo you would be happy to keep from a group.
3. Press **0-6** for what a photo is (ordinary, food, screenshot, document, meme, whiteboard,
   blank) and **E** for blurry or **N** for borderline. Press **Z** to see a photo at 100%.
4. Press **Enter** to finish the set. Anything you did not touch counts as sharp and ordinary.

Sets you finish are saved at once (the page shows "Saved"), **Ctrl+Z** undoes, and you can stop
and resume any time. The **Search terms** tab lets you add things you would really type, such as
"birthday cake", and click every finished photo that matches.

`export` copies the finished photos to `eval_data/mine/dataset/photos` with a `truth.json`, adding
byte-identical copies automatically from the file hashes. Score the engine with
`python -m dev.evalkit run eval_data\mine\dataset\photos`.

## Public benchmarks

For private testing only. These datasets are copyrighted or non-commercial, so keep them under
`eval_data/` (git-ignored) and never commit or ship them. The importers write a `truth.json` into the
folder you extracted the dataset to and never change the photos.

| Dataset | Tests | Get it | Then |
| --- | --- | --- | --- |
| CERTH Image Blur (training folders plus spreadsheet-labelled evaluation sets) | the blurry flag on real photos | [zip, 4 GB](http://mklab.iti.gr/files/imageblur/CERTH_ImageBlurDataset.zip) | `import certh <folder>` then `run <folder> --no-content --no-sweep` |
| INRIA Copydays | grouping of edited copies of one photo, and which copy to keep | [originals, 218 MB](https://dl.fbaipublicfiles.com/vissl/datasets/copydays_original.tar.gz) and [strong attacks, 63 MB](https://dl.fbaipublicfiles.com/vissl/datasets/copydays_strong.tar.gz), extracted into one folder | `import copydays <folder>` then `run <folder> --no-content` |

CERTH has natural blur (real photos, the fair test) and artificial blur (digitally added). By default only
the natural blur is scored; the artificial images are left out of the numbers. `--include all` scores both.
The importer decides sharp or blurred from the folder names (Undistorted, Naturally-Blurred,
Artificially-Blurred) and stops with the names it did not recognise rather than guessing.

Copydays groups each original with its attacked copies by file number, and counts the original as the
keeper. The strong attacks (print and scan, heavy blur, painting-like edits) are meant to be hard, so
a low recall there is expected for any hash-based method; what matters is the change between engines.

## Real-photo results: CERTH blur (2026-10-29)

CERTH has a training set (folders named by label) and an independent evaluation set whose labels are in
spreadsheets (+1 blurred, -1 clear); the importer reads both. Naturally blurred photos scored against 1,249
clear ones (the digitally blurred images are left out). The full run is in
`docs/baselines/certh-natural_current.md`.

**The blurry flag is precise but finds few of the blurred photos.** At the app's library-relative cut-off
it was right every time it flagged a photo (100% precision) but found 4.4% of the blurred ones (631 blurred
photos make up a quarter of this set, which pushes the cut-off down). The raw score does rank them
sensibly: average precision 0.825 (0.874 on the evaluation set alone, AUC 0.893).

**Other measures did not beat it.** Eleven alternatives were tried on the same photos (global Laplacian,
spectrum share, edge steepness, contrast-normalised variants). The current "sharpest tile" score was the
best single one. A classifier trained on CERTH's training set using all twelve measures, tested on its
evaluation set, reached AUC 0.900 and AP 0.880: not enough of a gain to justify the complexity. Natural
blur here includes mild blur that overlaps the sharp photos' scores (sharp median 1,606; blurred median
236, but the blurred 75th percentile is 631), so classical measures top out near AUC 0.9.

**What the cut-off trades off.** Using real scores, in a library where some share of the photos are
blurred (mean of 20 random libraries of 1,200):

| Blurred share | Cut-off | Finds | Right when it flags | Flags |
| --- | --- | --- | --- | --- |
| 6% | 1.5 x IQR (today) | 33% | 61% | 3.2% of photos |
| 6% | 1.0 x IQR | 54% | 49% | 6.6% |
| 6% | 0.5 x IQR | 67% | 33% | 12.3% |
| 10% | 1.5 x IQR (today) | 30% | 77% | 3.9% |
| 10% | 1.0 x IQR | 51% | 68% | 7.5% |
| 10% | 0.5 x IQR | 65% | 50% | 13.1% |

A fixed score cut-off does worse than the library-relative one, because real sharpness scores differ by
orders of magnitude from photo to photo. How blurred a typical iPhone library is, and how bad a false
alarm feels, are product questions; this set only says what each setting costs.

Caveat: CERTH is 2013-era web photos, not phone photos. Treat the numbers as a check on the method, not
a forecast for your library.

## Using it to compare engines

An engine is anything that returns an `EngineResult` (`dev/evalkit/engine.py`): groups with a
keeper, flags by name, a sharpness score per photo, a category per photo, and optionally ranked
search results. The ONNX engine planned in `docs/RESEARCH.md` plugs in by producing the same
structure, and `compare` shows what changed.
