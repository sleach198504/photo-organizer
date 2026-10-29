# Evaluation: synthetic-small / current

Run 2026-10-29T14:11:10+00:00 on commit `abfb758`. 151 photos. Machine: Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, 12 threads, 31.8 GB.

## Duplicates and similar photos

| Task | Precision | Recall | F1 | Missed pairs | Wrong pairs |
| --- | --- | --- | --- | --- | --- |
| Exact copies | 100.0% | 100.0% | 100.0% | 0 | 0 |
| Similar photos | 69.2% | 95.5% | 80.3% | 3 | 28 |

Photo-level (B-cubed): precision 95.4%, recall 98.0%. Sets that merged different moments: **1**. Moments split across sets: **3**. Largest set found 8 (largest real one 5).

Threshold sweep (Hamming distance; the app uses 6):

| Distance | Precision | Recall | F1 | Merged sets | Split moments | Largest set |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 91.4% | 48.5% | 63.4% | 1 | 13 | 5 |
| 1 | 84.2% | 48.5% | 61.5% | 2 | 13 | 5 |
| 2 | 78.7% | 89.4% | 83.7% | 2 | 5 | 6 |
| 3 | 78.7% | 89.4% | 83.7% | 2 | 5 | 6 |
| 4 | 68.9% | 93.9% | 79.5% | 1 | 4 | 8 |
| 5 | 68.9% | 93.9% | 79.5% | 1 | 4 | 8 |
| 6 | 69.2% | 95.5% | 80.3% | 1 | 3 | 8 |
| 7 | 69.2% | 95.5% | 80.3% | 1 | 3 | 8 |
| 8 | 69.6% | 97.0% | 81.0% | 1 | 2 | 8 |
| 9 | 69.6% | 97.0% | 81.0% | 1 | 2 | 8 |
| 10 | 69.5% | 100.0% | 82.0% | 2 | 0 | 8 |
| 11 | 69.5% | 100.0% | 82.0% | 2 | 0 | 8 |
| 12 | 69.5% | 100.0% | 82.0% | 2 | 0 | 8 |
| 13 | 69.5% | 100.0% | 82.0% | 2 | 0 | 8 |
| 14 | 69.5% | 100.0% | 82.0% | 2 | 0 | 8 |

Where grouping went wrong:

- **not grouped** (crop) Camera Roll/IMG_4064.jpg, Camera Roll/IMG_4065.jpg
- **not grouped** (crop) Camera Roll/IMG_4066.jpg, Camera Roll/IMG_4067.jpg
- **not grouped** (crop) Camera Roll/IMG_4068.jpg, Camera Roll/IMG_4069.jpg
- **includes photos that are not alike**  Camera Roll/IMG_4017.jpg, Camera Roll/IMG_4018.jpg, Camera Roll/IMG_4019.jpg, Camera Roll/IMG_4020.jpg ...

## Which photo to keep

| Case | Groups | Right pick | Not grouped |
| --- | --- | --- | --- |
| All | 24 | 70.8% | 3 |
| blur-vs-resolution | 4 | 0.0% | 0 |
| burst | 6 | 100.0% | 0 |
| contested | 4 | 0.0% | 0 |
| crop | 4 | 25.0% | 3 |
| exposure | 4 | 100.0% | 0 |
| recompressed | 6 | 100.0% | 0 |

## Flags

| Reason | Precision | Recall | False alarms | Missed | Ranking AP |
| --- | --- | --- | --- | --- | --- |
| blurry | 71.4% | 100.0% | 8 | 0 | 51.6% |
| screenshot (PNG files only) | 60.0% | 100.0% | 4 | 0 | n/a |

Not scored here: document (they need the recognition model, which cannot be judged fairly on generated pictures; run on labelled real photos to score them).

## Speed

| Stage | Seconds | ms per photo |
| --- | --- | --- |
| index | 3.547 | 23.49 |
| sharpness | 6.012 | 39.81 |
| duplicates | 0.026 | 0.17 |
| model_load | 11.36 | 75.23 |
| content | 2.778 | 18.4 |
