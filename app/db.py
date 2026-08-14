from collections.abc import Generator

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import ASSETS, DATA_DIR, DB_PATH, SOURCES
from app.models import Asset, Base, Source


def _sqlite_url() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DB_PATH}"


engine = create_engine(
    _sqlite_url(),
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _fk_on(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        _seed_references(session)
        session.commit()


def _seed_references(session: Session) -> None:
    import json

    existing_sources = {s.code for s in session.scalars(select(Source)).all()}
    for item in SOURCES:
        if item["code"] not in existing_sources:
            session.add(Source(**item))

    existing_assets = {a.symbol for a in session.scalars(select(Asset)).all()}
    for item in ASSETS:
        if item["symbol"] not in existing_assets:
            session.add(
                Asset(
                    symbol=item["symbol"],
                    name=item["name"],
                    coingecko_id=item["coingecko_id"],
                    keywords_json=json.dumps(item["keywords"], ensure_ascii=False),
                )
            )


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
