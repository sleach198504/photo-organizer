# Packaging

Every way of installing Photo Organizer starts from one **payload**: a self-contained folder that
needs nothing installed on the PC and downloads nothing.

```
PhotoOrganizer.exe     the launcher Windows starts (a ~30 KB program compiled from packaging/launcher)
runtime\               Python 3.12.10, the official embeddable build from python.org (checksum pinned)
site-packages\         the libraries, at the exact versions in constraints.txt
app\                   the application, plus package_info.json (which channel this build is)
models\                the recognition model (ONNX)
LICENSE, THIRD_PARTY_NOTICES.md, config.example.yaml
```

About 1 GB on disk. The launcher runs `runtime\pythonw.exe -m app.gui_launcher` with no console
window, and shows a plain message if the app dies while starting.

## Where data lives

A packaged build is installed read-only, so it keeps the person's settings, photo index, thumbnails
and log in `%LocalAppData%\Photo Organizer` (see `app/paths.py`). `app/package_info.json` is what tells
the app it is packaged; a development checkout or a copy made by `Setup.ps1` has no such file and
behaves as before. The first time a packaged build runs it copies the settings and photo index from an
earlier `Setup.ps1` install if it finds one (`app/legacy_import.py`). It only copies; the earlier install
is not changed.

In the Microsoft Store package, Windows keeps that folder inside the package's private storage, so
uninstalling the app also removes the photo index and settings. Photos are never touched.

## Building

All commands run from the project folder in the development environment (`venv`).

| Goal | Command |
| --- | --- |
| The payload | `venv\Scripts\python.exe packaging\build_payload.py [--channel store\|installer]` |
| Prove a payload works | `build\payload\runtime\python.exe packaging\smoke_payload.py build\payload <folder of photos>` |
| The Store package | `venv\Scripts\python.exe packaging\build_msix.py` (add `--sign` for a test-signed copy) |

Needed on the build machine: the exported model (`models\clip-vit-b32-onnx`, see MODEL.md) and an
internet connection the first time. Build-time downloads are cached in `packaging\cache` and
checked against checksums recorded in the scripts: the Python runtime from python.org, and
Microsoft's `makeappx`/`makepri`/`signtool` from the official `Microsoft.Windows.SDK.BuildTools` package
on nuget.org. Nothing is installed on the PC. Outputs go to `build\` (not tracked by git).

## What has been checked

- The payload on its own Python 3.12.10 and the exact pinned libraries: package detection, the model
  loads with no PyTorch, tkinter and PyTorch absent, a full scan of a generated 136-file library
  including recognition, and nothing written into the payload folder.
- The same app run from a write-protected folder (like Program Files), with an earlier install to
  import: it imported, ran a full scan, wrote no files into the code folder, and refused the update check.
- The launcher: starts the server in about half a second, serves the app, reports its channel, exits
  cleanly when the app shuts down, and writes only to the per-user folder.
- The native folder dialog opens, can be cancelled, and returns the folder it was confirmed on.
- The `.msix` packs without errors (makeappx validates the manifest), contains the manifest, resource
  index, launcher, runtime and model at the right sizes, and carries a valid structure when test-signed.

## What has not been checked

- **Installing and running the `.msix`.** That needs either the development certificate trusted on the
  PC (administrator) or Windows Developer Mode. Neither has been done. Things that could still differ
  inside a real package: file-write redirection, the Edge app window launching from the package,
  long paths.
- **The Windows App Certification Kit**, which the Store runs on every submission.
- **A clean PC.** Everything above ran on the development PC.

### Test-installing the `.msix`

Option A, trust the development certificate (needs an administrator PowerShell):

```powershell
Import-Certificate -FilePath packaging\cache\test-signing.cer -CertStoreLocation Cert:\LocalMachine\TrustedPeople
Add-AppxPackage build\dist\PhotoOrganizer_2.0.0.0_x64.msix        # build it with --sign
```

Option B, Developer Mode (Settings > System > For developers), then register the unpacked layout:

```powershell
Add-AppxPackage -Register build\msix-layout\AppxManifest.xml
```

Remove either with `Get-AppxPackage PhotoOrganizer.Dev | Remove-AppxPackage`, and remove the certificate
from TrustedPeople afterwards.

## Submitting to the Microsoft Store

You do these; the code side is ready.

1. Register a Microsoft Partner Center developer account (individual, one-time fee).
2. Reserve the app name. Partner Center then shows the **Package identity name**, **Publisher** (a
   `CN=...` string) and **Publisher display name**. Put them in `packaging\store_identity.json`.
3. Build **without** `--sign`: `packaging\build_msix.py`. The Store signs the package itself.
4. Publish `docs\store\PRIVACY.md` at a public web address. The Store requires a privacy policy URL even
   for an app that collects nothing.
5. Create the submission: upload the `.msix`, paste the listing from `docs\store\LISTING.md`, add the
   screenshots it lists, and answer the age-rating questionnaire.
6. The package asks for the `runFullTrust` capability, which Microsoft reviews. The reason to give:
   *a desktop app that reads and moves the photos in folders the person chooses anywhere on the PC*.
7. Each later version: raise `app/version.py`, rebuild, upload as a new submission. Raise the model's
   tag (MODEL.md) only when the model itself changes.

## The standalone installer

`PhotoOrganizer-2.0.0-Setup.exe` (about 460 MB) is the install route for people who do not use the Store:
one file that carries the whole payload, so installing needs no internet connection and no
administrator rights.

```
venv\Scripts\python.exe packaging\build_installer.py
```

It is made with [Inno Setup](https://jrsoftware.org/isinfo.php), kept as a portable copy in
`packaging\cache\innosetup` (Inno Setup 6.7.4, the installer is signed by its publisher; installed with
`innosetup-6.7.4.exe /PORTABLE=1 /DIR=...`, which adds nothing to the Start menu or Apps list).

What it does for the person: a licence page, a per-user install into
`%LocalAppData%\Programs\Photo Organizer`, optional Desktop and Start menu shortcuts, one entry in Windows
Settings > Apps, and an uninstaller. It installs **no global Python**: the runtime lives in the app's own
`runtime` folder and nothing is added to PATH. On uninstall it asks whether to also delete the photo index
and settings (default: keep); photos are never touched.

**Upgrading a `Setup.ps1` install.** The default folder is the same one the older installer used, so the
new files replace the old app in place. The old 4 GB PyTorch environment, scripts and model cache are removed
only after the new files are all in (a failed upgrade never leaves the person without a working app), the old
"Apps & features" entry is removed, and `config.yaml` and `data\` are never deleted: the app copies them to
the per-user folder the first time it runs.

Checked (installing into a scratch folder made to look like an older install, with silent switches): it installs
in about 1.6 minutes; old leftovers are gone and the user data kept; a full scan runs on the installed copy;
the installed launcher serves the app; uninstalling removes the app and its Apps entry and leaves user data.
The installer refuses an install folder long enough to push a library file past Windows' 260-character path
limit (the longest path in the payload is 115 characters).

Not checked: the wizard pages as a person sees them (only silent runs were done), the removal of the old
`Setup.ps1` Apps entry (guarded so it only happens when that entry points at the same folder; a test cannot
create it without clobbering a real one), and an install on a clean PC. The file is **unsigned**, so Windows
SmartScreen will warn "unknown publisher" until it is signed with a code-signing certificate.

## Older install route

`Install.bat` / `Setup.ps1` download the app and its parts and install them per user, and will install a
**global** copy of Python if the PC has none. That is the behaviour people dislike in a one-program download,
so this route should be retired once the Store version or the standalone installer is published.
