"""Install the user's pinned, unmodified MIT Ombre Brain checkout separately."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.ombre_runtime import REVISION, source


def stamp(destination):
    actual = subprocess.check_output(['git', '-C', str(destination), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != REVISION or subprocess.check_output(['git', '-C', str(destination), 'diff', '--name-only', 'HEAD'], text=True).strip():
        raise ValueError('Ombre source differs from the tested revision; owner changes preserved')
    files = [p for part in ('src', 'frontend') for p in (destination / part).rglob('*')
             if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    files += [destination / 'VERSION', destination / 'LICENSE', destination / 'NOTICE.md', destination / 'AUTHORS.md']
    marker = {'revision': REVISION, 'files': {str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    (destination.parent / (destination.name + '.lune-verified.json')).write_text(json.dumps(marker))


def install(destination):
    destination = Path(destination).resolve()
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
            stage = Path(temp) / 'source'
            subprocess.run(['git', 'clone', '--no-checkout', 'https://github.com/liyanjun921/Ombre-Brain.git', str(stage)], check=True)
            subprocess.run(['git', '-C', str(stage), 'checkout', '--detach', REVISION], check=True)
            stage.rename(destination)
    stamp(destination)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=source())
    print(install(parser.parse_args().destination))
