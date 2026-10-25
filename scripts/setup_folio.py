"""Install verified Folio UI/prompt assets; never execute its older server."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.ombre_folio_runtime import REPOSITORY, REVISION, source


def install(destination):
    destination = Path(destination).resolve()
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
            stage = Path(temp) / 'source'
            subprocess.run(['git', 'clone', '--no-checkout', REPOSITORY, str(stage)], check=True)
            subprocess.run(['git', '-C', str(stage), 'checkout', '--detach', REVISION], check=True)
            stage.rename(destination)
    actual = subprocess.check_output(['git', '-C', str(destination), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != REVISION or subprocess.check_output(['git', '-C', str(destination), 'diff', '--name-only', 'HEAD'], text=True).strip():
        raise ValueError('Folio checkout differs from the tested revision; changes preserved')
    paths = subprocess.check_output(['git', '-C', str(destination), 'ls-files', '-z']).decode().split('\0')
    files = [p for p in paths if p.startswith('v2/') or p in {'LICENSE', 'CHANGES.md', 'dehydrator.py','families.py'}]
    marker = {'revision': REVISION, 'files': {p: hashlib.sha256((destination / p).read_bytes()).hexdigest() for p in files}}
    (destination.parent / (destination.name + '.lune-verified.json')).write_text(json.dumps(marker))
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=source())
    print(install(parser.parse_args().destination))
