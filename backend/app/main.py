from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.routers.matches import router as matches_router
from app.repository import repair_equivalent_player_profiles
from app.routers.players import router as players_router
from app.services.sync_service import LiveSyncService
from app.websocket_manager import live_connections

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # Lightweight compatibility for local databases created before 2026 event cards
    # were added. Fresh installs receive the fields from SQLAlchemy metadata.
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE international_appearances ADD COLUMN IF NOT EXISTS yellow_cards INTEGER NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE international_appearances ADD COLUMN IF NOT EXISTS red_cards INTEGER NOT NULL DEFAULT 0"))

    # Older local installs could create separate ESPN/StatsBomb profiles for the
    # same player when the providers formatted accents differently. Repair them at
    # startup so their history feeds one player file and one projection.
    with SessionLocal() as session:
        merged = repair_equivalent_player_profiles(session)
        if merged:
            logger.info("Merged %s duplicate player profile(s) by normalized identity", merged)

    sync_service = LiveSyncService(settings, live_connections)
    app.state.sync_service = sync_service
    stop_event = asyncio.Event()

    # Make the current scoreboard available before the first browser request.
    # A complete tournament sweep can take longer and must never delay a live
    # fixture from reaching Match Desk.
    try:
        await sync_service.sync_live_window()
    except Exception:
        logger.exception("Initial live-window sync failed")

    # Keep the slower full schedule/event audit off the critical startup path.
    full_sync_task = asyncio.create_task(sync_service.sync_once(force_full_fixture_refresh=True))
    task = asyncio.create_task(sync_service.run_forever(stop_event))

    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        full_sync_task.cancel()
        for running in (task, full_sync_task):
            try:
                await running
            except asyncio.CancelledError:
                pass
        await sync_service.provider.aclose()


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(matches_router)
app.include_router(players_router)


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {"status": "ok", "demo_mode": settings.demo_mode}


@app.websocket("/ws/live")
async def live_updates(websocket: WebSocket) -> None:
    await live_connections.connect(websocket)
    try:
        snapshot = await asyncio.to_thread(app.state.sync_service.snapshot)
        await websocket.send_json({"type": "matches.snapshot", "matches": snapshot})

        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        await live_connections.disconnect(websocket)
