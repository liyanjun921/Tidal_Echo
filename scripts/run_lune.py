"""Run both services, forwarding termination and stopping if either child fails."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
if not os.environ.get("RELAY_SECRET"):
    raise SystemExit("Set RELAY_SECRET to a long, unique password before starting Luné")
for key in ("RELAY_DB", "LOOP_CONFIG"):
    if os.environ.get(key):
        Path(os.environ[key]).parent.mkdir(parents=True, exist_ok=True)
if os.environ.get("LUNE_LATENT_AUTO_SETUP") == "1":
    from setup_latent import install
    source = Path(os.environ.get("LUNE_LATENT_SOURCE") or Path(os.environ.get("RELAY_DB", "relay.db")).resolve().parent / "lune-private" / "latent-source")
    install(source)
    os.environ["LUNE_LATENT_SOURCE"] = str(source)
    cache = Path(os.environ.get("LUNE_PASSIVE_MODEL_CACHE") or source.parent / "latent-models")
    if not (cache / "lune-passive-ready.json").is_file():
        subprocess.run([sys.executable, "scripts/setup_latent.py", "--destination", str(source), "--vectors", "--model-cache", str(cache)], check=True)
    os.environ["LUNE_PASSIVE_MODEL_CACHE"] = str(cache)
os.environ.setdefault("RELAY_URL", "http://127.0.0.1:" + os.environ.get("PORT", "8080") + "/relay")
children = []


def stop(signum=None, frame=None):
    for child in children:
        if child.poll() is None:
            child.terminate()


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "api_loop:app", "--app-dir", "examples", "--host", "127.0.0.1", "--port", "3020", "--no-access-log"]))
    children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.lune_server:app", "--host", "0.0.0.0", "--port", os.environ.get("PORT", "8080"), "--no-access-log"]))
    while all(child.poll() is None for child in children):
        time.sleep(.25)
finally:
    stop()
    for child in children:
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
sys.exit(next((child.returncode for child in children if child.returncode), 0))
