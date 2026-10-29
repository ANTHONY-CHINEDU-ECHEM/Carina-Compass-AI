"""Terminal interface.

carina ask "EGFR exon 19 deletion, stage IVA adenocarcinoma, PS 1: first line options?"
carina understand "Tagrisso after resection of stage IIIA L858R adenocarcinoma"
carina stage cT2a N2b M0
carina options adenocarcinoma IVA ALK
carina screen lorlatinib with rifampicin
carina carboplatin 5 68 72 96 male
carina serve
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from carina.clinical import dosing, safety_screen, staging, therapy
from carina.clinical.understanding import understand
from carina.domain import PatientContext


def _print(data: object) -> None:
    print(json.dumps(data, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="carina", description="Carina Compass AI")
    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask", help="ask a cited question")
    ask.add_argument("question", nargs="+")
    ask.add_argument("--provider", default=None)
    und = sub.add_parser("understand", help="show entities, triage and tool cards for a question")
    und.add_argument("question", nargs="+")
    stg = sub.add_parser("stage", help="TNM stage group (9th edition)")
    stg.add_argument("tnm", nargs="+")
    stg.add_argument("--edition", type=int, default=9)
    opt = sub.add_parser("options", help="NICE aligned treatment options: histology stage biomarkers...")
    opt.add_argument("histology")
    opt.add_argument("stage")
    opt.add_argument("biomarkers", nargs="*")
    opt.add_argument("--pdl1", type=float, default=None)
    opt.add_argument("--ps", type=int, default=None)
    scr = sub.add_parser("screen", help="medication safety screen: planned drugs 'with' current medicines")
    scr.add_argument("terms", nargs="+")
    carbo = sub.add_parser("carboplatin", help="Calvert check: auc age weight creatinine sex")
    carbo.add_argument("auc", type=float)
    carbo.add_argument("age", type=int)
    carbo.add_argument("weight", type=float)
    carbo.add_argument("creatinine", type=float)
    carbo.add_argument("sex")
    srv = sub.add_parser("serve", help="run the API")
    srv.add_argument("--host", default="0.0.0.0")
    srv.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    if args.command == "ask":
        from carina.container import get_container

        result = asyncio.run(get_container().pipeline.ask(" ".join(args.question), provider=args.provider))
        print(result.answer)
        print()
        for source in result.sources:
            print(f"[{source['id']}] {source['title']} ({source['evidence_label']}) {source['url']}")
        if result.tools:
            print()
            _print(result.tools)
    elif args.command == "understand":
        _print(understand(" ".join(args.question)).as_dict())
    elif args.command == "stage":
        staged = staging.stage_from_text(" ".join(args.tnm), args.edition)
        if staged is None:
            print("No TNM combination found", file=sys.stderr)
            return 1
        _print(staged.as_dict())
    elif args.command == "options":
        histology = args.histology.lower()
        ctx = PatientContext(
            histology=histology, stage_group=args.stage.upper(), biomarkers=_biomarkers(args.biomarkers), pdl1_tps=args.pdl1, performance_status=args.ps
        )
        _print(therapy.match_therapies(ctx).as_dict())
    elif args.command == "screen":
        terms = [t.lower() for t in args.terms]
        split = terms.index("with") if "with" in terms else len(terms)
        ctx = PatientContext(current_medicines=terms[split + 1 :])
        _print(safety_screen.screen(terms[:split], ctx).as_dict())
    elif args.command == "carboplatin":
        _print([s.as_dict() for s in dosing.carboplatin_from_patient(args.auc, args.age, args.weight, args.creatinine, args.sex)])
    elif args.command == "serve":
        import uvicorn

        uvicorn.run("carina.main:app", host=args.host, port=args.port)
    return 0


def _biomarkers(values: list[str]) -> list[str]:
    aliases = {
        "EGFR": "EGFR_COMMON",
        "KRAS": "KRAS_G12C",
        "G12C": "KRAS_G12C",
        "BRAF": "BRAF_V600",
        "MET": "MET_EX14",
        "HER2": "HER2_MUT",
        "T790M": "EGFR_T790M",
        "EXON20": "EGFR_EXON20_INS",
    }
    return [aliases.get(v.upper(), v.upper()) for v in values]


if __name__ == "__main__":
    raise SystemExit(main())
