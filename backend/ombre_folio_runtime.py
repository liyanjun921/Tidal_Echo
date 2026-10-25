"""Pinned Folio assets and prompts, used by the existing Ombre process only."""
import hashlib
import json
import os
from pathlib import Path

try:
    from . import ombre_runtime as ob
except ImportError:
    import ombre_runtime as ob

REPOSITORY = 'https://github.com/liyanjun921/OmbreBrain-folio.git'
REVISION = 'bf6887575fa8e6fa519279be9dc7e5886a29d2ea'


def source():
    return Path(os.environ.get('LUNE_FOLIO_SOURCE') or ob.root() / 'folio-source')


def installed():
    try:
        marker = json.loads((source().parent / (source().name + '.lune-verified.json')).read_text())
        return marker['revision'] == REVISION and all(
            hashlib.sha256((source() / name).read_bytes()).hexdigest() == digest
            for name, digest in marker['files'].items())
    except (OSError, ValueError, KeyError):
        return False
