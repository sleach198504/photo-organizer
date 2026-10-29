# Evaluation: synthetic-small / current

Run 2026-10-29T15:33:20+00:00 on commit `cae9429` (app files modified). 151 photos. Machine: Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, 12 threads, 31.8 GB.

## Duplicates and similar photos

| Task | Precision | Recall | F1 | Missed pairs | Wrong pairs |
| --- | --- | --- | --- | --- | --- |
| Exact copies | 100.0% | 100.0% | 100.0% | 0 | 0 |
| Similar photos | 100.0% | 95.5% | 97.7% | 3 | 0 |

Photo-level (B-cubed): precision 100.0%, recall 98.0%. Sets that merged different moments: **0**. Moments split across sets: **3**. Largest set found 5 (largest real one 5).

Threshold sweep (Hamming distance; the app uses 6):

| Distance | Precision | Recall | F1 | Merged sets | Split moments | Largest set |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 100.0% | 48.5% | 65.3% | 0 | 13 | 5 |
| 1 | 100.0% | 48.5% | 65.3% | 0 | 13 | 5 |
| 2 | 100.0% | 89.4% | 94.4% | 0 | 5 | 5 |
| 3 | 100.0% | 89.4% | 94.4% | 0 | 5 | 5 |
| 4 | 100.0% | 93.9% | 96.9% | 0 | 4 | 5 |
| 5 | 100.0% | 93.9% | 96.9% | 0 | 4 | 5 |
| 6 | 100.0% | 95.5% | 97.7% | 0 | 3 | 5 |
| 7 | 100.0% | 95.5% | 97.7% | 0 | 3 | 5 |
| 8 | 100.0% | 97.0% | 98.5% | 0 | 2 | 5 |
| 9 | 100.0% | 97.0% | 98.5% | 0 | 2 | 5 |
| 10 | 98.5% | 100.0% | 99.2% | 1 | 0 | 5 |
| 11 | 98.5% | 100.0% | 99.2% | 1 | 0 | 5 |
| 12 | 98.5% | 100.0% | 99.2% | 1 | 0 | 5 |
| 13 | 98.5% | 100.0% | 99.2% | 1 | 0 | 5 |
| 14 | 98.5% | 100.0% | 99.2% | 1 | 0 | 5 |

Where grouping went wrong:

- **not grouped** (crop) Camera Roll/IMG_4064.jpg, Camera Roll/IMG_4065.jpg
- **not grouped** (crop) Camera Roll/IMG_4066.jpg, Camera Roll/IMG_4067.jpg
- **not grouped** (crop) Camera Roll/IMG_4068.jpg, Camera Roll/IMG_4069.jpg

## Which photo to keep

| Case | Groups | Right pick | Not grouped |
| --- | --- | --- | --- |
| All | 24 | 87.5% | 3 |
| blur-vs-resolution | 4 | 100.0% | 0 |
| burst | 6 | 100.0% | 0 |
| contested | 4 | 100.0% | 0 |
| crop | 4 | 25.0% | 3 |
| exposure | 4 | 100.0% | 0 |
| recompressed | 6 | 100.0% | 0 |

## Flags

| Reason | Precision | Recall | False alarms | Missed | Ranking AP |
| --- | --- | --- | --- | --- | --- |
| blurry | 100.0% | 100.0% | 0 | 0 | 100.0% |
| screenshot (PNG files only) | 66.7% | 100.0% | 3 | 0 | n/a |

Not scored here: document (they need the recognition model, which cannot be judged fairly on generated pictures; run on labelled real photos to score them).

## Speed

| Stage | Seconds | ms per photo |
| --- | --- | --- |
| index | 3.468 | 22.97 |
| sharpness | 3.118 | 20.65 |
| duplicates | 0.02 | 0.13 |
| model_load | 9.857 | 65.28 |
| content | 2.4 | 15.89 |
