"""Run both services, forwarding termination and stopping if either child fails."""
import os
import signal
import shutil
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
sys.path.insert(0, str(root))
from backend import ombre_runtime as ombre
from backend import xinchao_runtime as xinchao
if os.environ.get('LUNE_OMBRE_AUTO_SETUP') == '1':
    from setup_ombre import install as install_ombre
    install_ombre(ombre.source())
if os.environ.get('LUNE_FOLIO_AUTO_SETUP') == '1':
    from setup_folio import install as install_folio
    from backend.ombre_folio_runtime import source as folio_source
    install_folio(folio_source())
if os.environ.get('LUNE_XINCHAO_AUTO_SETUP')=='1':
    from setup_xinchao import install as install_xinchao
    install_xinchao(xinchao.source())
os.environ.setdefault("RELAY_URL", "http://127.0.0.1:" + os.environ.get("PORT", "8080") + "/relay")
children = []
native_children={}


def stop(signum=None, frame=None):
    for child in children+[item[0] for item in native_children.values()]:
        if child.poll() is None:
            child.terminate()


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    cinema_source = root / 'backend/vendor/open_watch_cinema/server.mjs'
    cinema_node = shutil.which('node')
    if cinema_source.is_file() and cinema_node:
        major = int(subprocess.check_output([cinema_node, '--version'], text=True).strip().lstrip('v').split('.')[0])
        if major >= 24:
            cinema_env = {**os.environ, 'OPEN_BROWSER': '0', 'PORT': os.environ.get('LUNE_CINEMA_PORT', '4182'),
                          'LOCAL_DATA_ROOT': os.environ.get('LUNE_CINEMA_DATA') or str(Path(os.environ.get('RELAY_DB', 'relay.db')).resolve().parent / 'cinema')}
            children.append(subprocess.Popen([cinema_node, str(cinema_source)], env=cinema_env, cwd=cinema_source.parent))
        else:
            print('Cinema unavailable: Node.js 24+ is required', flush=True)
    if ombre.installed():
        for scope in ombre.SCOPES:
            children.append(subprocess.Popen([sys.executable, str(root / 'scripts/run_ombre.py')],
                cwd=ombre.source(), env=ombre.prepare(scope)))
    if xinchao.installed():
        if not xinchao.node() or int(subprocess.check_output([xinchao.node(),'--version'],text=True).strip().lstrip('v').split('.')[0])<20:raise RuntimeError('Xinchao requires Node.js 20+ in the service environment')
        import json
        for scope in xinchao.SCOPES:
            native_children[scope]=(subprocess.Popen([xinchao.node(),str(root/'scripts/run_xinchao.mjs')],env=xinchao.prepare(scope)),json.dumps(xinchao.config(scope),sort_keys=True))
    children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "api_loop:app", "--app-dir", "examples", "--host", "127.0.0.1", "--port", "3020", "--no-access-log"]))
    children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.lune_server:app", "--host", "0.0.0.0", "--port", os.environ.get("PORT", "8080"), "--no-access-log"]))
    while all(child.poll() is None for child in children):
        for scope,(child,fingerprint) in list(native_children.items()):
            changed=json.dumps(xinchao.config(scope),sort_keys=True)
            if changed!=fingerprint:
                child.terminate()
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.wait()
                native_children[scope]=(subprocess.Popen([xinchao.node(),str(root/'scripts/run_xinchao.mjs')],env=xinchao.prepare(scope)),changed)
            elif child.poll() is not None:
                raise RuntimeError('Xinchao native process stopped: '+scope)
        time.sleep(.25)
finally:
    stop()
    for child in children+[item[0] for item in native_children.values()]:
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
sys.exit(next((child.returncode for child in children if child.returncode), 0))
