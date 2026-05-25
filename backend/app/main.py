import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.database import init_db
from app.services.pipeline import pipeline_manager
from app.routers import cameras, alerts, roi, settings
from app.ws.live_feed import router as ws_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Hospital Monitor...")
    init_db()
    await pipeline_manager.start()
    logger.info("System ready")
    yield
    logger.info("Shutting down...")
    await pipeline_manager.stop()


app = FastAPI(title="Hospital Monitor", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST routers
app.include_router(cameras.router)
app.include_router(alerts.router)
app.include_router(roi.router)
app.include_router(settings.router)

# WebSocket router
app.include_router(ws_router)

# Test WebSocket page
from fastapi.responses import HTMLResponse

@app.get("/test-ws")
async def test_ws_page():
    with open(Path(__file__).resolve().parent.parent / "test_ws.html") as f:
        return HTMLResponse(f.read())

# Serve frontend static files if built
frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
