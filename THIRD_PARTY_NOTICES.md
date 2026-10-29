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
| ONNX Runtime | MIT | Runs the recognition model |
| tokenizers, huggingface_hub | Apache-2.0 | Turns a search phrase into the numbers the model reads |
| reverse_geocoder | LGPL-2.1 (per its GitHub licence file; its PyPI metadata says only "lgpl") | Names the place a photo was taken, offline |

## Libraries bundled inside the pillow-heif Windows wheel

| Component | Licence |
| --- | --- |
| libheif | LGPL-3.0 |
| libde265 | LGPL-3.0 |
| x265 | GPL-2.0-or-later (see below) |

x265 is a video encoder that Photo Organizer never calls; it is present only because the
upstream wheel includes it. The wheel's own licence note says just "GPLv2", and x265's
`COPYING` file is the plain GPL version 2 text, but the licence notice at the top of x265's
source files (checked in `encoder.cpp` and `frame.cpp` on the `master` branch) grants "version 2
of the License, or (at your option) any later version". Code under GPL-2.0-or-later may be
combined into a GPL-3.0 work, so shipping the wheel unchanged is consistent with this project's
licence. x265's source is at <https://bitbucket.org/multicoreware/x265_git> (the wheel bundles
release 3.4; its `LICENSES_bundled.txt` links the exact tree), and libheif and libde265 are
LGPL-3.0, whose source is linked in the same file.

This was settled by reading the licence headers, not by legal advice. Two things are still to
confirm before a Store release: that the headers of the exact x265 version inside the wheel say
the same as `master`, and what the Store's publisher agreement requires of GPL software.

## Data

| Component | Licence | Used for |
| --- | --- | --- |
| GeoNames cities (bundled with reverse_geocoder) | Creative Commons Attribution (confirm the exact version), attribution to [geonames.org](https://www.geonames.org) | Place names for trips |
| CLIP ViT-B/32 (OpenAI), converted to ONNX, downloaded by Setup | MIT | Recognising what is in a photo, and search |

## Interface assets (bundled in `app/web/static`)

| Component | Licence | File |
| --- | --- | --- |
| Preact and Preact hooks | MIT | `js/vendor/LICENSE-preact.txt` |
| @preact/signals | MIT | `js/vendor/LICENSE-signals.txt` |
| htm | Apache-2.0 | `js/vendor/LICENSE-htm.txt` |
| Lucide icons | ISC | `icons/LICENSE-lucide.txt` |
| Figtree font | SIL Open Font License 1.1 | `fonts/OFL-Figtree.txt` |

## Development tools (not installed for users)

PyTorch (BSD-3-Clause and others), Transformers (Apache-2.0) and ONNX (Apache-2.0) are used only to
convert the recognition model and to check the conversion (`dev/requirements-dev.txt`).

## Not checked yet

- reverse_geocoder is a library used unmodified, which LGPL-2.1 allows inside a GPL-3.0 program; the
  GeoNames data it carries needs the attribution given above (confirm whether the bundled 2016
  extract is CC BY 3.0 or 4.0).
- Licences of any model that replaces CLIP in a later release. Models with research-only
  weights (for example MobileCLIP2) are not to be used.
