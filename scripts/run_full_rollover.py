"""CLI: run the monthly rollover for every F&O stock that doesn't have current-cycle levels yet."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.dhan_client import DhanClient
from app.data.universe import get_fno_universe
from app.db import database as db
from app import pipeline


def main() -> None:
    db.init_db()
    client = DhanClient()
    stocks = get_fno_universe()
    print(f"Universe: {len(stocks)} stocks")

    def progress(done, total, symbol):
        print(f"[{done}/{total}] {symbol}", flush=True)

    succeeded, errors = pipeline.run_universe_rollover(client, stocks, progress_cb=progress)
    print(f"\nDone. Succeeded: {len(succeeded)}  Errors: {len(errors)}")
    for e in errors:
        print(" ERROR:", e)


if __name__ == "__main__":
    main()
