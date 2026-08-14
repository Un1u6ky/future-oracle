from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.db import get_session, init_db
from app.ingest.pipeline import run_ingest
from app.models import Asset, Forecast, MarketSnapshot
from app.web.present import (
    DIRECTION_RU,
    RISK_RU,
    accuracy_stats,
    fmt_pct,
    fmt_price,
    fmt_when,
    last_run,
    latest_fng,
    latest_live_forecasts,
    parse_json,
    recent_news,
    serialize_forecast,
    source_rows,
)

ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.filters["price"] = fmt_price
templates.env.filters["pct"] = fmt_pct
templates.env.filters["when"] = fmt_when
templates.env.globals["DIRECTION_RU"] = DIRECTION_RU
templates.env.globals["RISK_RU"] = RISK_RU

app = FastAPI(
    title="Future Oracle — Crypto Pulse",
    description="Учебный предсказатель 24ч-направления криптоактивов. Не финансовый совет.",
    version=__version__,
)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.on_event("startup")
def _startup() -> None:
    init_db()


def _ctx(request: Request, session: Session, **extra):
    return {
        "request": request,
        "accuracy": accuracy_stats(session),
        "fng": latest_fng(session),
        "run": last_run(session),
        "version": __version__,
        **extra,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session)):
    cards = []
    for asset, forecast in latest_live_forecasts(session):
        cards.append(
            {
                "asset": asset,
                "forecast": forecast,
                "used": parse_json(forecast.used_data_json, {}),
            }
        )
    return templates.TemplateResponse("index.html", _ctx(request, session, cards=cards))


@app.get("/asset/{symbol}", response_class=HTMLResponse)
def asset_page(symbol: str, request: Request, session: Session = Depends(get_session)):
    asset = session.scalars(select(Asset).where(Asset.symbol == symbol.upper())).first()
    if not asset:
        raise HTTPException(404, "Актив не найден")
    forecast = session.scalars(
        select(Forecast)
        .where(Forecast.asset_id == asset.id, Forecast.kind == "live")
        .order_by(Forecast.created_at.desc())
        .limit(1)
    ).first()
    if not forecast:
        raise HTTPException(404, "Прогноза ещё нет — обновите данные")
    history = session.scalars(
        select(Forecast)
        .where(Forecast.asset_id == asset.id)
        .order_by(Forecast.as_of.desc())
        .limit(12)
    ).all()
    snapshots = session.scalars(
        select(MarketSnapshot)
        .where(MarketSnapshot.asset_id == asset.id)
        .order_by(MarketSnapshot.captured_at.desc())
        .limit(10)
    ).all()
    payload = serialize_forecast(forecast, asset)
    return templates.TemplateResponse(
        "asset.html",
        _ctx(
            request,
            session,
            asset=asset,
            forecast=forecast,
            payload=payload,
            history=history,
            snapshots=snapshots,
            used=payload["used_data"],
            breakdown=payload["breakdown"],
        ),
    )


@app.get("/methodology", response_class=HTMLResponse)
def methodology(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse("methodology.html", _ctx(request, session))


@app.get("/data", response_class=HTMLResponse)
def data_page(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(
        "data.html",
        _ctx(
            request,
            session,
            sources=source_rows(session),
            news=recent_news(session, 30),
        ),
    )


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request, session: Session = Depends(get_session)):
    rows = session.scalars(
        select(Forecast).where(Forecast.resolved_at.is_not(None)).order_by(Forecast.as_of.desc())
    ).all()
    return templates.TemplateResponse("history.html", _ctx(request, session, rows=rows))


@app.post("/refresh")
def refresh(session: Session = Depends(get_session)):
    run_ingest(session)
    return RedirectResponse("/", status_code=303)


@app.get("/api/forecasts")
def api_forecasts(session: Session = Depends(get_session)):
    return [
        serialize_forecast(forecast, asset)
        for asset, forecast in latest_live_forecasts(session)
    ]


@app.get("/api/forecasts/{symbol}")
def api_forecast(symbol: str, session: Session = Depends(get_session)):
    asset = session.scalars(select(Asset).where(Asset.symbol == symbol.upper())).first()
    if not asset:
        raise HTTPException(404)
    forecast = session.scalars(
        select(Forecast)
        .where(Forecast.asset_id == asset.id, Forecast.kind == "live")
        .order_by(Forecast.created_at.desc())
        .limit(1)
    ).first()
    if not forecast:
        raise HTTPException(404)
    return serialize_forecast(forecast, asset)


@app.get("/api/accuracy")
def api_accuracy(session: Session = Depends(get_session)):
    return accuracy_stats(session)
