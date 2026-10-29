"""Ingestion command line.

carina-ingest seed              index the verified seed snapshot only
carina-ingest run               harvest every source, then build the index
carina-ingest run pubmed 500    harvest one source with a per source cap
carina-ingest build             rebuild the index from existing checkpoints
carina-ingest stats             print the index manifest
"""

from __future__ import annotations

import argparse
import json
import sys

from carina.config import get_settings
from carina.logging_setup import configure_logging
from ingestion import pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="carina-ingest", description="Build the Carina Compass knowledge base")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="index the verified seed snapshot")
    run = sub.add_parser("run", help="harvest sources and build the index")
    run.add_argument("sources", nargs="*", help="limit to these sources")
    run.add_argument("--limit", type=int, default=None, help="cap documents per source")
    sub.add_parser("build", help="rebuild the index from raw checkpoints")
    sub.add_parser("stats", help="show the index manifest")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)

    if args.command == "seed":
        index = pipeline.build_index(settings, include_seed=True, include_raw=False)
        index.save(settings.index_dir)
        print(json.dumps(index.manifest, indent=2))
    elif args.command == "run":
        sources = [s for s in args.sources if not s.isdigit()]
        limit = args.limit or next((int(s) for s in args.sources if s.isdigit()), None)
        report = pipeline.run(settings, only=sources or None, limit=limit)
        print(json.dumps(report, indent=2, default=str))
    elif args.command == "build":
        index = pipeline.build_index(settings)
        index.save(settings.index_dir)
        print(json.dumps(index.manifest, indent=2))
    elif args.command == "stats":
        manifest = settings.index_dir / "manifest.json"
        if not manifest.exists():
            print("No index found. Run: make seed", file=sys.stderr)
            return 1
        print(manifest.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
