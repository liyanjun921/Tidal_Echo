"""Same-origin Luné web + authenticated relay; keep api_loop on loopback only."""
from contextlib import asynccontextmanager
from pathlib import Path
import os
import sqlite3

import httpx

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from backend import app as relay


@asynccontextmanager
async def lifespan(app):
    async with relay.lifespan(relay.app):
        yield


app = FastAPI(lifespan=lifespan)


@app.get("/readyz")
async def ready():
    """Probe the real dependencies without exposing owner state or credentials."""
    ok = True
    try:
        with sqlite3.connect("file:" + str(Path(relay.DB_PATH).resolve()) + "?mode=ro", uri=True) as c:
            c.execute("SELECT id FROM messages LIMIT 1").fetchone()
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            response = await client.get("http://127.0.0.1:3020/healthz")
            ok = response.status_code == 200 and response.json().get("ok") is True
        if os.environ.get("LUNE_LATENT_AUTO_SETUP") == "1":
            from backend.lune_memory import LatentEngine
            ok = ok and LatentEngine(relay.DB_PATH).passive_status()["assets_ready"]
    except (OSError, ValueError, sqlite3.Error, httpx.HTTPError):
        ok = False
    return JSONResponse({"ok": bool(ok)}, status_code=200 if ok else 503)


app.mount("/relay", relay.app)
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "web", html=True), name="web")
