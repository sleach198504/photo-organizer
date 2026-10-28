# Photo Organizer: pre-implementation research pass

Date: 2026-10-28. Scope: the whole project (detection engine, AI runtime, iPhone media handling, safety model, local server security, app shell, packaging and signing, licensing, design and accessibility, performance, quality engineering).

Nothing in the app was changed. Two throwaway experiments were run against a scratch copy (results marked **[Verified here]**). This file is the only addition to the project.

## How to read the evidence

| Label | Meaning |
| --- | --- |
| **[Verified here]** | I ran it or read the code/installed files in this project |
| **[Primary]** | Read from the vendor's or maintainer's own documentation or model card |
| **[Reported]** | Secondary source: blogs, vendor marketing, forum posts. Directional only |
| **[Unverified]** | I could not confirm it. Listed in section 12 with the test that would settle it |

Many sources in this category are vendor marketing. Where a claim rests only on those, it is labelled **[Reported]**.

---

## 1. Summary: what matters most

1. **The local server accepts requests from any website. [Verified here]** There are no Host, Origin or token checks. A cross-site `POST /api/shutdown` shut my scratch server down, and a request with a forged `Host` header was served. Any web page open in the user's browser can stop the app. Because Host is not checked, a DNS-rebinding page would also be same-origin with the API and could in principle call every route (settings, marks, apply, purge); I did not run that full chain. This is cheap to fix and must be fixed before any release.
2. **The install design is the root of the "just works" problem.** Setup runs `pip` on the user's PC. The dev environment is 4.7 GB (PyTorch alone is 4.0 GB) plus a 581 MB model, the GPU/CPU question is exposed, dependencies are unpinned (`>=`), and the real installed copy runs Python 3.14.3 although Setup targets 3.12. **[Verified here]** The professional pattern is a self-contained, signed installer with no choices.
3. **Replace PyTorch and `transformers` with ONNX Runtime and one built-in model.** Licence-safe candidates: OpenAI CLIP ViT-B/32 (MIT), SigLIP 2 base (Apache-2.0), DINOv2-small for visual similarity (Apache-2.0). **Do not use MobileCLIP2:** its weights carry Apple's research-only licence. **[Primary]**
4. **Detection quality has specific, fixable weaknesses.** Near-duplicates are grouped by single-linkage on a 64-bit pHash, which chains; the "keeper" is chosen by resolution first, then sharpness; blur is a whole-image Laplacian, which mislabels portrait-mode photos; "food" and "meme" are treated as clutter. The industry norm is layered: hash, then embedding verification, then a learned quality score, then conservative suggestions with reasons.
5. **iPhone-specific realities are mostly unhandled.** Live Photos are paired by filename, not Apple's `ContentIdentifier`; edited copies (`IMG_E…`) and `.AAE` sidecars are not understood; burst IDs are unused; Display P3 colour profiles are dropped when thumbnails are rendered **[Verified here]**; HDR video frames, HEVC video playback and OneDrive placeholder files are unaddressed.
6. **The safety model is sound but has gaps.** Marks are applied once, with Undo, and a purge is confined to the review folder. Gaps: Organize cannot be undone; permanent delete is `unlink`, not the Recycle Bin; cross-drive moves are copy-then-delete. Keep the review folder (the Recycle Bin is unreliable on removable drives **[Reported]**), but add safeguards.
7. **Licensing is unresolved.** The repo has no `LICENSE`, no third-party notices and no CI. The pillow-heif wheel bundles x265 (GPLv2) and LGPLv3 libraries **[Verified here]**; `reverse_geocoder` is LGPL; OpenCV wheels bundle LGPL FFmpeg **[Reported]**; GeoNames data needs attribution.
8. **Unsigned distribution will hurt.** SmartScreen warns, and Windows 11 Smart App Control can block unsigned, unrecognised executables outright **[Primary]**. EV certificates no longer bypass SmartScreen **[Primary]**. The cheapest good options: Microsoft Store MSIX (free, auto-signed), Azure Artifact Signing ($9.99/month, US/Canada individuals), SignPath (free, open-source projects only).
9. **The app shell is adequate but limiting.** Edge `--app` works with no dependencies, but gives no native dialogs, no custom title bar and no control over the window. pywebview (WebView2, BSD) would keep the existing UI and add those.
10. **Design and accessibility are a strong base with specific gaps:** no ARIA grid semantics or roving focus on the photo grid, no forced-colors (high-contrast) pass, no automated UI tests, no CI.

---

## 2. What exists today (scope map)

| Area | State | Notes |
| --- | --- | --- |
| Frontend | Preact + htm + signals, no build step; 3,900 lines of JS and 2,800 of CSS (excluding vendored libraries) | Virtual grid, lightbox, compare, keyboard culling, dark/light, WCAG AA contrast checked by script |
| API | FastAPI, 43 routes, 127.0.0.1:8765; 5,100 lines of Python | No Host/Origin/token checks (section 7) |
| Indexing | `os.walk`, SHA-256 of every file, pHash, EXIF/MP4 metadata | Full read of every file, including multi-GB videos |
| Duplicates | Exact (SHA-256), near (pHash + BK-tree + union-find), video (middle-frame pHash) | Section 4 |
| Quality | Laplacian variance at 1024 px, Tukey fence per library | Section 4 |
| Recognition | CLIP ViT-B/32 zero-shot: 6 prompts + "other", threshold 0.5; person prompt; embeddings for search | Section 5 |
| Removal | Move to `Image Review` folder, restore via recorded path, purge guarded by typed `DELETE` | Section 8 |
| Organize | Preview then irreversible move into dated folders; trips from GPS + offline city database | No undo journal |
| Install | `Install.bat`/`Setup.ps1`: Python via winget or python.org, venv, `pip install`, model download | Section 9 |
| Tests | 12 Python tests (one is a full lifecycle), 7 JS tests, contrast and unused-import linters | No UI/e2e tests, no CI, no accuracy evaluation |
| Licence | None in repo | Section 10 |

