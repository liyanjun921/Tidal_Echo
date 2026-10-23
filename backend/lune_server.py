"""Same-origin Luné web + authenticated relay; keep api_loop on loopback only."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from backend import app as relay


@asynccontextmanager
async def lifespan(app):
    async with relay.lifespan(relay.app):
        yield


app = FastAPI(lifespan=lifespan)
app.mount("/relay", relay.app)
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "web", html=True), name="web")
