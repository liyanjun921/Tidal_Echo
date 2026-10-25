"""Verify the MIT Xinchao directory only; never run the bundled Ombre fork."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.xinchao_runtime import REPOSITORY,REVISION,source


def install(destination):
    destination=Path(destination).resolve()
    if not destination.exists():
        destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
            stage=Path(tmp)/'source'
            subprocess.run(['git','clone','--no-checkout',REPOSITORY,str(stage)],check=True)
            subprocess.run(['git','-C',str(stage),'checkout','--detach',REVISION],check=True)
            stage.rename(destination)
    actual=subprocess.check_output(['git','-C',str(destination),'rev-parse','HEAD'],text=True).strip()
    if actual!=REVISION or subprocess.check_output(['git','-C',str(destination),'diff','--name-only','HEAD'],text=True).strip():
        raise ValueError('Xinchao source differs from the tested revision; changes preserved')
    names=subprocess.check_output(['git','-C',str(destination),'ls-files','-z']).decode().split('\0')
    names=[p for p in names if p.startswith(('xinchao/src/','xinchao/configs/')) or p in {'xinchao/LICENSE','xinchao/package.json'}]
    marker={'revision':REVISION,'files':{name:hashlib.sha256((destination/name).read_bytes()).hexdigest() for name in names}}
    (destination.parent/(destination.name+'.lune-verified.json')).write_text(json.dumps(marker))
    return destination


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',type=Path,default=source())
    print(install(parser.parse_args().destination))