---

## 3. Competitive landscape: what the category does

**Duplicate finders (Windows).** Roundups list AllDup, Czkawka, dupeGuru, VisiPics, Duplicate Cleaner Pro (about $77) and many $40 tools; most reviews are vendor-written **[Reported]**. Czkawka's design is the useful reference: duplicates are found by a **multi-stage pipeline (size, then a partial "prehash", then a full hash)** with a hash cache so rescans are fast **[Reported]**. Similar images use a perceptual hash compared by Hamming distance, with a hash size of 16 recommended as a balance **[Reported]**. Our indexer hashes every byte of every file.

**Phone cleaner apps.** They group near-identical shots, pick a "best" per group by a quality score, flag blurry/dark/screenshots, run on-device and leave the decision to the user **[Reported]**. One independent review notes they sometimes flag a soft shot even when sharper versions exist, and that two people pick different "best" photos from one burst **[Reported]**. Developers who moved from instant delete to mark-then-review did so because one wrong tap felt dangerous **[Reported]**. That is our mark-first model.

**Culling tools for photographers.**
- Aftershoot runs locally (min 8 GB RAM and a recent CPU, no dedicated GPU stated), scores each image 1 to 100, groups similar images, marks the best in each group, sorts closed eyes/blur/highlights into their own groups, and learns from the user's corrections. **[Primary]**
- Lightroom Classic's Assisted Culling scores **subject sharpness, eye sharpness and eyes open**, and is described as optimised for portraits. **[Primary/Reported]** Sharpness is judged on the subject, not the whole frame.
- Narrative Select is grouping-first with focus and eye assessment; Photo Mechanic's AI is assistive (face detection, sharpness, duplicates). **[Reported]**

**Libraries.**
- Apple: duplicates via on-device ML (exact only, per some sources) **[Reported]**; the Vision framework exposes an aesthetics score from -1 to 1 plus an **`isUtility` flag** for screenshots and documents (iOS 18+). **[Primary/Reported]**
- Immich: one default CLIP model (`ViT-B-32__openai`), alternatives behind an admin setting; duplicate detection uses CLIP embedding distance with a user slider (0.001 to 0.1). Models download once and then work offline. **[Primary/Reported]**

**Takeaways.**
- Nobody ships a single method. Hash for exact, perceptual hash or embeddings for near-duplicates, a learned model for quality, and metadata for screenshots.
- Nobody auto-deletes. Everyone ends in a user confirmation.
- Quality judgement is **subject-aware** in the professional tools (faces, eyes), and **explained** ("sharpest of the set").
- Features common in the category that we lack: keeper rules the user can express (prefer originals, prefer a folder), a "corrupt/unreadable files" category (Czkawka covers broken files), and face/eye awareness. Keeper-rule details were not documented in the sources I found **[Unverified]**.

---

## 4. Detection engine

### 4.1 Near-duplicates and bursts

| Today | Problem | Evidence |
| --- | --- | --- |
| 64-bit pHash, Hamming ≤ 4/6/9, BK-tree, **union-find** | Union-find is single-linkage: A~B and B~C merge A and C even if A and C differ. Long chains form in burst sequences | Single linkage "chains"; complete linkage resists it; a Fuji Xerox patent found single linkage unsatisfying for near-duplicate photos. **[Reported]** |
| No time constraint | Two similar scenes years apart can join | A time window plus a maximum group diameter bound the chain. Reasoned from the sources, not directly documented. |
| pHash on the whole image | Flat images (screenshots, dark shots, blank frames) hash alike; embeddings over-match templated content instead | Hashes were reliable on flat/templated images while an SSCD embedding scored two unrelated bar charts 0.92; deep embeddings win on edited copies. Common remedy: cascade, cheap hash first, embedding to verify. **[Reported]** |
| Exact-duplicate keeper = lowest id | Arbitrary | Prefer the original location, earliest `mtime`, the file with metadata |
| Photo keeper = (pixels, blur score) | A blurry high-resolution shot beats a sharp lower-resolution one | Rank sharpness/quality before resolution; add subject-aware sharpness |
| Videos: one middle-frame pHash | Two clips that start differently but share a middle frame are missed; two different clips can collide | Use several frames per video |

**Recommendation:** keep pHash as the cheap first pass, then verify candidates with the embedding we already compute; constrain by capture time (bursts are seconds apart) and a maximum group diameter; use complete-linkage or "link only to the group's keeper" instead of union-find; pick the keeper by quality first.

**Apple-specific grouping signals** (more reliable than image similarity for iPhone dumps):
- **Live Photos:** the HEIC still and MOV clip share a `ContentIdentifier` (MakerNote in the still, QuickTime key in the clip). Filenames usually match but ExifTool users report they cannot be relied on. **[Reported]** We pair by filename stem (`find_live_pair`).
- **Bursts:** the Apple MakerNote has a `BurstUUID` shared by every image in one burst; absent in non-burst files. **[Reported]** Unused today.
- **Edits:** an edited photo exists as the original (`IMG_0000.HEIC`), the edit (`IMG_E0000.HEIC`) and a `.AAE` sidecar. **[Reported]** Both images are indexed, so they surface as "similar photos". They should be recognised as an original/edit pair and suggested differently.

### 4.2 Quality (blur, exposure, "is this a keeper")

