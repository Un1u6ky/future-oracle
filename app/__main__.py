"""python -m app          — запуск сервера
python -m app ingest   — принудительный сбор данных
"""

from __future__ import annotations

import sys

import uvicorn

from app.db import SessionLocal, init_db
from app.ingest.pipeline import recompute_forecasts, run_ingest


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "ingest":
        init_db()
        with SessionLocal() as session:
            run = run_ingest(session)
            print(run.status, run.stats_json or run.error)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "recompute":
        init_db()
        with SessionLocal() as session:
            print(recompute_forecasts(session))
        return
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
