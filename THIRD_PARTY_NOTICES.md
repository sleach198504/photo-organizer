# Third-party software

Photo Organizer is licensed under the GNU General Public License, version 3 (see `LICENSE`).
It is built on the open-source components below. Each keeps its own licence, whose full text
ships with the component (in the installed Python packages, or next to the file for the
bundled interface assets).

Versions are the ones pinned in `constraints.txt`. Licence names come from each package's own
metadata; where a package states more than one, all are listed.

## Python libraries (installed by Setup)

| Component | Licence | Used for |
| --- | --- | --- |
| Pillow | MIT-CMU (HPND) | Reading images, making thumbnails, colour conversion |
| pillow-heif | BSD-3-Clause (see the libraries it bundles, below) | Reading HEIC/HEIF photos |
| ImageHash | BSD-2-Clause | Finding similar photos |
| OpenCV (opencv-python-headless) | Apache-2.0 (the wheel also bundles LGPL FFmpeg) | Sharpness scoring, reading video frames |
| NumPy | BSD-3-Clause and others | Image maths |
| SciPy | BSD-3-Clause | Image maths, nearest-city lookup |
| PyWavelets | MIT / BSD-3-Clause | Used by ImageHash |
| PyYAML | MIT | Reading `config.yaml` |
| FastAPI | MIT | The local API |
| Starlette | BSD-3-Clause | Used by FastAPI |
| Pydantic | MIT | Request validation |
| Uvicorn | BSD-3-Clause | Runs the local server |
| python-multipart | Apache-2.0 | Form handling |
| PyTorch | BSD-3-Clause, Apache-2.0, MIT and others (see the package metadata) | Runs the recognition model |
| Transformers (Hugging Face) | Apache-2.0 | Loads the recognition model |
| huggingface_hub, tokenizers, safetensors | Apache-2.0 | Support for Transformers |
| reverse_geocoder | LGPL | Names the place a photo was taken, offline |

## Libraries bundled inside the pillow-heif Windows wheel

| Component | Licence |
| --- | --- |
| libheif | LGPL-3.0 |
| libde265 | LGPL-3.0 |
| x265 | GPL-2.0 (version 2 only) |

x265 is a video encoder that Photo Organizer never calls. It is present only because the
upstream wheel includes it. Because it is GPL-2.0-only it cannot be combined with
GPL-3.0 code, so it will be removed from release builds by shipping a decode-only HEIC
reader. Until then, builds that include it are not a clean GPL-3.0 distribution.

## Data

| Component | Licence | Used for |
| --- | --- | --- |
| GeoNames cities (bundled with reverse_geocoder) | Creative Commons Attribution (confirm the exact version), attribution to [geonames.org](https://www.geonames.org) | Place names for trips |
| CLIP ViT-B/32 (OpenAI), downloaded by Setup | MIT | Recognising what is in a photo, and search |

## Interface assets (bundled in `app/web/static`)

| Component | Licence | File |
| --- | --- | --- |
| Preact and Preact hooks | MIT | `js/vendor/LICENSE-preact.txt` |
| @preact/signals | MIT | `js/vendor/LICENSE-signals.txt` |
| htm | Apache-2.0 | `js/vendor/LICENSE-htm.txt` |
| Lucide icons | ISC | `icons/LICENSE-lucide.txt` |
| Figtree font | SIL Open Font License 1.1 | `fonts/OFL-Figtree.txt` |

## Not checked yet

- The exact LGPL version of reverse_geocoder, and its compatibility with GPL-3.0.
- Licences of any model that replaces CLIP in a later release. Models with research-only
  weights (for example MobileCLIP2) are not to be used.
