"""Load Folio enhancements into the same modern Ombre runtime and vault."""
from pathlib import Path
import runpy
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import ombre_runtime as ob
from backend import ombre_folio_runtime as folio

if not ob.installed():
    raise SystemExit('Ombre source verification failed')
sys.path.insert(0, str(ob.source() / 'src'))
if folio.installed():
    import web
    original = web.register_all
    def register_all(mcp):
        original(mcp)
        from backend.ombre_folio import register
        register(mcp)
    web.register_all = register_all
runpy.run_path(str(ob.source() / 'src/server.py'), run_name='__main__')
