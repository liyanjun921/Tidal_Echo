"""Install a pinned, separate Latent checkout for the owner's internal use.

No Latent code is bundled in Luné releases or container images.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

REPOSITORY = "https://github.com/liyanjun921/Latent-memory.git"
REVISION = "835250d080c02d9553d3b96d9a2753773a4a0c3c"


def stamp(source):
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual != REVISION:
        raise ValueError("Latent revision does not match the tested version")
    if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True).strip():
        raise ValueError("Latent source has local changes; use an unmodified checkout")
    files = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted((source / "src").glob("*.py"))}
    if "src/memory_retrieval.py" not in files or not (source / "LICENSE").is_file():
        raise ValueError("Latent source is incomplete")
    # Marker lives outside its Git checkout and includes no private memory.
    marker = source.parent / (source.name + ".lune-verified.json")
    marker.write_text(json.dumps({"revision": REVISION, "files": files}), encoding="utf-8")
    os.chmod(marker, 0o600)


def install(destination):
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        stamp(destination)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="latent-install-", dir=destination.parent) as temp:
        stage = Path(temp) / "source"
        subprocess.run(["git", "clone", "--no-checkout", REPOSITORY, str(stage)], check=True)
        subprocess.run(["git", "-C", str(stage), "checkout", "--detach", REVISION], check=True)
        # An interrupted install never becomes the active source directory.
        stage.rename(destination)
    stamp(destination)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="安装独立的 Latent 运行源码，不包含或上传私人记忆")
    parser.add_argument("--destination", type=Path, default=Path(os.environ.get("RELAY_DB", "relay.db")).resolve().parent / "lune-private" / "latent-source")
    args = parser.parse_args()
    print("Latent source: " + str(install(args.destination)))
