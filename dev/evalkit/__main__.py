"""Command line:

    python -m dev.evalkit synth  <folder> [--size tiny|small|medium] [--from <photos>] [--seed N]
    python -m dev.evalkit run    <dataset folder> [--no-content] [--no-sweep] [--out <folder>]
    python -m dev.evalkit compare <before.json> <after.json>

Public benchmarks (downloaded separately; see docs/EVALUATION.md):
    python -m dev.evalkit import certh|copydays <extracted folder>

Labelling your own photos (they stay on this PC; see docs/EVALUATION.md):
    python -m dev.evalkit prepare <photo folder> --name mine [--count 400]
    python -m dev.evalkit label   mine
    python -m dev.evalkit export  mine
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "eval_runs"


def _synth(args: argparse.Namespace) -> int:
    from . import synth

    truth = synth.build(args.folder, args.size, args.seed, args.source)
    print(f"Wrote {len(truth.notes)} photos and {len(truth.groups)} labelled groups to {args.folder}")
    print(f"Truth file: {args.folder / 'truth.json'}")
    return 0


def _run(args: argparse.Namespace) -> int:
    from . import report, truth as truthmod
    from .engine import CurrentEngine
    from .score import score

    truth = truthmod.load(args.dataset)
    engine = CurrentEngine(content=not args.no_content, sweep=not args.no_sweep, backend=args.backend)
    with tempfile.TemporaryDirectory(prefix="eval-") as work:
        result = engine.run(args.dataset, Path(work), truth.queries if "search" in truth.tasks else None)
    scores = score(truth, result)
    run = report.build_run(truth.name, engine.name, scores, result.settings)
    json_path, md_path = report.write(run, args.out)
    print(report.markdown(run))
    print(f"\nSaved {json_path}\n      {md_path}")
    return 0


def _compare(args: argparse.Namespace) -> int:
    from . import report

    before, after = (json.loads(p.read_text(encoding="utf-8")) for p in (args.before, args.after))
    print(report.compare(before, after))
    return 0


def _prepare(args: argparse.Namespace) -> int:
    from . import prepare

    prepare.prepare(args.photos, args.name, args.count, args.seed)
    print(f"Next: python -m dev.evalkit label {args.name}")
    return 0


def _label(args: argparse.Namespace) -> int:
    from . import label_server, prepare

    folder = prepare.project_dir(args.name)
    if not (folder / "project.json").exists():
        raise SystemExit(f"No project named {args.name!r}. Run `prepare` first.")
    label_server.serve(folder, open_browser=not args.no_browser)
    return 0


def _export(args: argparse.Namespace) -> int:
    from . import label_store, prepare

    try:
        info = label_store.export(prepare.project_dir(args.name))
    except label_store.LabelError as exc:
        raise SystemExit(str(exc))
    print(f"Copied {info['photos']} photos; scoring {', '.join(info['tasks'])}.")
    print(f'Score the current engine:  python -m dev.evalkit run "{info["dataset"]}"')
    return 0


def _import(args: argparse.Namespace) -> int:
    from . import importers

    try:
        if args.dataset == "certh":
            truth = importers.import_certh(args.folder, args.include)
            print(f"CERTH: {truth.notes.pop('_counts')}; scoring blurry flag on "
                  f"{sum(1 for n in truth.notes.values() if n == 'undistorted')} sharp and {len(truth.flags)} blurred images "
                  f"({args.include}).")
        else:
            truth = importers.import_copydays(args.folder)
            print(f"Copydays: {len(truth.groups)} originals with attacked copies.")
    except importers.ImportError_ as exc:
        raise SystemExit(str(exc))
    print(f"Next: python -m dev.evalkit run \"{args.folder}\" --no-content" + (" --no-sweep" if args.dataset == "certh" else ""))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m dev.evalkit", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("synth", help="build a dataset whose answers are known")
    p.add_argument("folder", type=Path)
    p.add_argument("--size", choices=["tiny", "small", "medium"], default="small")
    p.add_argument("--from", dest="source", type=Path, help="use your own photos as the starting pictures")
    p.add_argument("--seed", type=int, default=11)
    p.set_defaults(fn=_synth)

    p = sub.add_parser("run", help="run the current engine over a dataset and score it")
    p.add_argument("dataset", type=Path)
    p.add_argument("--no-content", action="store_true", help="skip the recognition model (faster)")
    p.add_argument("--no-sweep", action="store_true", help="skip the threshold sweep (faster)")
    p.add_argument("--backend", choices=["auto", "onnx", "torch"], default="auto", help="which recognition runtime")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.set_defaults(fn=_run)

    p = sub.add_parser("compare", help="show headline numbers from two saved runs side by side")
    p.add_argument("before", type=Path)
    p.add_argument("after", type=Path)
    p.set_defaults(fn=_compare)

    p = sub.add_parser("prepare", help="pick a mixed sample of your photos to label")
    p.add_argument("photos", type=Path, help="the folder your photos are in (only read, never changed)")
    p.add_argument("--name", required=True, help="a name for this labelling project")
    p.add_argument("--count", type=int, default=400, help="how many photos to sample (default 400)")
    p.add_argument("--seed", type=int, default=5)
    p.set_defaults(fn=_prepare)

    p = sub.add_parser("label", help="open the labelling page for a project")
    p.add_argument("name")
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=_label)

    p = sub.add_parser("export", help="write a finished project out as an evaluation dataset")
    p.add_argument("name")
    p.set_defaults(fn=_export)

    p = sub.add_parser("import", help="write a truth.json for a downloaded public benchmark")
    p.add_argument("dataset", choices=["certh", "copydays"])
    p.add_argument("folder", type=Path, help="the folder the dataset was extracted to (photos are not changed)")
    p.add_argument("--include", choices=["natural", "artificial", "all"], default="natural",
                   help="CERTH only: which blurred images to score (default: the naturally blurred ones)")
    p.set_defaults(fn=_import)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
