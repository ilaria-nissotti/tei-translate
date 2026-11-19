"""Command line: python -m tei_translate translate IN.xml [-o OUT.xml] [--engine tag]"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from tei_translate.pipeline.document import DEFAULT_PAIR, load_pair, translate_document
from tei_translate.pipeline.policy import REPO_ROOT, Policy


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tei_translate")
    sub = parser.add_subparsers(dest="command", required=True)

    t = sub.add_parser("translate", help="translate one TEI file")
    t.add_argument("input", type=Path)
    t.add_argument("-o", "--output", type=Path, help="default: outputs/<input name>.<tgt>.xml")
    t.add_argument("--pair", type=Path, default=DEFAULT_PAIR, help="language pair config (default: grc-en)")
    t.add_argument("--engine", help="override the engine from the pair config: identity, tag, opus-grk-en, "
                                    "opus-bible-ine, madlad-3b, marian:<HF model id>, madlad:<HF model id>")
    t.add_argument("--policy", type=Path, help="override the policy file from the pair config")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    logging.getLogger("tei_translate").setLevel(logging.INFO)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    pair = load_pair(args.pair)
    policy = Policy.load(args.policy) if args.policy else None
    result = translate_document(args.input, pair, engine=args.engine, policy=policy)

    output = args.output or REPO_ROOT / "outputs" / f"{args.input.stem}.{pair['tgt']}.xml"
    output.parent.mkdir(parents=True, exist_ok=True)
    result.tree.write(str(output), encoding="UTF-8", xml_declaration=True)

    print(result.report.summary())
    print(f"written: {output}")
    return 0 if result.report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
