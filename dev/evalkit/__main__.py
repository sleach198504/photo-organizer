"""Command line:

    python -m dev.evalkit synth  <folder> [--size tiny|small|medium] [--from <photos>] [--seed N]
    python -m dev.evalkit run    <dataset folder> [--no-content] [--no-sweep] [--out <folder>]
    python -m dev.evalkit compare <before.json> <after.json>
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
    engine = CurrentEngine(content=not args.no_content, sweep=not args.no_sweep)
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
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.set_defaults(fn=_run)

    p = sub.add_parser("compare", help="show headline numbers from two saved runs side by side")
    p.add_argument("before", type=Path)
    p.add_argument("after", type=Path)
    p.set_defaults(fn=_compare)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