- **Laplacian variance** is cheap and standard, but its documented failure modes are plain walls and sky, dark or noisy shots, and **intentional bokeh or subject blur with a sharp background**. **[Reported]** iPhone Portrait Mode makes the last case routine. Our adaptive Tukey threshold fixes the "universal threshold" problem but not the content dependence.
- **Subject-aware sharpness:** Lightroom judges subject and eye sharpness. A face detector would let us measure sharpness inside the face box. **YuNet** (OpenCV Zoo) is MIT-licensed, about 230 KB, with WIDER FACE AP ≈ 0.83/0.82/0.71 (easy/medium/hard). **[Reported]**
- **Closed eyes:** MediaPipe's Face Landmarker outputs 52 blendshape coefficients including `eyeBlinkLeft/Right`. **[Reported]** Its licence and bundle size were not confirmed **[Unverified]**.
- **Learned quality models:** pyiqa packages MUSIQ, TOPIQ, MANIQA, CLIP-IQA, and offers **SPAQ-trained variants** (SPAQ is 11,125 photos from 66 smartphones with human ratings, the closest public match to our domain). **[Reported]** I found no benchmark numbers, no ONNX export status and no licence terms for these **[Unverified]**.
- **CLIP-feature probes work:** a linear probe on CLIP image features matches fully fine-tuned ImageNet models on the AVA aesthetics benchmark with 768 trained parameters. LAION's predictor is built the same way, but an audit notes it was trained mostly on Western photographers' preferences. **[Reported]**

**Recommendation:** add a subject-aware focus score (face box) and a blink score; evaluate a small learned head on our embedding against a labelled set before adopting; treat Laplacian as one input, not the verdict.

### 4.3 Categories (what counts as clutter)

- Screenshots are decided by metadata (PNG with no camera model), which is the right call. Apple's `isUtility` concept (screenshots, documents) is the closest industry analogue.
- **Product question, not a technical one:** "Food" and "Memes" are topics, not defects. Flagging every food photo for removal is a surprising default. The common cleaner categories are duplicates, similar, blurry, screenshots, documents/receipts, and large videos. See decision D3.
- OpenAI's own CLIP model card calls deployed use cases out of scope without thorough in-domain testing, and notes weakness at fine-grained classification and counting. **[Primary]** Our tuned 0.5 threshold came from a handful of images. We need a labelled evaluation set (section 11).
- OCR could separate receipts and documents from whiteboards more reliably than a prompt. Options: Windows' built-in OCR, RapidOCR (ONNX, about 80 MB), PaddleOCR (best accuracy in one small invoice test). All numbers come from vendor or tiny tests. **[Reported]**

### 4.4 Search

- CLIP ViT-B/32 is English-only per its model card. **[Primary]** Immich offers multilingual models for non-English queries. **[Primary]**
- Our scoring is a paired softmax against "something other than X" with a 0.5 cutoff. It is principled but means some phrasings return nothing; Immich simply ranks. A relative score cutoff (best match minus a margin) would likely feel better. Design reasoning, not tested.
- SigLIP is trained with a sigmoid loss and is described as better suited to retrieval. **[Reported]** SigLIP 2 base is Apache-2.0, about 0.4 B parameters, and `onnx-community/siglip2-base-patch16-224-ONNX` exists. **[Primary]** File sizes and the CPU speed were not confirmed.

### 4.5 Learning from the user

Every mark the user makes is a label, and we already store each photo's embedding. A tiny per-user model (logistic regression on the embedding) could re-order suggestions. Support: linear probes on CLIP features are competitive for aesthetics, and personalised aesthetic assessment is an active few-shot research area. **[Reported]** I found **no per-user accuracy figures**, so this must be evaluated before it ships. Risks: marks reflect "I don't want this", not "this is poor quality"; labels are sparse and noisy. Use it only to order suggestions, never to auto-decide.

### 4.6 Cost of mistakes

Wrongly suggesting a keeper is worse than missing a clutter photo. Defaults should be conservative, suggestions explained, and "accept all" offered only for the most certain categories (exact duplicates, clear sets). Aftershoot exposes sensitivity sliders; Apple exposes none. We have chosen none, which makes the defaults matter more.

---

## 5. AI runtime and models

### 5.1 Measured cost today

| Component | Size |
| --- | --- |
| venv (dev) | 4,679 MB; `torch` 4,030 MB (CUDA 12.6 build), `transformers` 107 MB, OpenCV 112 MB, SciPy 110 MB |
| CLIP weights | 581 MB |
| Installed copy | Python 3.14.3, FastAPI 0.141.1, numpy 2.5.1, OpenCV 5.0.0.93, torch 2.13.0+cu126 |

All **[Verified here]**. `requirements.txt` uses `>=` everywhere, so two installs on different days can differ. Setup targets Python 3.12 but the installed copy runs 3.14.3.

### 5.2 Runtime options

- **ONNX Runtime** (CPU wheel, plus DirectML for any DirectX 12 GPU) removes `torch` and `transformers`. DirectML is **in sustained engineering**; Microsoft points new work to **Windows ML**, which wraps the same ONNX Runtime APIs, is GA, and delivers GPU/NPU execution providers through Windows Update. **[Primary]** Whether Windows ML is usable from Python was not confirmed **[Unverified]**.
- DirectML constraints: sequential execution only, memory-pattern optimisation off, one `Run` call at a time per session, ONNX opset ≤ 20. **[Primary]**
- ONNX Runtime ships Windows wheels for Python 3.12 and 3.13. **[Reported]** Python 3.12 is the lowest-risk pin; confirm numpy/OpenCV wheel coverage for the chosen version **[Unverified]**.
- INT8 is not free: one CLIP B/32 port lost 4.6 points on a CIFAR-100 zero-shot test (0.871 to 0.825); an INT8 EfficientNet ran 10.9× **slower** on a laptop CPU in the QOperator format; a fully INT8 MobileCLIP2 vision model was about 12× slower than its hybrid build. **[Reported]** Benchmark FP32, FP16 and INT8 on target hardware; do not assume.

### 5.3 Model shortlist and licences

