"""Run any supported original Latent utility from the separately verified source.

Example: python scripts/latent_tools.py forge-session check /private/session.jsonl
Native options and all their failure/confirmation guards are preserved verbatim.
"""
import os
from pathlib import Path
import runpy
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from lune_memory import LatentEngine

COMMANDS = {"initialize": "memory_init.py", "import": "memory_import.py", "mcp": "mcp_server.py",
    "archive": "background_archive.py", "forge-session": "forge_session.py", "claude-hook": "claude_code_hook.py",
    "reference-host": "reference_host.py", "probe": "probe_guard.py", "regression": "regression_set.py",
    "facts": "passive_facts.py", "entities": "memory_retrieval.py", "degradation": "degradation_protocol.py"}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        raise SystemExit("可用原版入口：" + ", ".join(COMMANDS))
    engine = LatentEngine(os.environ.get("RELAY_DB", "relay.db"))
    if not engine.installation():
        raise SystemExit("先运行 python scripts/setup_latent.py --vectors 安装并验证原版源码")
    script = engine.source() / "src" / COMMANDS[sys.argv[1]]
    sys.path.insert(0, str(script.parent))
    sys.argv = [str(script), *sys.argv[2:]]
    runpy.run_path(str(script), run_name="__main__")
