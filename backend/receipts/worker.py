"""`python -m receipts.worker [--once] [--interval 60]`: poll -> generate -> place -> sync, forever."""
from __future__ import annotations

import argparse
import logging
import time

from . import get_pipeline

log = logging.getLogger("receipts.worker")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Receipts order worker")
    ap.add_argument("--once", action="store_true", help="run one pass and exit")
    ap.add_argument("--interval", type=float, default=60.0, help="seconds between passes")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = get_pipeline()
    s = p.settings
    log.info("receipts worker: data=%s whop=%s slant=%s craftcloud=%s", s.data_dir,
             "mock" if s.whop_mock else "live", "mock" if s.slant_mock else "live",
             "mock" if s.craftcloud_mock else "live")
    while True:
        try:
            log.info("pass: %s", p.run_once())
        except Exception:
            log.exception("worker pass failed")
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