| Model | Licence | Size | Verdict |
| --- | --- | --- | --- |
| OpenAI CLIP ViT-B/32 | MIT (repo LICENSE) **[Primary]** | ~600 MB FP32 across both encoders **[Reported]** | Safe, English-only, what we use now. Immich's default. |
| SigLIP 2 base (patch16-224) | Apache-2.0 **[Primary]** | ~0.4 B params | Strong candidate; ONNX export exists |
| DINOv2-small | Apache-2.0 **[Primary]** | 22.1 M params | Good for visual similarity and near-duplicate verification; no text encoder |
| MobileCLIP2 (S0–S4) | **Apple research-only licence (`apple-amlr`)** **[Primary]**; the licence text excludes commercial products **[Reported]** | S0 ≈ 54 M params | **Do not use** in a product without a licence from Apple |
| SSCD (copy detection) | Code MIT; **weights licence not stated** **[Primary]** | 512-d embedding | Unclear; do not adopt without confirming |
| YuNet (faces) | MIT **[Reported]** | ~230 KB | Adopt for face boxes |

### 5.4 Hardware floor

Aftershoot's published floor (8 GB RAM, recent CPU, no discrete GPU required) is a sensible reference. **[Primary]** Assume CPU-only laptops are the common case and treat a GPU as a bonus selected automatically at run time, which is what `ClipBackend.device` already does for CUDA.

### 5.5 Vector search

100,000 vectors of 512 dimensions is about 200 MB as float32. Exact search in `sqlite-vec` was about 39 ms for 100k × 384 in one test; my own estimate for NumPy brute force at that size is 10 to 30 ms. **[Reported/Unverified]** Our current NumPy approach is fine to well past 100k photos; no vector database is needed.

---

## 6. iPhone and Windows media realities

| Issue | Finding | Status |
| --- | --- | --- |
| **Colour profiles** | `media._render_still` drops the embedded ICC profile and does no conversion. With a non-sRGB test profile, the stored pixel stayed (200, 40, 40) where a correct conversion gives (210, 53, 53). The profile survived decoding for both JPEG and HEIC. iPhone photos are Display P3, so saturated colours will look duller than they should. Fix: convert to sRGB with `ImageCms` (or keep the profile). | **[Verified here]**; real P3 file not tested |
| **HDR photos** | iPhone HDR HEIC stores an SDR base image plus a gain map; decoders we use show the base image. | **[Reported]** |
| **HDR video frames** | iPhone video is HLG/Dolby Vision-based; grabbing raw frames without an HLG-to-SDR transform gives a flat, washed-out look. Whether OpenCV does this is unconfirmed. | **[Reported]/[Unverified]** |
| **HEIC decoding** | Windows apps need the HEIF and HEVC codec extensions (HEVC is a paid Store item). Our app decodes HEIC itself through pillow-heif, so it does not depend on them. | **[Reported]** |
| **HEVC video playback** | Edge relies on the Windows platform decoder for HEVC. On a PC without the extension, the lightbox video player may fail. Fallback: detect with `canPlayType`, show the poster frame and an "Open in default player" button. | **[Primary]** (dependency), fallback is a design proposal |
| **OneDrive placeholders** | Reading a cloud-only file downloads it. Microsoft guidance is not to open placeholders unless needed; the file attributes can be read from the directory listing. A scan of a OneDrive `Pictures` folder could download an entire library. We never check the attributes. | **[Reported]** |
| **Long paths** | Python is long-path aware, but the registry setting must also be on; the process current directory is excluded. | **[Primary/Reported]** |
| **Controlled Folder Access** | `Pictures` is protected by default when the feature is on; an unrecognised app can be blocked from writing there. Whether it is on by default was not confirmed. The app should surface a clear message when moves fail. | **[Primary]/[Unverified]** |

---

## 7. Local server security (verified here)

A scratch server (installed copy's code, scratch data, port 8766) was probed with `curl`:

| Probe | Result | Meaning |
| --- | --- | --- |
| `GET /api/settings` with `Host: evil.example` | 200 | No Host validation: **DNS rebinding works** |
| `POST /api/heartbeat` with `Origin: https://evil.example` | 200 | No Origin validation |
| `PUT /api/settings`, `text/plain` JSON body | 422 | FastAPI's strict content-type check (default since 0.132.0) blocks this one **[Primary]** |
| `OPTIONS` pre-flight from a foreign origin | 405 | No CORS answer, so the browser blocks `application/json` cross-site writes |
| `POST /api/shutdown`, cross-site | 200, **server exited** | A simple cross-site request terminates the app |

**Why it matters.** FastAPI's strict content-type check does not help against DNS rebinding, which makes the attacker's page same-origin and removes the CORS barrier entirely, and does not help body-less POSTs such as `shutdown`. Reasoning from the routes (not exercised end to end): a rebinding page could mark photos for removal, run Apply (which moves them to the review folder), and call Purge, whose "confirmation" is a value the client supplies. Each step is a plain API call. Apply is restorable and Purge is confined to files inside the review folder, but the last step permanently deletes.

**Industry response (2025 to 2026).** The localhost MCP-server wave and Vite's 2025 advisory were the same bug class. The fix pattern, seen in several projects: reject any request whose `Host` is not a loopback name and port, reject foreign or `null` `Origin`, check `Sec-Fetch-Site`, and require a random per-launch token for state-changing routes. **[Reported]** Host validation is what stops rebinding; Origin checks stop cross-site posts; the token covers both and any local process. Rails and Vite added Host allow-lists by default. **[Reported]**

**Recommendation (P0):** add middleware that enforces the loopback `Host`/`Origin`/`Sec-Fetch-Site` rules on every request; generate a random token at launch, pass it to the window via the launch URL, and require it on all non-GET routes; keep `/healthz` open for the single-instance check; add tests that reproduce each probe above.

---

## 8. Safety model

**What is right.** Mark first, apply once, restore with the recorded original path, typed `DELETE` for the one irreversible step, purge confined to the review folder. NN/g advises against routine confirmation dialogs, prefers undo, and cites typed confirmation for severe cases. **[Primary]** Apple's Recently Deleted keeps items 30 days with a visible countdown; Google Photos has reportedly moved from 60 to 30 days. **[Reported]**

**Gaps and options.**
1. **Permanent delete is `unlink`.** Windows' Recycle Bin is the user's mental model. `send2trash` uses `IFileOperation`/`SHFileOperation`, batches calls and raises `TrashPermissionError`; long-path and size/drive behaviour were not confirmed. **[Reported]** Deletions from removable drives are generally permanent unless an admin enables the bin. **[Reported]** Recommendation: keep the visible review folder as the safety net (it works on every drive), and make the final purge go to the Recycle Bin where supported.
2. **Organize has no undo.** It moves files and records only a status. Add a move journal (source, destination, time) so a run can be reversed, and surface an Undo like the other actions.
3. **Cross-drive moves.** `shutil.move` across volumes is copy-then-delete; a failure mid-way can leave both copies or a partial one. **[Reported/general]** Verify size (and ideally a hash) before deleting the source.
4. **Optional auto-expiry** of the review folder (30 days, with a countdown, like Apple) would add a deletion the user did not explicitly confirm. If offered at all, default off. Decision D5.
5. **Index and data live inside the program folder.** Uninstall removes the index; an update that replaces the folder could too. Store user data under a separate `%LocalAppData%` folder, and back up the database before a migration (standard practice).
6. **Diagnostics.** A local "Export diagnostics" bundle (logs with home paths scrubbed, never uploaded automatically) matches the pattern privacy-focused apps use. **[Reported]**

---

## 9. App shell, packaging, signing, updates

### 9.1 Window shell

| Option | Notes |
| --- | --- |
| **Edge/Chrome `--app` (today)** | No dependencies; private profile; but no native folder dialog (we run Tk in the server), no custom title bar, depends on Edge or Chrome being present. Window Controls Overlay is documented for installed PWAs, not for `--app` launches. **[Primary/Unverified]** |
| **pywebview** | Wraps a native webview (WebView2 on Windows is the expected renderer **[Unverified]**), native file dialogs, native menus, two-way JS↔Python calls, built-in static server, bundlers PyInstaller/Nuitka, BSD licence. **[Primary]** Keeps our UI. |
| **Tauri / Electron** | Rewrites around a Rust or Node shell; Python would become a sidecar. Not justified. |

### 9.2 Freezing Python

Folder builds (PyInstaller `--onedir`, Nuitka standalone) trigger fewer antivirus false positives than `--onefile`; vendors claim Nuitka is safer, which is self-reported. Sign the build and scan it before release. **[Reported]** Alternative: ship an embedded Python plus pinned wheels, which avoids freezer quirks. Either removes `pip` from the user's PC.

### 9.3 Installer and updates

Inno Setup and WiX have no built-in update channel. **Velopack** lists Python as supported, can host updates on GitHub Releases and installs without configuration; its per-user install behaviour and delta updates were not confirmed. **[Primary/Unverified]** The app must stay "no phoning home": the existing manual **Check for updates** button is the right model; an in-app "download and install" can still be user-initiated.

### 9.4 Signing and trust

| Option | Cost | Notes (Microsoft's comparison, updated 2026-08) **[Primary]** |
| --- | --- | --- |
| Microsoft Store, MSIX | Free (individual registration is free) | Store re-signs; no SmartScreen warning; recommended for most new apps |
| Store, MSI/EXE | You sign | Self-signed not accepted |
| Azure Artifact Signing | ~$9.99/month | Individuals: US and Canada only; reputation builds over time; no token needed |
| OV certificate | $150 to 300/year | Same SmartScreen behaviour; HSM/token required since 2023 |
| EV certificate | $400+/year | No longer bypasses SmartScreen (removed 2024) |
| SignPath Foundation | Free | Open-source projects; third-party guides cite OSI licence and a public repo **[Reported]** |
| Unsigned | Free | Strong SmartScreen block; Smart App Control can block outright |

Smart App Control, in enforcement mode, runs only apps Microsoft recognises or that are signed with a trusted certificate; it is chosen automatically on clean Windows 11 installs for users who mostly run signed software. **[Primary]** Whether our current script-and-`python.exe` install is affected, and the current toggle behaviour, are unconfirmed **[Unverified]**.

Other channels: **winget** manifests go through automated safety validation and SmartScreen checks; whether unsigned installers are accepted was not established. **[Reported/Unverified]**

### 9.5 Model delivery

GitHub release assets are limited to under 2 GiB each, so a large model cannot ship as one asset. **[Reported]** Bundling the model in the installer gives a true offline install and removes the first-run download; downloading on first run requires a connection. I found nothing on Hugging Face download resilience. For either route: pin a SHA-256, verify, and resume.

---

## 10. Licensing and compliance

| Component | Licence | Implication |
| --- | --- | --- |
| This project | **None** | Public repo with no licence means all rights reserved. Choose before release; it also decides SignPath eligibility |
| pillow-heif 1.5.0 wheel | BSD-3 wrapper, but bundles **libheif (LGPLv3), libde265 (LGPLv3), x265 (GPLv2)**, libaom (BSD) **[Verified here]** | A bundled installer would redistribute GPLv2 code. A decode-only build (the `pi-heif` line) avoids x265, but upstream discontinued it and a community fork carries libheif security fixes **[Reported]** |
| OpenCV wheels | Apache-2.0 / BSD, bundling FFmpeg (LGPL) **[Reported]** | Ship the third-party licence file; current-wheel FFmpeg configuration unconfirmed |
| `reverse_geocoder` | LGPL | Dynamic use is usually fine; keep notices. GeoNames `cities1000` data needs attribution (CC BY; v3 or v4 sources disagree) **[Reported]** |
| CLIP, transformers, torch | MIT, Apache-2.0, BSD | Notices only; going away with ONNX |
| Figtree, Lucide, Preact, htm | OFL, ISC, MIT, Apache-2.0 | Already bundled with licence files |

HEVC **patent** licensing is separate from copyright licences and was not researched; get advice before a commercial release. Not legal advice.

**To do:** generate a third-party notices file from the shipped build (a tool such as `pip-licenses` run in the build environment), add a `LICENSE`, and write a short privacy statement matching the README's claims (nothing leaves the PC; update check is manual; the only network use is the optional model/update download).

---

## 11. Design, accessibility, performance, quality engineering

### 11.1 Design (keep)

Neutral surfaces around photos, mark-first grease-pencil marks, undo toasts, typed confirmation for the one irreversible step, keyboard culling. Onboarding guidance agrees with the current direction: land users on something actionable, avoid long tours, treat empty states as a guide. **[Reported]** Fluent guidance: use standard components. **[Reported]**

### 11.2 Design (gaps)

- **Time to value:** the scan must finish before anything can be reviewed. Showing exact duplicates as soon as they are found would let review start while later stages run (idea, not a documented standard).
- **Title bar / window chrome** (section 9.1).
- **Explanations:** keep "why this keeper" and extend it to quality reasons ("eyes closed", "soft focus on faces").
- **Corrupt/unreadable files** are counted but not reviewable.

### 11.3 Accessibility

- The ARIA grid pattern: a single Tab stop with **roving tabindex** (or `aria-activedescendant`), arrow keys, Home/End, `aria-rowcount`/`aria-rowindex` kept correct as a virtualised list scrolls, and an accessible name. **[Reported]** Our virtual grid has keyboard handling but I have not audited its roles or focus model.
- WCAG 2.2 adds nine criteria including **Focus Not Obscured (AA)**, **Target Size minimum 24×24 CSS px (AA)** and Dragging Movements. **[Reported]** The floating selection bar and small thumb buttons should be checked against the first two.
- Also unaudited: Windows High Contrast (`forced-colors`), `prefers-reduced-motion`, screen-reader announcements for toasts and job progress. Add axe checks and a manual NVDA pass.

### 11.4 Performance

- Our measurements: all API calls ≤ ~160 ms at 20,000 photos; a 1,000-file apply took ~7.8 s. **[Verified here, earlier]**
- Thumbnails: sources suggest WebP for small thumbnails (fast decode, close to AVIF in size under ~300 px) and AVIF for larger images, with only a few ms/image difference on desktop. **[Reported]** Low priority; measure first.
- `pyvips` vs Pillow: for large JPEGs with `draft()` they tied in the one test found; no HEIC data. **[Reported]** Keep Pillow.
- Scan hashing: adopt size → partial hash → full hash with a cache (Czkawka's design).

### 11.5 Quality engineering

- Today: ~12 Python tests, 7 JS tests, lint scripts. Missing: **UI end-to-end tests** (Playwright against Edge), **axe** accessibility checks, **CI** (GitHub Actions on Windows), **security regression tests** for section 7, a **dependency lockfile**, and an automated **build/sign/release** pipeline.
- **Accuracy evaluation is the biggest gap.** There is no labelled set, so every threshold (0.5 category cutoff, pHash distances, blur fence) is tuned by eye. Build a small evaluation harness first: a few hundred labelled phone photos (kept local), precision/recall for each suggestion type, and latency per stage. Public references: SPAQ for smartphone quality; others commonly used for duplicates (INRIA Holidays, Copydays) and blur are from memory and were not verified here.
- Risk controls: unit tests with fault injection for file moves (cross-drive, locked file, permission denied), and property tests for Live Photo pairing and restore paths.

---

## 12. Not verified, with the test that would settle each

| Open question | How to settle it |
| --- | --- |
| Real Display P3 behaviour with iPhone HEIC | Run the renderer on a real iPhone photo and compare against a P3-aware viewer |
| CLIP/SigLIP2/DINOv2 CPU throughput, FP32/FP16/INT8, and DirectML speed | Benchmark on 2 to 3 typical PCs; include accuracy on our labelled set |
| Whether a learned head on embeddings beats Laplacian+resolution as a keeper rule | Evaluate on bursts with human-chosen keepers |
| Pairing by `ContentIdentifier` vs filename on real exports | Parse a real iPhone export and count mismatches |
| HLG/Dolby Vision frame appearance via OpenCV | Render thumbnails of a real iPhone HDR clip |
| HEVC playback in Edge/WebView2 on a clean Windows 11 | Test in a fresh VM with and without the extension |
| Windows ML from Python; pywebview renderer and WebView2 availability | Prototype the existing UI in pywebview |
| Velopack per-user install and Python support; Store acceptance of a Python-based MSIX | Build a hello-world package for each |
| Smart App Control effect on the current install and on a frozen build | Test on a clean Windows 11 install with SAC enforcing |
| Whether Controlled Folder Access is on by default | Check a clean Windows 11 install |
| Google Photos/Lightroom/Narrative internals | Not obtainable from public sources I found |
| Current licences of SSCD weights, pyiqa models and MediaPipe | Read each repository's LICENSE before any adoption |
| HEVC patent exposure of bundling a decoder | Legal advice |

---

## 13. Recommended sequence (not yet agreed)

**P0: trust and hygiene (small, independent of everything else)**
1. Host/Origin/token guard plus regression tests (section 7).
2. Pin dependencies and Python version; add a lockfile.
3. Colour-managed thumbnails (convert to sRGB).
4. Choose a licence; generate third-party notices.

**P1: engine**
5. Build the labelled evaluation harness and baseline today's numbers.
6. Migrate to ONNX Runtime with one built-in model; remove the GPU/CPU choice and the quality knobs from the UI.
7. Near-duplicate pipeline: time window, diameter-bounded grouping, embedding verification, quality-first keeper.
8. iPhone-aware grouping (`ContentIdentifier`, `BurstUUID`, original/edit pairs); face-aware sharpness and blink score.
9. Faster, cloud-safe scanning (size/prehash/full hash with cache; skip placeholder files).

**P2: product packaging**
10. Decide shell (Edge `--app` vs pywebview) after a prototype.
11. Self-contained signed installer with the model bundled; manual update check retained.
12. Separate user data from the program folder; add backup-before-migrate.

**P3: polish**
13. Organize undo journal; Recycle Bin option for the final purge.
14. Accessibility pass (grid semantics, target sizes, forced-colors) with automated checks.
15. Optional: personal ordering model, XMP export, progressive review while scanning.

**Avoid:** cloud inference, generative vision-language models (slow, heavy, non-deterministic over tens of thousands of photos), auto-delete, MobileCLIP2 weights, any telemetry.

## 14. Decisions needed from the owner

- **D1 Distribution:** Microsoft Store (free signing, MSIX), direct signed download (Azure Artifact Signing if eligible), or both. And whether the project becomes open source (changes SignPath eligibility and the licence choice).
- **D2 Model delivery:** bundle in the installer (offline, larger) or download at first run (smaller, needs a connection).
- **D3 What counts as clutter:** keep Food/Memes/Whiteboards as review categories, make them filters/labels, or drop them.
- **D4 Settings:** remove Strict/Balanced/Loose and search detail from the UI (my recommendation), or keep them under an "Advanced" section.
- **D5 Review folder:** keep indefinite storage (today), or offer optional auto-expiry (off by default).
- **D6 Supported scope:** iPhone dumps only, or any camera and Android exports (affects the heuristics).
- **D7 Hardware floor:** confirm CPU-only laptops with 8 GB RAM as the minimum target.

### Owner's answers (2026-10-28)

| | Decision |
| --- | --- |
| D1 | Microsoft Store (MSIX, Microsoft-signed). |
| Licence | Open source under **GPL-3.0**. |
| D2 | Model bundled in the installer. |
| D3 | Review queue holds plausible junk only (duplicates, bursts, blurry, blank, screenshots); food, memes, documents and whiteboards become Photos filters. |
| D4 | Remove similarity presets, search detail and hardware choices from the UI. |
| D5 | Review folder keeps files until the user deletes them. |
| D6 | iPhone **and Android** treated equally. |
| D7 | CPU-only laptop with 8 GB RAM is the floor; GPU used automatically when present. |

**Checked 2026-10-28: GPL-3.0 and the Microsoft Store**
- [Primary] Microsoft Store Policies v7.20 (updated 2026-09-14) contain no GPL or open-source licence restriction. The only open-source wording concerns browser engines.
- [Reported] The 2011 Windows Phone Marketplace agreement did bar GPLv3 apps. That was a different store and agreement and is not in the current policy.
- [Reported] GIMP, Inkscape and QField are listed on the Microsoft Store (a QGIS developer thread, Aug 2026). Presence is precedent, not proof of compatibility.
- [Unverified] The separate Store publisher agreement was not read; it must be read before submission. GPLv3's "installation information" clause is the likeliest friction, and MSIX packages can be sideloaded, which supports compliance. Legal advice is the only real answer.
- Practical GPL duties: publish the full source for every released version, keep the source link in the Store listing and About page.

**Checked 2026-10-28: bundled HEIC libraries vs GPL-3.0**
- [Verified here] pillow-heif 1.5.0's Windows wheel ships `libheif` (LGPLv3), `libde265` (LGPLv3) and `libx265` (**GPLv2**, release 3.4). The wheel's own licence note calls the whole wheel "GPLv2".
- [Primary] x265's COPYING is GPL version 2; the project says it is available only under GPLv2 or a paid commercial licence. GPLv2-only code cannot be combined with GPLv3 code in one work.
- The app only reads photos. x265 is an encoder we never use. So the clean fix is to ship a decode-only libheif (no x265) at packaging time, or replace it with another HEIC decoder. Until then do not claim the installer is GPL-clean. This is a P2 packaging item, not a blocker for step 1.

**Follow-ups still open:**
- Model licences (CLIP MIT, SigLIP 2 and DINOv2 Apache-2.0) are compatible with GPL-3.0 (Apache-2.0 is one-way compatible with GPLv3).
- Android parity needs sample exports (Pixel/Samsung motion photos, bursts) that we do not have yet.

---

## Sources

Product and category
- Aftershoot technical answers: https://support.aftershoot.com/en/articles/10601968-technical-answers-about-aftershoot
- Lightroom Assisted Culling (Adobe): https://helpx.adobe.com/ie/lightroom-classic/desktop/import-photos/assisted-culling-at-import.html and https://fstoppers.com/lightroom/use-lightroom-ai-find-sharp-eyes-open-keepers-seconds-719139
- Narrative Select / Photo Mechanic / Imagen comparison (vendor): https://imagen-ai.com/post/narrative-select-vs-photo-mechanic-vs-imagen/
- Cisdem duplicate finder (two neural models): https://www.cisdem.com/duplicate-finder/duplicate-photo-finder.html
- Duplicate finder roundup (vendor): https://www.lilachbullock.com/best-duplicate-photo-finders/
- Czkawka: https://github.com/rugk/czkawka and https://git.blob42.xyz/Archives/czkawka/raw/commit/1a011644bf64c98542f60829bc313f104f9f921e/instructions/Instruction.md
- Immich settings and search: https://docs.immich.app/administration/system-settings/ and https://docs.immich.app/features/searching
- Apple Vision aesthetics: https://www.createwithswift.com/scoring-the-aesthetics-of-an-image-with-the-vision-framework/
- Apple Duplicates album: https://9to5mac.com/2022/06/06/duplicate-detection-photos/

Models and ML
- MobileCLIP2-S0 card: https://huggingface.co/timm/MobileCLIP2-S0-OpenCLIP and licence discussion: https://huggingface.co/apple/mobileclip2_coca_dfn2b_s13b_context77/blob/main/README.md
- SigLIP 2 base: https://huggingface.co/google/siglip2-base-patch16-224 ; ONNX: https://huggingface.co/onnx-community/siglip2-base-patch16-224-ONNX
- CLIP model card: https://huggingface.co/openai/clip-vit-base-patch32 ; licence: https://raw.githubusercontent.com/openai/CLIP/main/LICENSE
- DINOv2-small: https://huggingface.co/facebook/dinov2-small ; SSCD: https://github.com/facebookresearch/sscd-copy-detection
- YuNet: https://huggingface.co/opencv/face_detection_yunet/blob/main/README.md
- MediaPipe Face Landmarker: https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker
- IQA (pyiqa model cards): https://iqa-pytorch.readthedocs.io/en/latest/ModelCard.html ; SPAQ: https://ece.uwaterloo.ca/~z70wang/publications/cvpr20_smartphone.pdf
- CLIP linear probe for aesthetics: https://pmc.ncbi.nlm.nih.gov/articles/PMC9732445 ; LAION audit: https://www.themoonlight.io/en/review/the-algorithmic-gaze-an-audit-and-ethnography-of-the-laion-aesthetics-predictor-model
- Personalised aesthetics: https://arxiv.org/pdf/2407.07176 and https://arxiv.org/html/2604.11374
- Near-duplicate comparison: https://doi.org/10.3390/electronics15071493 and https://arxiv.org/pdf/2312.07273
- Clustering chaining: https://patents.justia.com/patent/10504002 and https://nlp.stanford.edu/IR-book/html/htmledition/single-link-and-complete-link-clustering-1.html
- INT8 CLIP: https://heartbeat.comet.ml/quantizing-clip-with-onnx-pt-1-smaller-faster-feasible-919966d44dbb ; MobileCLIP2 ONNX: https://huggingface.co/felixhrdyn/mobileclip2-s0-onnx
- Blur-detection failure modes: https://pub.dev/documentation/blur_check/latest/
- OCR comparison (vendor): https://codesota.com/ocr/paddleocr-vs-tesseract

Runtime and Windows
- ONNX Runtime DirectML EP: https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html
- Windows ML overview: https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/overview
- Code signing options (Microsoft): https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options
- Store free registration: https://blogs.windows.com/windowsdeveloper/2025/09/10/free-developer-registration-for-individual-developers-on-microsoft-store/
- Smart App Control: https://learn.microsoft.com/windows/apps/develop/smart-app-control/overview
- SignPath Foundation: https://signpath.org/ and https://zenn.dev/shm_7ec/articles/signpath-oss-code-signing?locale=en
- Velopack: https://docs.velopack.io/ ; pywebview: https://pywebview.flowrl.com/
- PyInstaller/Nuitka false positives (vendor-heavy): https://dev.to/weisshufer/from-pyinstaller-to-nuitka-convert-python-to-exe-without-false-positives-19jf
- HEVC in Edge: https://learn.microsoft.com/en-us/troubleshoot/microsoft-edge/development/video-playback-issues
- HEIC on Windows: https://www.windowscentral.com/software-apps/windows-11/how-to-add-support-for-heic-and-hevc-files-on-windows-11
- OneDrive placeholders: https://sourceware.org/pipermail/cygwin/2024-March/255623.html
- Long paths: https://learn.microsoft.com/en-ie/Windows/Win32/fileio/maximum-file-path-limitation
- Controlled Folder Access: https://learn.microsoft.com/en-us/defender-endpoint/customize-controlled-folders
- Window Controls Overlay: https://web.dev/window-controls-overlay/
- Live Photo pairing and Apple MakerNote tags: https://exiftool.org/forum/index.php?msg=56597 and https://web.do.metacpan.org/release/EXIFTOOL/Image-ExifTool-10.50/view/html/TagNames/Apple.html
- iPhone import quirks: https://learn.microsoft.com/en-us/answers/a/4534467 and https://internet.watch.impress.co.jp/docs/column/homewifi/2097449.html

Security
- FastAPI strict content type: https://fastapi.tiangolo.com/advanced/strict-content-type/
- Local-server guard examples: https://github.com/mauritsE/Fretlane/pull/47 , https://github.com/noderef/noderef/pull/82 , https://safeguard.sh/resources/blog/localhost-is-not-as-private-as-it-feels

Licensing
- pillow-heif bundled libraries: https://github.com/bigcat88/pillow_heif and the installed wheel's `LICENSES_bundled.txt`
- OpenCV wheels: https://github.com/opencv/opencv-python/issues/682
- reverse_geocoder: https://github.com/thampiman/reverse-geocoder

UX and accessibility
- NN/g confirmation dialogs: https://www.nngroup.com/articles/confirmation-dialog/
- Google Photos trash change: https://9to5google.com/2026/09/08/google-photos-trash-bin-now-deletes-media-after-30-days-down-from-60-days/
- WCAG 2.2 summary: https://www.boia.org/blog/whats-new-in-wcag-2.2-new-success-criteria-for-digital-accessibility
- ARIA grid: https://www.w3.org/WAI/ARIA/apg/patterns/grid/
- Onboarding: https://fluent2.microsoft.design/onboarding/ and https://m1.material.io/growth-communications/onboarding.html
- Image formats: https://hiredigital.com/blog/jpg-vs-webp-vs-avif-2026
